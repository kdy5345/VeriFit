"""같은 모델을 여러 번 돌려 흔들리는 항목만 OTHER로 낮춘다.

한계를 분명히 해둔다: 이건 "독립된 다른 모델"의 대체품이 아니다. 다른 제공사 API가
없어 택한 차선책이고, 잡을 수 있는 오류의 종류가 다르다.
  - 잡을 수 있음: 모델이 매 호출마다 판단이 갈리는 애매한 경우 (확률적 오류)
  - 못 잡음: 모델이 매번 똑같이 확신에 차서 원문을 잘못 읽는 경우 (계통적 오류).
    이런 오류는 N번을 더 돌려도 N번 다 똑같이 틀린다. 이건 여전히
    app.services.reachability의 숫자 검증에 의존해야 한다.

병합 방식: runs[0]을 기준(baseline)으로 삼고, 같은 term의 다른 run들 중 동일한
evidence_quote(공백만 정규화, 텍스트는 그대로)를 가진 항목을 찾아 "숫자까지 포함해"
전부 같은지 대조한다. 하나라도 다르거나, 다른 run에 그 term 자체가 통째로 없거나,
그 quote를 아예 못 찾으면 그 항목은 codes=[other]로 강등한다. term 단위의 합산 한도와
중복 불가 쌍도 비교해, 갈리면 사용자 금리가 낮아지는 쪽(낮은 한도, 쌍의 합집합)을 쓴다.

수정 이력: 처음 버전은 fingerprint에 codes·combinator만 넣어서, rate_bps나
min_amount_won 같은 숫자가 run마다 달라도 "합의됨"으로 잘못 처리했다. 또한 어떤
run에서 term 전체가 통째로 빠진 경우를 감지하지 못했다 (dict comprehension이 그
run을 조용히 건너뜀). 둘 다 지적을 받고 고쳤다. eligibility도 계산에 직접 쓰이진
않지만 같은 방식으로 흔들림을 잡아 화면에 잘못된 자격 조건이 나가지 않게 한다.
"""

from dataclasses import dataclass, field

from app.schemas.extraction import (
    LlmBonus,
    LlmEligibility,
    LlmExtraction,
    LlmRateOptionBonuses,
    LlmRequirementRef,
)
from app.schemas.requirements import RequirementCode


def _normalize(text: str) -> str:
    return " ".join(text.split())


_Fingerprint = tuple


def _requirement_fingerprint(r: LlmRequirementRef) -> tuple:
    return (
        tuple(sorted(r.codes)),
        r.min_amount_won,
        r.min_months,
        r.min_count,
        r.channel,
    )


def _bonus_fingerprint(bonus: LlmBonus) -> _Fingerprint:
    """combinator + rate_bps + 각 requirement의 codes·금액·기간까지 전부 비교 대상.

    rate_bps를 포함한 이유: "급여이체 50만원, 0.7%p"와 "급여이체 50만원, 0.5%p"는
    codes는 같아도 명백히 다른 추출이고, 숫자가 서비스의 실제 계산 결과이므로 여기서
    갈리면 반드시 잡아야 한다.
    """
    reqs = tuple(sorted(_requirement_fingerprint(r) for r in bonus.requirements))
    return (bonus.combinator, bonus.rate_bps, reqs)


def _eligibility_fingerprint(e: LlmEligibility) -> _Fingerprint:
    return (tuple(sorted(e.codes)),)


def _downgrade_bonus_to_other(bonus: LlmBonus) -> LlmBonus:
    return bonus.model_copy(
        update={
            "rate_bps": 0,
            "combinator": "sole",
            "requirements": [LlmRequirementRef(codes=[RequirementCode.OTHER])],
            "label": f"{bonus.label} (자동 검증: 반복 시도 간 불일치로 강등)",
        }
    )


def _downgrade_eligibility_to_other(e: LlmEligibility) -> LlmEligibility:
    return e.model_copy(
        update={
            "codes": [RequirementCode.OTHER],
            "note": f"{e.note or ''} (자동 검증: 반복 시도 간 불일치로 강등)".strip(),
        }
    )


@dataclass
class ConsistencyReport:
    total_bonuses: int = 0
    downgraded: list[str] = field(default_factory=list)  # "term_months:label" 형태 기록
    downgraded_eligibility: list[str] = field(default_factory=list)
    group_conflicts: list[str] = field(default_factory=list)  # 합산 한도·중복 불가 불일치

    def notes(self) -> list[str]:
        """extraction_log에 남길 사람이 읽는 기록. 기간별 항목은 '12개월:' 접두어를 가진다."""
        return ([f"{item} 강등" for item in self.downgraded] + self.group_conflicts
                + [f"가입자격:{item} 강등" for item in self.downgraded_eligibility])


def _merge_group_fields(term_option: LlmRateOptionBonuses, others: list[LlmRateOptionBonuses | None],
                        report: ConsistencyReport) -> dict:
    """합산 한도와 중복 불가 쌍도 run마다 비교한다. 갈리면 사용자 금리가 낮아지는 쪽을 쓴다.

    - 한도: 하나라도 한도를 읽었다면 그중 가장 낮은 값 (한도는 금리를 깎기만 한다)
    - 중복 불가: 모든 run의 쌍을 합친다 (쌍이 늘면 동시에 받을 수 있는 우대가 줄어든다)
    bonus id는 run마다 다를 수 있어 쌍은 evidence_quote로 맞춰 비교한다.
    그래도 공시 최고금리와 안 맞으면 다음 단계의 도달가능성 검사가 걸러낸다.
    """
    term = term_option.term_months
    present = [o for o in others if o is not None]
    caps = [term_option.group_cap_bps] + [o.group_cap_bps for o in present]
    merged_cap = term_option.group_cap_bps
    if len(set(caps)) > 1:
        known = [c for c in caps if c is not None]
        merged_cap = min(known)
        report.group_conflicts.append(f"{term}개월:합산 한도 불일치 {caps} → {merged_cap}bp 적용")

    def quote_pairs(option: LlmRateOptionBonuses) -> set[frozenset[str]]:
        quotes = {b.id: _normalize(b.evidence_quote) for b in option.bonuses}
        return {frozenset((quotes[a], quotes[b])) for a, b in (p for p in option.exclusive_bonus_id_pairs if len(p) == 2)
                if a in quotes and b in quotes and a != b}

    baseline_pairs = quote_pairs(term_option)
    all_pairs = set(baseline_pairs)
    for option in present:
        all_pairs |= quote_pairs(option)
    id_by_quote = {_normalize(b.evidence_quote): b.id for b in term_option.bonuses}
    merged_pairs = [sorted(id_by_quote[q] for q in pair) for pair in all_pairs if all(q in id_by_quote for q in pair)]
    if all_pairs != baseline_pairs:
        report.group_conflicts.append(f"{term}개월:중복 불가 조건 불일치 → 모든 시도의 쌍 {len(merged_pairs)}개 적용")
    return {"group_cap_bps": merged_cap, "exclusive_bonus_id_pairs": merged_pairs}


def _already_other(codes: list[RequirementCode]) -> bool:
    return codes == [RequirementCode.OTHER]


def merge_self_consistency(runs: list[LlmExtraction]) -> tuple[LlmExtraction, ConsistencyReport]:
    if not runs:
        raise ValueError("runs가 비어 있습니다.")
    baseline = runs[0]
    other_runs = runs[1:]
    report = ConsistencyReport()

    # --- 우대조건 (rate_options.bonuses) -------------------------------------
    merged_rate_options: list[LlmRateOptionBonuses] = []
    for term_option in baseline.rate_options:
        # 다른 run 각각에 대해 "이 term이 있으면 quote->bonus 사전, 아예 없으면 빈 사전"을
        # 만든다. 빈 사전이면 이 term의 모든 bonus가 "그 run에서는 못 찾음"으로 처리되어
        # 자동으로 불일치 판정을 받는다 (term 전체가 빠진 경우를 놓치지 않기 위함).
        other_term_indexes = [
            next(
                (
                    {_normalize(b.evidence_quote): b for b in run_option.bonuses}
                    for run_option in run.rate_options
                    if run_option.term_months == term_option.term_months
                ),
                {},
            )
            for run in other_runs
        ]

        merged_bonuses: list[LlmBonus] = []
        for bonus in term_option.bonuses:
            report.total_bonuses += 1
            if _already_other(bonus.requirements[0].codes) and len(bonus.requirements) == 1:
                # 이미 other인 항목을 또 other로 강등해봐야 의미 없다.
                merged_bonuses.append(bonus)
                continue

            quote_key = _normalize(bonus.evidence_quote)
            baseline_fp = _bonus_fingerprint(bonus)
            agrees_everywhere = all(
                (match := other_by_quote.get(quote_key)) is not None
                and _bonus_fingerprint(match) == baseline_fp
                for other_by_quote in other_term_indexes
            )

            if agrees_everywhere:
                merged_bonuses.append(bonus)
            else:
                report.downgraded.append(f"{term_option.term_months}개월:{bonus.label}")
                merged_bonuses.append(_downgrade_bonus_to_other(bonus))

        others = [
            next((o for o in run.rate_options if o.term_months == term_option.term_months), None)
            for run in other_runs
        ]
        merged_rate_options.append(
            term_option.model_copy(update={"bonuses": merged_bonuses, **_merge_group_fields(term_option, others, report)})
        )

    # --- 가입자격 (eligibility) -----------------------------------------------
    other_eligibility_indexes = [
        {_normalize(e.evidence_quote): e for e in run.eligibility} for run in other_runs
    ]
    merged_eligibility: list[LlmEligibility] = []
    for e in baseline.eligibility:
        if _already_other(e.codes):
            merged_eligibility.append(e)
            continue

        quote_key = _normalize(e.evidence_quote)
        baseline_fp = _eligibility_fingerprint(e)
        agrees_everywhere = all(
            (match := other_by_quote.get(quote_key)) is not None
            and _eligibility_fingerprint(match) == baseline_fp
            for other_by_quote in other_eligibility_indexes
        )
        if agrees_everywhere:
            merged_eligibility.append(e)
        else:
            report.downgraded_eligibility.append(e.note or e.evidence_quote[:30])
            merged_eligibility.append(_downgrade_eligibility_to_other(e))

    merged = baseline.model_copy(
        update={"rate_options": merged_rate_options, "eligibility": merged_eligibility}
    )
    return merged, report
