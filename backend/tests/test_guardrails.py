"""입력·답변·추출 단계의 코드 가드레일을 확인한다 (LLM 호출 없음)."""

import json

import pytest

import app.graph.nodes as graph_nodes
from app.agent import nodes
from app.db.store import connect, log_extraction_result
from app.graph.workflow import build_extraction_graph
from app.schemas.agent import (
    AgentProductResult,
    AnalyzedFact,
    AnalyzedUserInput,
    BonusEvidenceResult,
    DraftAnswer,
    DraftProductClaim,
)
from app.schemas.extraction import LlmBonus, LlmExtraction, LlmRateOptionBonuses, LlmRequirementRef
from app.schemas.graph import (
    Bonus,
    BonusGroup,
    Evidence,
    ProductCategory,
    RateOption,
    RequirementCombinator,
    RequirementRef,
    ReserveType,
)
from app.schemas.requirements import RequirementCode as Code
from app.schemas.user import UserProfile
from app.services.consistency import merge_self_consistency
from app.services.korean_numbers import find_won_amounts, parse_months, parse_won
from app.services.reachability import check_reachability
from app.services.verification import rate_matches_quote


# --- 한국어 금액·기간 해석 ----------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("30만 원", 300_000), ("30만씩", 300_000), ("300,000원", 300_000), ("1.5만 원", 15_000),
    ("삼십만 원", 300_000), ("월 이십만원", 200_000), ("1천만원", 10_000_000), ("5만 9,389원", 59_389),
    ("급여이체는 가능", None), ("사원 할인", None),
])
def test_parse_won(text, expected):
    assert parse_won(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("1년", 12), ("2년 6개월", 30), ("1년 반", 18), ("반년", 6), ("18개월", 18), ("12달", 12),
    ("삼 년", 36), ("이달", None), ("1년(12개월)", 12),
])
def test_parse_months(text, expected):
    assert parse_months(text) == expected


# --- 입력 검증: 실패 대신 다시 묻거나 미확인으로 낮춘다 ----------------------------

def _analysis(**overrides) -> AnalyzedUserInput:
    data = {"monthly_deposit_won": 300_000, "monthly_deposit_quote": "30만씩", "term_months": 12, "term_quote": "1년", "facts": []}
    return AnalyzedUserInput(**{**data, **overrides})


def test_unit_less_amount_is_accepted():
    result = nodes.validate_input({"message": "30만씩 1년 넣을래", "analysis": _analysis()})
    assert result["profile"].monthly_deposit_won == 300_000


def test_mismatched_amount_asks_again_instead_of_failing():
    result = nodes.validate_input({"message": "30만씩 1년 넣을래", "analysis": _analysis(monthly_deposit_won=3_000_000)})
    assert result["profile"] is None and result["errors"] == []
    assert "월 30만 원" in result["questions"][0]
    assert nodes.route_after_validation(result) == "needs_input"


def test_ungrounded_fact_is_dropped_not_fatal():
    fact = AnalyzedFact(code=Code.SALARY_TRANSFER, satisfied=True, evidence_quote="급여이체 가능")
    result = nodes.validate_input({"message": "30만씩 1년 넣을래", "analysis": _analysis(facts=[fact])})
    assert result["profile"].facts == {}
    assert "salary_transfer" in result["input_warnings"][0]


# --- 답변 문장 검증 -----------------------------------------------------------

def _product(key: str, name: str) -> AgentProductResult:
    return AgentProductResult(
        product_key=key, institution_name="테스트은행", product_name=name, reserve_type="free", term_months=12,
        base_rate_bps=300, achieved_rate_bps=350, max_rate_bps=370, after_tax_interest_won=57_800,
        maturity_amount_won=3_657_800, potential_rate_bps=370, potential_after_tax_interest_won=61_100,
        bonuses=[BonusEvidenceResult(bonus_id="b1", label="급여이체", rate_bps=50, satisfied=True,
                                     evidence_quote="급여이체 실적 충족 시 연 0.5%p")],
    )


def _verify(answer: str, products: list[AgentProductResult]) -> list[str]:
    claim = DraftProductClaim(product_key=products[0].product_key, achieved_rate_bps=350, after_tax_interest_won=57_800)
    state = {"draft": DraftAnswer(answer=answer, product_claims=[claim]), "product_results": products,
             "profile": UserProfile(monthly_deposit_won=300_000, term_months=12)}
    return nodes.verify_answer(state)["errors"]


def test_answer_text_with_calculated_numbers_passes():
    answer = "예시적금은 월 30만 원 기준 예상 적용금리 연 3.50%, 세후 이자 57,800원이고 급여이체 0.50%p가 반영됐어요. 실제 금리는 가입 시 확인하세요."
    assert _verify(answer, [_product("p1", "예시적금")]) == []


def test_max_rate_written_as_applied_rate_is_caught_only_if_not_calculated():
    # 공시 최고금리 3.70%는 계산 결과에 있는 값이라 허용, 3.80%는 어디에도 없는 값이라 거부
    assert _verify("예시적금 최고 연 3.70%", [_product("p1", "예시적금")]) == []
    errors = _verify("예시적금 예상 연 3.80%", [_product("p1", "예시적금")])
    assert any("3.80%" in e for e in errors)


def test_rounded_or_computed_amount_is_caught():
    errors = _verify("예시적금 세후 이자는 약 6만 원입니다.", [_product("p1", "예시적금")])
    assert any("60,000원" in e for e in errors)


def test_product_named_in_text_without_claim_is_caught():
    errors = _verify("예시적금 연 3.50%, 다른적금도 좋아요.", [_product("p1", "예시적금"), _product("p2", "다른적금")])
    assert any("다른적금" in e for e in errors)


# --- 오프라인 추출 검증 -------------------------------------------------------

def test_rate_must_match_number_in_quote():
    assert rate_matches_quote(50, "급여이체 시 연 0.5%p")
    assert not rate_matches_quote(70, "급여이체 시 연 0.5%p")
    assert rate_matches_quote(0, "재직기간에 따라 최고 연 1.2%p")  # 폭 미상은 판정하지 않음
    assert rate_matches_quote(40, "아래 표의 우대금리 적용")  # 인용문에 숫자가 없으면 판정하지 않음


def test_other_bonus_with_known_rate_explains_max_but_never_applies():
    bonuses = [
        Bonus(id="b1", label="급여이체", rate_bps=30, combinator=RequirementCombinator.SOLE,
              requirements=[RequirementRef(codes=[Code.SALARY_TRANSFER])], evidence=Evidence(quote="급여이체 0.3%p", source_field="spcl_cnd")),
        Bonus(id="b2", label="주거래 실적", rate_bps=20, combinator=RequirementCombinator.SOLE,
              requirements=[RequirementRef(codes=[Code.OTHER])], evidence=Evidence(quote="주거래 실적 0.2%p", source_field="spcl_cnd")),
    ]
    option = RateOption(term_months=12, reserve_type=ReserveType.FREE, base_rate_bps=200, max_rate_bps=250,
                        bonus_group=BonusGroup(id="g", bonuses=bonuses))
    result = check_reachability(option)
    assert result.reachable and result.excluded_other == ("b2",)

    from app.services.matching import evaluate_rate_option
    profile = UserProfile(monthly_deposit_won=100_000, term_months=12, facts={Code.SALARY_TRANSFER: {"satisfied": True}})
    match = evaluate_rate_option(option, profile)
    assert match.achieved_rate_bps == 230 and match.potential_rate_bps == 230


def _run(cap: int | None, pairs: list[list[str]]) -> LlmExtraction:
    bonus = lambda i, q: LlmBonus(id=i, label=i, rate_bps=30, combinator="sole",
                                  requirements=[LlmRequirementRef(codes=[Code.SALARY_TRANSFER if i == "b1" else Code.UTILITY_AUTOPAY])], evidence_quote=q)
    return LlmExtraction(status="extracted", eligibility=[], rate_options=[LlmRateOptionBonuses(
        term_months=12, bonuses=[bonus("b1", "급여 0.3%p"), bonus("b2", "공과금 0.3%p")], group_cap_bps=cap, exclusive_bonus_id_pairs=pairs)])


def test_conflicting_cap_and_pairs_take_the_lower_rate_side():
    merged, report = merge_self_consistency([_run(None, []), _run(40, []), _run(50, [["b1", "b2"]])])
    option = merged.rate_options[0]
    assert option.group_cap_bps == 40
    assert option.exclusive_bonus_id_pairs == [["b1", "b2"]]
    assert len(report.group_conflicts) == 2 and all(n.startswith("12개월:") for n in report.notes())


def test_rate_mismatch_is_retried_then_excluded(monkeypatch):
    spcl = "급여이체 실적 충족 시 연 1.0%p"
    wrong = LlmExtraction(status="extracted", eligibility=[], rate_options=[LlmRateOptionBonuses(term_months=12, bonuses=[
        LlmBonus(id="b1", label="급여", rate_bps=100 + 10, combinator="sole", requirements=[LlmRequirementRef(codes=[Code.SALARY_TRANSFER])], evidence_quote=spcl)])])

    class Extractor:
        calls = 0
        def extract_n(self, n, **_):
            self.calls += 1
            return [wrong] * n

    class Reviewer:
        def review(self, **_):
            raise AssertionError("검증 실패 term은 검토하지 않는다")

    extractor = Extractor()
    monkeypatch.setattr(graph_nodes, "get_extractor", lambda: extractor)
    monkeypatch.setattr(graph_nodes, "get_reviewer", lambda: Reviewer())
    result = build_extraction_graph().invoke({
        "institution_name": "테스트은행", "product_name": "테스트", "category": ProductCategory.SAVINGS, "disclosed_month": "202609",
        "source_hash": "h", "join_way": None, "max_limit_won": None, "join_member": "개인", "spcl_cnd": spcl,
        "known_rate_options": [{"term_months": 12, "base_rate_bps": 200, "max_rate_bps": 300}], "reserve_type": ReserveType.FREE,
    })
    assert extractor.calls == 2
    assert "우대 금리와 원문 숫자 불일치" in result["excluded_terms"][12]


def test_extraction_log_keeps_reviewer_and_consistency_records(tmp_path):
    conn = connect(tmp_path / "log.db")
    log_extraction_result(conn, "은행", "상품", 12, "accepted", None, 0, True, ["12개월:급여 강등"])
    row = conn.execute("SELECT reviewer_unavailable, consistency_notes FROM extraction_log").fetchone()
    assert row[0] == 1 and json.loads(row[1]) == ["12개월:급여 강등"]
    conn.close()
