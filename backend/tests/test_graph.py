"""재시도 루프와 review 노드가 실제로 도는지 확인한다. 진짜 API를 부르지 않고,
get_extractor/get_reviewer를 가짜로 바꿔치기해서 그래프의 라우팅만 검증한다.
"""

import app.graph.nodes as nodes_module
from app.graph.workflow import build_extraction_graph
from app.schemas.extraction import (
    LlmBonus,
    LlmEligibility,
    LlmExtraction,
    LlmRateOptionBonuses,
    LlmRequirementRef,
)
from app.schemas.graph import ProductCategory, ReserveType
from app.schemas.requirements import RequirementCode
from app.schemas.review import ReviewFinding, ReviewResult
from app.services.extractor import ExtractionError
from app.services.reviewer import ReviewError


class FakeExtractor:
    """extract_n을 호출할 때마다 미리 정해둔 응답을 순서대로 꺼내 쓴다.
    응답 대신 Exception 인스턴스를 넣어두면 그걸 raise한다 (API 장애 흉내)."""

    def __init__(self, responses: list[LlmExtraction | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[list[str] | None] = []  # 매 호출의 feedback 기록

    def extract_n(self, n: int, feedback: list[str] | None = None, **_kwargs) -> list[LlmExtraction]:
        self.calls.append(feedback)
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return [response] * n  # 자가 반복 결과를 전부 동일하게 줘서, 이 테스트는 재시도
        # 라우팅만 보고 self-consistency 강등 로직과는 분리한다 (그건 test_consistency.py).


class FakeReviewer:
    """review()를 호출할 때마다 미리 정해둔 응답을 순서대로 꺼내 쓴다.
    응답 대신 Exception 인스턴스를 넣어두면 그걸 raise한다."""

    def __init__(self, responses: list[ReviewResult | Exception] | None = None) -> None:
        self._responses = list(responses) if responses is not None else []
        self.call_count = 0

    def review(self, **_kwargs) -> ReviewResult:
        self.call_count += 1
        if not self._responses:
            return ReviewResult(findings=[])
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _bonus(bonus_id: str, rate_bps: int, code: RequirementCode, quote: str) -> LlmBonus:
    return LlmBonus(
        id=bonus_id,
        label=bonus_id,
        rate_bps=rate_bps,
        combinator="sole",
        requirements=[LlmRequirementRef(codes=[code])],
        evidence_quote=quote,
    )


def _base_input(spcl_cnd: str) -> dict:
    return {
        "institution_name": "테스트은행",
        "product_name": "테스트상품",
        "category": ProductCategory.SAVINGS,
        "disclosed_month": "202609",
        "source_hash": "test-hash",
        "join_way": None,
        "max_limit_won": None,
        "join_member": "실명의 개인",
        "spcl_cnd": spcl_cnd,
        "known_rate_options": [{"term_months": 12, "base_rate_bps": 200, "max_rate_bps": 300}],
        "reserve_type": ReserveType.FREE,
    }


def _reachable_extraction(spcl_cnd_quote: str) -> LlmExtraction:
    return LlmExtraction(
        status="extracted",
        eligibility=[],
        rate_options=[
            LlmRateOptionBonuses(
                term_months=12,
                bonuses=[_bonus("b1", 100, RequirementCode.SALARY_TRANSFER, spcl_cnd_quote)],
            )
        ],
    )


# --- 코드 검증(근거 대조 · 도달가능성) 라우팅 ------------------------------------


def test_no_retry_when_first_attempt_already_reachable(monkeypatch) -> None:
    spcl_cnd = "가. A: 1.0%p"
    fake_extractor = FakeExtractor([_reachable_extraction(spcl_cnd)])
    fake_reviewer = FakeReviewer()  # 지적 없음
    monkeypatch.setattr(nodes_module, "get_extractor", lambda: fake_extractor)
    monkeypatch.setattr(nodes_module, "get_reviewer", lambda: fake_reviewer)

    result = build_extraction_graph().invoke(_base_input(spcl_cnd))

    assert result["accepted_terms"] == [12]
    assert result["excluded_terms"] == {}
    assert len(fake_extractor.calls) == 1
    assert fake_extractor.calls[0] is None
    assert fake_reviewer.call_count == 1  # 코드 검증 통과한 term은 review까지 받는다


def test_retry_succeeds_when_second_attempt_finds_missing_bonus(monkeypatch) -> None:
    """1차 시도는 항목 하나를 놓쳐 gap 100bp 중 50bp만 설명 → 재시도에서 마저 찾음."""
    spcl_cnd = "가. A: 0.5%p\n나. B: 0.5%p"
    incomplete = LlmExtraction(
        status="extracted",
        eligibility=[],
        rate_options=[
            LlmRateOptionBonuses(
                term_months=12,
                bonuses=[_bonus("b1", 50, RequirementCode.SALARY_TRANSFER, "가. A: 0.5%p")],
            )
        ],
    )
    complete = LlmExtraction(
        status="extracted",
        eligibility=[],
        rate_options=[
            LlmRateOptionBonuses(
                term_months=12,
                bonuses=[
                    _bonus("b1", 50, RequirementCode.SALARY_TRANSFER, "가. A: 0.5%p"),
                    _bonus("b2", 50, RequirementCode.UTILITY_AUTOPAY, "나. B: 0.5%p"),
                ],
            )
        ],
    )
    fake_extractor = FakeExtractor([incomplete, complete])
    fake_reviewer = FakeReviewer()
    monkeypatch.setattr(nodes_module, "get_extractor", lambda: fake_extractor)
    monkeypatch.setattr(nodes_module, "get_reviewer", lambda: fake_reviewer)

    result = build_extraction_graph().invoke(_base_input(spcl_cnd))

    assert result["accepted_terms"] == [12]
    assert result["excluded_terms"] == {}
    assert len(fake_extractor.calls) == 2
    assert fake_extractor.calls[1] is not None and "100bp" in fake_extractor.calls[1][0]
    assert fake_reviewer.call_count == 1  # 1차는 코드검증에서 걸려 review까지 못 감


def test_gives_up_after_one_retry_and_excludes_that_term(monkeypatch) -> None:
    spcl_cnd = "가. A: 0.5%p"
    always_incomplete = LlmExtraction(
        status="extracted",
        eligibility=[],
        rate_options=[
            LlmRateOptionBonuses(
                term_months=12,
                bonuses=[_bonus("b1", 50, RequirementCode.SALARY_TRANSFER, "가. A: 0.5%p")],
            )
        ],
    )
    fake_extractor = FakeExtractor([always_incomplete, always_incomplete])
    fake_reviewer = FakeReviewer()
    monkeypatch.setattr(nodes_module, "get_extractor", lambda: fake_extractor)
    monkeypatch.setattr(nodes_module, "get_reviewer", lambda: fake_reviewer)

    result = build_extraction_graph().invoke(_base_input(spcl_cnd))

    assert result["accepted_terms"] == []
    assert "도달 불가" in result["excluded_terms"][12]
    assert len(fake_extractor.calls) == 2
    assert fake_reviewer.call_count == 0  # 코드검증을 한 번도 통과 못 해 review는 호출되지 않는다


def test_hallucinated_evidence_quote_triggers_retry_then_exclusion(monkeypatch) -> None:
    spcl_cnd = "가. A: 1.0%p"
    hallucinated = LlmExtraction(
        status="extracted",
        eligibility=[],
        rate_options=[
            LlmRateOptionBonuses(
                term_months=12,
                bonuses=[_bonus("b1", 100, RequirementCode.SALARY_TRANSFER, "원문에 없는 문장입니다")],
            )
        ],
    )
    fake_extractor = FakeExtractor([hallucinated, hallucinated])
    fake_reviewer = FakeReviewer()
    monkeypatch.setattr(nodes_module, "get_extractor", lambda: fake_extractor)
    monkeypatch.setattr(nodes_module, "get_reviewer", lambda: fake_reviewer)

    result = build_extraction_graph().invoke(_base_input(spcl_cnd))

    assert result["accepted_terms"] == []
    assert "근거 인용 실패" in result["excluded_terms"][12]
    assert fake_reviewer.call_count == 0


# --- Reviewer 지적 라우팅 --------------------------------------------------------


def test_review_finding_triggers_retry_and_second_pass_clears_it(monkeypatch) -> None:
    """코드 검증은 1차부터 통과하지만, Reviewer가 지적 → 재시도 → 2차는 지적 없음."""
    spcl_cnd = "가. A: 1.0%p"
    fake_extractor = FakeExtractor([_reachable_extraction(spcl_cnd), _reachable_extraction(spcl_cnd)])
    fake_reviewer = FakeReviewer(
        [
            ReviewResult(
                findings=[
                    ReviewFinding(term_months=12, bonus_id="b1", description="분류가 의심됩니다", quote="가. A: 1.0%p")
                ]
            ),
            ReviewResult(findings=[]),
        ]
    )
    monkeypatch.setattr(nodes_module, "get_extractor", lambda: fake_extractor)
    monkeypatch.setattr(nodes_module, "get_reviewer", lambda: fake_reviewer)

    result = build_extraction_graph().invoke(_base_input(spcl_cnd))

    assert result["accepted_terms"] == [12]
    assert result["excluded_terms"] == {}
    assert len(fake_extractor.calls) == 2
    assert "[검토 지적] 분류가 의심됩니다" in fake_extractor.calls[1][0]
    assert fake_reviewer.call_count == 2


def test_review_finding_without_grounded_quote_is_discarded(monkeypatch) -> None:
    """Reviewer가 지적했지만 근거 quote가 원문에 없으면 그 지적 자체를 버리고 그냥 통과시킨다."""
    spcl_cnd = "가. A: 1.0%p"
    fake_extractor = FakeExtractor([_reachable_extraction(spcl_cnd)])
    fake_reviewer = FakeReviewer(
        [
            ReviewResult(
                findings=[
                    ReviewFinding(
                        term_months=12, bonus_id="b1", description="지어낸 지적",
                        quote="원문에 존재하지 않는 문장",
                    )
                ]
            )
        ]
    )
    monkeypatch.setattr(nodes_module, "get_extractor", lambda: fake_extractor)
    monkeypatch.setattr(nodes_module, "get_reviewer", lambda: fake_reviewer)

    result = build_extraction_graph().invoke(_base_input(spcl_cnd))

    assert result["accepted_terms"] == [12]
    assert result["excluded_terms"] == {}
    assert len(fake_extractor.calls) == 1  # 근거 없는 지적이라 재시도로 이어지지 않음
    assert fake_reviewer.call_count == 1


def test_persistent_review_finding_excludes_term_after_retry(monkeypatch) -> None:
    """코드 검증은 계속 통과하지만 Reviewer가 재시도 후에도 같은 지적을 반복 → 결국 제외."""
    spcl_cnd = "가. A: 1.0%p"
    fake_extractor = FakeExtractor([_reachable_extraction(spcl_cnd), _reachable_extraction(spcl_cnd)])
    persistent_finding = ReviewResult(
        findings=[
            ReviewFinding(term_months=12, bonus_id="b1", description="AND/OR 결합이 틀림", quote="가. A: 1.0%p")
        ]
    )
    fake_reviewer = FakeReviewer([persistent_finding, persistent_finding])
    monkeypatch.setattr(nodes_module, "get_extractor", lambda: fake_extractor)
    monkeypatch.setattr(nodes_module, "get_reviewer", lambda: fake_reviewer)

    result = build_extraction_graph().invoke(_base_input(spcl_cnd))

    assert result["accepted_terms"] == []
    assert "검토 지적: AND/OR 결합이 틀림" in result["excluded_terms"][12]
    assert fake_reviewer.call_count == 2
    assert len(fake_extractor.calls) == 2


# --- Extractor/Reviewer 호출 자체가 실패하는 경우 --------------------------------


def test_extractor_api_failure_is_retried_then_excluded(monkeypatch) -> None:
    spcl_cnd = "가. A: 1.0%p"
    fake_extractor = FakeExtractor([ExtractionError("Gemini API 오류(HTTP 503)"), ExtractionError("Gemini API 오류(HTTP 503)")])
    fake_reviewer = FakeReviewer()
    monkeypatch.setattr(nodes_module, "get_extractor", lambda: fake_extractor)
    monkeypatch.setattr(nodes_module, "get_reviewer", lambda: fake_reviewer)

    result = build_extraction_graph().invoke(_base_input(spcl_cnd))

    assert result["accepted_terms"] == []
    assert "Extractor 오류" in result["excluded_terms"][12]
    assert "503" in result["excluded_terms"][12]
    assert len(fake_extractor.calls) == 2  # 최초 1회 + 재시도 1회
    assert fake_reviewer.call_count == 0  # 코드검증까지 못 가서 review는 호출 안 됨


def test_extractor_api_failure_recovers_on_retry(monkeypatch) -> None:
    spcl_cnd = "가. A: 1.0%p"
    fake_extractor = FakeExtractor([ExtractionError("일시적 오류"), _reachable_extraction(spcl_cnd)])
    fake_reviewer = FakeReviewer()
    monkeypatch.setattr(nodes_module, "get_extractor", lambda: fake_extractor)
    monkeypatch.setattr(nodes_module, "get_reviewer", lambda: fake_reviewer)

    result = build_extraction_graph().invoke(_base_input(spcl_cnd))

    assert result["accepted_terms"] == [12]
    assert result["excluded_terms"] == {}
    assert len(fake_extractor.calls) == 2


def test_reviewer_api_failure_does_not_exclude_already_verified_term(monkeypatch) -> None:
    """Reviewer가 장애로 실패해도, 이미 코드 검증을 통과한 term을 억지로 제외하지 않는다.
    대신 reviewer_unavailable=True로 표시해 2차 안전장치가 꺼졌음을 남긴다."""
    spcl_cnd = "가. A: 1.0%p"
    fake_extractor = FakeExtractor([_reachable_extraction(spcl_cnd)])
    fake_reviewer = FakeReviewer([ReviewError("Gemini API에 연결하지 못했습니다.")])
    monkeypatch.setattr(nodes_module, "get_extractor", lambda: fake_extractor)
    monkeypatch.setattr(nodes_module, "get_reviewer", lambda: fake_reviewer)

    result = build_extraction_graph().invoke(_base_input(spcl_cnd))

    assert result["accepted_terms"] == [12]
    assert result["excluded_terms"] == {}
    assert result["reviewer_unavailable"] is True
    assert len(fake_extractor.calls) == 1  # Reviewer 장애가 재시도를 유발하지 않음


# --- product 조립 -----------------------------------------------------------


def test_finalize_builds_product_from_accepted_terms_and_eligibility(monkeypatch) -> None:
    spcl_cnd = "가. A: 1.0%p"
    join_member = "만 19세 이상 34세 이하의 실명의 개인"
    extraction = LlmExtraction(
        status="extracted",
        eligibility=[
            LlmEligibility(codes=[RequirementCode.AGE_RANGE], note="만 19~34세", evidence_quote=join_member)
        ],
        rate_options=[
            LlmRateOptionBonuses(
                term_months=12,
                bonuses=[_bonus("b1", 100, RequirementCode.SALARY_TRANSFER, "가. A: 1.0%p")],
            )
        ],
    )
    fake_extractor = FakeExtractor([extraction])
    fake_reviewer = FakeReviewer()
    monkeypatch.setattr(nodes_module, "get_extractor", lambda: fake_extractor)
    monkeypatch.setattr(nodes_module, "get_reviewer", lambda: fake_reviewer)

    payload = _base_input(spcl_cnd)
    payload["join_member"] = join_member
    result = build_extraction_graph().invoke(payload)

    assert result["accepted_terms"] == [12]
    product = result["product"]
    assert product is not None
    assert product.institution_name == "테스트은행"
    assert product.name == "테스트상품"
    assert len(product.rate_options) == 1
    assert product.rate_options[0].term_months == 12
    assert product.rate_options[0].bonus_group.bonuses[0].rate_bps == 100
    assert len(product.eligibility) == 1
    assert product.eligibility[0].codes == [RequirementCode.AGE_RANGE]
    assert product.eligibility[0].evidence.quote == join_member


def test_finalize_product_is_none_when_nothing_accepted(monkeypatch) -> None:
    spcl_cnd = "가. A: 0.5%p"
    always_incomplete = LlmExtraction(
        status="extracted",
        eligibility=[],
        rate_options=[
            LlmRateOptionBonuses(
                term_months=12,
                bonuses=[_bonus("b1", 50, RequirementCode.SALARY_TRANSFER, "가. A: 0.5%p")],
            )
        ],
    )
    fake_extractor = FakeExtractor([always_incomplete, always_incomplete])
    fake_reviewer = FakeReviewer()
    monkeypatch.setattr(nodes_module, "get_extractor", lambda: fake_extractor)
    monkeypatch.setattr(nodes_module, "get_reviewer", lambda: fake_reviewer)

    result = build_extraction_graph().invoke(_base_input(spcl_cnd))

    assert result["product"] is None
