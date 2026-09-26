"""사용자 조건으로 저장된 상품의 실제 적용 금리를 계산한다.

LLM을 쓰지 않는다 — 여기서부터는 전부 결정론적 코드다. RateOptionVerdict의
도달가능성 검사(reachability.py)가 "이 상품이 이해 가능한가"를 봤다면, 여기는
"이 사용자가 실제로 얼마를 받는가"를 본다. 로직은 비슷하다: Bonus의
combinator(AND/OR/SOLE)를 판정하고, 중복 불가 쌍은 더 높은 쪽만 인정하고,
그룹 한도로 자른다.
"""

from dataclasses import dataclass

from app.schemas.graph import Bonus, Product, RateOption, RequirementCombinator
from app.schemas.requirements import RequirementCode
from app.schemas.user import UserProfile


def _requirement_satisfied(ref, profile: UserProfile) -> bool:
    return profile.satisfies(ref.codes, ref.param)


def _bonus_satisfied(bonus: Bonus, profile: UserProfile) -> bool:
    results = [_requirement_satisfied(r, profile) for r in bonus.requirements]
    if bonus.combinator == RequirementCombinator.AND:
        return all(results)
    if bonus.combinator == RequirementCombinator.OR:
        return any(results)
    return results[0]  # SOLE: requirements 길이 1


@dataclass(frozen=True)
class RateOptionMatch:
    term_months: int
    achieved_rate_bps: int
    satisfied_bonuses: tuple[Bonus, ...]
    unmet_bonuses: tuple[Bonus, ...]  # 조건을 더 알면 받을 수 있는 것들 (설명·다음 질문용)
    dropped_by_exclusivity: tuple[str, ...]  # 둘 다 만족했지만 중복 불가라 뺀 쪽


def evaluate_rate_option(option: RateOption, profile: UserProfile) -> RateOptionMatch:
    if option.bonus_group is None:
        return RateOptionMatch(option.term_months, option.base_rate_bps, (), (), ())

    satisfied = [b for b in option.bonus_group.bonuses if _bonus_satisfied(b, profile)]
    satisfied_by_id = {b.id: b for b in satisfied}
    # id 기준으로 걸러야 한다 — Pydantic 모델은 값이 같으면 같은 객체로 취급돼서
    # `not in` 같은 멤버십 비교로 걸러내면 우연히 값이 같은 다른 항목이 섞일 수 있다.
    unmet = [b for b in option.bonus_group.bonuses if b.id not in satisfied_by_id]

    # 중복 불가 쌍: 둘 다 만족했으면 낮은 쪽을 빼고 높은 쪽만 인정한다.
    dropped: list[str] = []
    for id_a, id_b in option.bonus_group.exclusive_pairs:
        if id_a in satisfied_by_id and id_b in satisfied_by_id:
            lower = id_a if satisfied_by_id[id_a].rate_bps <= satisfied_by_id[id_b].rate_bps else id_b
            dropped.append(lower)

    counted = [b for b in satisfied if b.id not in dropped]
    total_bonus_bps = sum(b.rate_bps for b in counted)
    if option.bonus_group.cap_bps is not None:
        total_bonus_bps = min(total_bonus_bps, option.bonus_group.cap_bps)

    achieved = min(option.base_rate_bps + total_bonus_bps, option.max_rate_bps)
    return RateOptionMatch(
        term_months=option.term_months,
        achieved_rate_bps=achieved,
        satisfied_bonuses=tuple(counted),
        unmet_bonuses=tuple(unmet),
        dropped_by_exclusivity=tuple(dropped),
    )


@dataclass(frozen=True)
class ProductMatch:
    product: Product
    rate_option: RateOption
    match: RateOptionMatch
    eligibility_warning: bool  # OTHER 자격조건이 있어 직접 확인이 필요한 경우


def find_matches(products: list[Product], profile: UserProfile) -> list[ProductMatch]:
    """사용자가 원하는 term_months와 정확히 일치하는 RateOption만 평가한다."""
    results: list[ProductMatch] = []
    for product in products:
        eligibility_warning = any(
            RequirementCode.OTHER in e.codes for e in product.eligibility
        )
        for option in product.rate_options:
            if option.term_months != profile.term_months:
                continue
            match = evaluate_rate_option(option, profile)
            results.append(ProductMatch(product, option, match, eligibility_warning))
    return sorted(results, key=lambda pm: pm.match.achieved_rate_bps, reverse=True)
