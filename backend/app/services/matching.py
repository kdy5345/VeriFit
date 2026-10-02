"""사용자 조건으로 저장된 상품의 실제 적용 금리를 계산한다.

LLM을 쓰지 않는다 — 여기서부터는 전부 결정론적 코드다. RateOptionVerdict의
도달가능성 검사(reachability.py)가 "이 상품이 이해 가능한가"를 봤다면, 여기는
"이 사용자가 실제로 얼마를 받는가"를 본다. 로직은 비슷하다: Bonus의
combinator(AND/OR/SOLE)를 판정하고, 중복 불가 쌍은 더 높은 쪽만 인정하고,
그룹 한도로 자른다.
"""

from dataclasses import dataclass
from itertools import combinations

from app.schemas.graph import Bonus, Product, RateOption, RequirementCombinator
from app.schemas.user import ConditionStatus, UserProfile


def bonus_status(bonus: Bonus, profile: UserProfile) -> ConditionStatus:
    statuses = [profile.condition_status(r.codes, r.param) for r in bonus.requirements]
    if bonus.combinator == RequirementCombinator.AND:
        if ConditionStatus.UNSATISFIED in statuses:
            return ConditionStatus.UNSATISFIED
        return ConditionStatus.UNKNOWN if ConditionStatus.UNKNOWN in statuses else ConditionStatus.SATISFIED
    if ConditionStatus.SATISFIED in statuses:
        return ConditionStatus.SATISFIED
    return ConditionStatus.UNKNOWN if ConditionStatus.UNKNOWN in statuses else ConditionStatus.UNSATISFIED


def best_bonus_combo(bonuses: list[Bonus], group) -> list[Bonus]:
    """중복 불가 관계가 연결된 경우도 최대 조합을 정확히 선택한다."""
    best, best_total = [], -1
    exclusive = {frozenset(pair) for pair in group.exclusive_pairs}
    if not exclusive:
        return bonuses
    for size in range(len(bonuses) + 1):
        for combo in combinations(bonuses, size):
            if any(frozenset((a.id, b.id)) in exclusive for a, b in combinations(combo, 2)):
                continue
            total = sum(b.rate_bps for b in combo)
            if total > best_total:
                best, best_total = list(combo), total
    return best


@dataclass(frozen=True)
class RateOptionMatch:
    term_months: int
    achieved_rate_bps: int
    satisfied_bonuses: tuple[Bonus, ...]
    unmet_bonuses: tuple[Bonus, ...]  # 조건을 더 알면 받을 수 있는 것들 (설명·다음 질문용)
    dropped_by_exclusivity: tuple[str, ...]  # 둘 다 만족했지만 중복 불가라 뺀 쪽
    unknown_bonuses: tuple[Bonus, ...] = ()
    potential_rate_bps: int = 0


def evaluate_rate_option(option: RateOption, profile: UserProfile) -> RateOptionMatch:
    if option.bonus_group is None:
        return RateOptionMatch(option.term_months, option.base_rate_bps, (), (), (), (), option.base_rate_bps)

    statuses = {b.id: bonus_status(b, profile) for b in option.bonus_group.bonuses}
    satisfied = [b for b in option.bonus_group.bonuses if statuses[b.id] == ConditionStatus.SATISFIED]
    satisfied_by_id = {b.id: b for b in satisfied}
    # id 기준으로 걸러야 한다 — Pydantic 모델은 값이 같으면 같은 객체로 취급돼서
    # `not in` 같은 멤버십 비교로 걸러내면 우연히 값이 같은 다른 항목이 섞일 수 있다.
    unmet = [b for b in option.bonus_group.bonuses if b.id not in satisfied_by_id]

    # 중복 불가 쌍: 둘 다 만족했으면 낮은 쪽을 빼고 높은 쪽만 인정한다.
    counted = best_bonus_combo(satisfied, option.bonus_group)
    dropped = [b.id for b in satisfied if b not in counted]
    total_bonus_bps = sum(b.rate_bps for b in counted)
    if option.bonus_group.cap_bps is not None:
        total_bonus_bps = min(total_bonus_bps, option.bonus_group.cap_bps)

    achieved = min(option.base_rate_bps + total_bonus_bps, option.max_rate_bps)
    unknown = [b for b in option.bonus_group.bonuses if statuses[b.id] == ConditionStatus.UNKNOWN]
    possible = best_bonus_combo([b for b in satisfied + unknown if not b.has_unsupported_requirement], option.bonus_group)
    potential_bonus = sum(b.rate_bps for b in possible)
    if option.bonus_group.cap_bps is not None:
        potential_bonus = min(potential_bonus, option.bonus_group.cap_bps)
    return RateOptionMatch(
        term_months=option.term_months,
        achieved_rate_bps=achieved,
        satisfied_bonuses=tuple(counted),
        unmet_bonuses=tuple(unmet),
        dropped_by_exclusivity=tuple(dropped),
        unknown_bonuses=tuple(unknown),
        potential_rate_bps=min(option.base_rate_bps + potential_bonus, option.max_rate_bps),
    )


@dataclass(frozen=True)
class ProductMatch:
    product: Product
    rate_option: RateOption
    match: RateOptionMatch
    eligibility_warning: bool  # OTHER 자격조건이 있어 직접 확인이 필요한 경우
    eligibility_status: ConditionStatus = ConditionStatus.SATISFIED
    eligibility_reasons: tuple[str, ...] = ()


def find_matches(products: list[Product], profile: UserProfile) -> list[ProductMatch]:
    """사용자가 원하는 term_months와 정확히 일치하는 RateOption만 평가한다."""
    results: list[ProductMatch] = []
    for product in products:
        statuses = [profile.condition_status(e.codes, e.param) for e in product.eligibility]
        reasons = [e.evidence.quote for e, status in zip(product.eligibility, statuses) if status != ConditionStatus.SATISFIED]
        if product.max_limit_won is not None and profile.monthly_deposit_won > product.max_limit_won:
            statuses.append(ConditionStatus.UNSATISFIED)
            reasons.append(f"월 납입 한도 {product.max_limit_won:,}원 초과")
        eligibility_status = (ConditionStatus.UNSATISFIED if ConditionStatus.UNSATISFIED in statuses else
                              ConditionStatus.UNKNOWN if ConditionStatus.UNKNOWN in statuses else ConditionStatus.SATISFIED)
        eligibility_warning = eligibility_status != ConditionStatus.SATISFIED
        for option in product.rate_options:
            if option.term_months != profile.term_months:
                continue
            match = evaluate_rate_option(option, profile)
            results.append(ProductMatch(product, option, match, eligibility_warning, eligibility_status, tuple(reasons)))
    return sorted(results, key=lambda pm: (pm.eligibility_status == ConditionStatus.UNSATISFIED, -pm.match.achieved_rate_bps))
