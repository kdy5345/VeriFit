from app.schemas.extraction import (
    LlmBonus,
    LlmEligibility,
    LlmExtraction,
    LlmRateOptionBonuses,
    LlmRequirementRef,
)
from app.schemas.requirements import RequirementCode
from app.services.consistency import merge_self_consistency


def _extraction(*, cross_selling_codes: list[RequirementCode]) -> LlmExtraction:
    """b1(급여이체)은 항상 동일, b2(교차거래)만 run마다 codes를 다르게 줄 수 있게."""
    return LlmExtraction(
        status="extracted",
        eligibility=[],
        rate_options=[
            LlmRateOptionBonuses(
                term_months=12,
                bonuses=[
                    LlmBonus(
                        id="b1",
                        label="급여이체 실적",
                        rate_bps=70,
                        combinator="sole",
                        requirements=[LlmRequirementRef(codes=[RequirementCode.SALARY_TRANSFER])],
                        evidence_quote="가.급여 이체:연 0.7%p",
                    ),
                    LlmBonus(
                        id="b2",
                        label="교차거래 우대",
                        rate_bps=30,
                        combinator="sole",
                        requirements=[LlmRequirementRef(codes=cross_selling_codes)],
                        evidence_quote="② 교차거래 우대이율: 연 0.3%p",
                    ),
                ],
            )
        ],
    )


def test_stable_bonus_survives_and_unstable_one_is_downgraded() -> None:
    runs = [
        _extraction(cross_selling_codes=[RequirementCode.LINKED_PRODUCT_HELD]),
        _extraction(cross_selling_codes=[RequirementCode.OTHER]),
        _extraction(cross_selling_codes=[RequirementCode.OTHER]),
    ]
    merged, report = merge_self_consistency(runs)
    bonuses = {b.id: b for b in merged.rate_options[0].bonuses}

    # 급여이체는 3번 다 동일 → 그대로 유지
    assert bonuses["b1"].requirements[0].codes == [RequirementCode.SALARY_TRANSFER]
    assert bonuses["b1"].rate_bps == 70

    # 교차거래는 갈렸으므로 → other로 강등, rate_bps는 0으로
    assert bonuses["b2"].requirements[0].codes == [RequirementCode.OTHER]
    assert bonuses["b2"].rate_bps == 0
    assert "12개월:교차거래 우대" in report.downgraded
    assert report.total_bonuses == 2


def test_fully_agreeing_runs_downgrade_nothing() -> None:
    runs = [_extraction(cross_selling_codes=[RequirementCode.LINKED_PRODUCT_HELD]) for _ in range(3)]
    merged, report = merge_self_consistency(runs)
    assert report.downgraded == []
    bonuses = {b.id: b for b in merged.rate_options[0].bonuses}
    assert bonuses["b2"].requirements[0].codes == [RequirementCode.LINKED_PRODUCT_HELD]


def test_already_other_is_not_re_flagged_as_downgraded() -> None:
    # baseline이 이미 other면, 다른 run과 안 맞아도 "강등 로그"에는 안 남긴다
    # (더 낮출 곳이 없으므로 잡음일 뿐이다).
    runs = [
        _extraction(cross_selling_codes=[RequirementCode.OTHER]),
        _extraction(cross_selling_codes=[RequirementCode.LINKED_PRODUCT_HELD]),
    ]
    merged, report = merge_self_consistency(runs)
    assert report.downgraded == []
    bonuses = {b.id: b for b in merged.rate_options[0].bonuses}
    assert bonuses["b2"].requirements[0].codes == [RequirementCode.OTHER]


def test_missing_quote_in_other_run_counts_as_disagreement() -> None:
    stable = _extraction(cross_selling_codes=[RequirementCode.LINKED_PRODUCT_HELD])
    # 두 번째 run은 b2를 아예 추출하지 못한 상황을 흉내낸다 (bonuses에서 제거).
    incomplete = stable.model_copy(deep=True)
    incomplete.rate_options[0].bonuses = incomplete.rate_options[0].bonuses[:1]

    merged, report = merge_self_consistency([stable, incomplete])
    bonuses = {b.id: b for b in merged.rate_options[0].bonuses}
    assert bonuses["b2"].requirements[0].codes == [RequirementCode.OTHER]
    assert report.downgraded == ["12개월:교차거래 우대"]


def test_numeric_only_disagreement_is_caught() -> None:
    """codes·combinator는 같지만 rate_bps나 min_amount_won이 run마다 다르면 강등돼야 한다
    (예전 버전은 codes만 봐서 이걸 놓쳤다)."""

    def extraction(rate_bps: int, min_amount_won: int) -> LlmExtraction:
        return LlmExtraction(
            status="extracted",
            eligibility=[],
            rate_options=[
                LlmRateOptionBonuses(
                    term_months=12,
                    bonuses=[
                        LlmBonus(
                            id="b1",
                            label="급여이체",
                            rate_bps=rate_bps,
                            combinator="sole",
                            requirements=[
                                LlmRequirementRef(
                                    codes=[RequirementCode.SALARY_TRANSFER],
                                    min_amount_won=min_amount_won,
                                    min_months=6,
                                )
                            ],
                            evidence_quote="급여이체:연 0.7%p",
                        )
                    ],
                )
            ],
        )

    runs = [extraction(70, 500_000), extraction(50, 1_000_000), extraction(70, 500_000)]
    merged, report = merge_self_consistency(runs)
    bonus = merged.rate_options[0].bonuses[0]
    assert bonus.requirements[0].codes == [RequirementCode.OTHER]
    assert bonus.rate_bps == 0
    assert "12개월:급여이체" in report.downgraded


def test_term_entirely_missing_in_one_run_counts_as_disagreement() -> None:
    """다른 run에 그 term_months 자체가 통째로 없으면, baseline의 모든 bonus가
    강등돼야 한다 (dict comprehension이 빈 term을 조용히 건너뛰던 버그 재현)."""
    with_term = LlmExtraction(
        status="extracted",
        eligibility=[],
        rate_options=[
            LlmRateOptionBonuses(
                term_months=12,
                bonuses=[
                    LlmBonus(
                        id="b1", label="급여이체", rate_bps=70, combinator="sole",
                        requirements=[LlmRequirementRef(codes=[RequirementCode.SALARY_TRANSFER])],
                        evidence_quote="급여이체:연 0.7%p",
                    )
                ],
            )
        ],
    )
    without_term = LlmExtraction(status="no_bonus", eligibility=[], rate_options=[])

    merged, report = merge_self_consistency([with_term, without_term])
    bonus = merged.rate_options[0].bonuses[0]
    assert bonus.requirements[0].codes == [RequirementCode.OTHER]
    assert "12개월:급여이체" in report.downgraded


def test_eligibility_disagreement_is_downgraded() -> None:
    stable = LlmExtraction(
        status="extracted",
        eligibility=[
            LlmEligibility(
                codes=[RequirementCode.AGE_RANGE], note="만 19~34세", evidence_quote="만 19세 이상 34세 이하"
            )
        ],
        rate_options=[],
    )
    disagreeing = LlmExtraction(
        status="extracted",
        eligibility=[
            LlmEligibility(
                codes=[RequirementCode.OTHER], note="만 19~34세", evidence_quote="만 19세 이상 34세 이하"
            )
        ],
        rate_options=[],
    )
    merged, report = merge_self_consistency([stable, disagreeing])
    assert merged.eligibility[0].codes == [RequirementCode.OTHER]
    assert report.downgraded_eligibility
