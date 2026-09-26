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
그 quote를 아예 못 찾으면 그 항목은 codes=[other]로 강등한다.

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

        merged_rate_options.append(
            # cap_bps·exclusive_pairs 같은 term 단위 다른 필드는 baseline 값을 그대로
            # 이어받는다 (bonuses만 병합 대상이다).
            term_option.model_copy(update={"bonuses": merged_bonuses})
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
