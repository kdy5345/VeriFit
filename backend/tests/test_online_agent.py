from fastapi.testclient import TestClient

from app.agent import nodes
from app.api.routes.evaluate import get_db
from app.db.store import connect, save_product
from app.main import app
from app.schemas.agent import (
    AnalyzedFact,
    AnalyzedUserInput,
    AnswerReview,
    DraftAnswer,
    DraftProductClaim,
)
from app.schemas.graph import (
    Bonus,
    BonusGroup,
    Evidence,
    Product,
    ProductCategory,
    RateOption,
    RequirementCombinator,
    RequirementRef,
    ReserveType,
)
from app.schemas.requirements import RequirementCode
from app.services.online_agent_llm import OnlineAgentLlmError


def _seed_db(db_path) -> None:
    conn = connect(db_path)
    bonus = Bonus(
        id="b1",
        label="급여이체 실적",
        rate_bps=70,
        combinator=RequirementCombinator.SOLE,
        requirements=[RequirementRef(codes=[RequirementCode.SALARY_TRANSFER])],
        evidence=Evidence(quote="급여이체 실적 충족 시 연 0.7%p", source_field="spcl_cnd"),
    )
    save_product(
        conn,
        Product(
            institution_name="우리은행",
            name="테스트적금",
            category=ProductCategory.SAVINGS,
            disclosed_month="202609",
            source_hash="hash",
            rate_options=[
                RateOption(
                    term_months=12,
                    reserve_type=ReserveType.FREE,
                    base_rate_bps=245,
                    max_rate_bps=315,
                    bonus_group=BonusGroup(id="g1", bonuses=[bonus]),
                )
            ],
        ),
    )
    conn.close()


def _client(db_path) -> TestClient:
    def override_get_db():
        conn = connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


class SuccessfulAgent:
    def analyze(self, message):
        return AnalyzedUserInput(
            monthly_deposit_won=300_000,
            monthly_deposit_quote="30만 원",
            term_months=12,
            term_quote="1년",
            facts=[
                AnalyzedFact(
                    code=RequirementCode.SALARY_TRANSFER,
                    satisfied=True,
                    evidence_quote="급여이체는 가능",
                )
            ],
        )

    def write(self, message, analysis, products, feedback=None):
        top = products[0]
        return DraftAnswer(
            answer=(
                f"{top['product_name']}의 예상 적용금리는 "
                f"{top['achieved_rate_bps'] / 100:.2f}%입니다."
            ),
            product_claims=[
                DraftProductClaim(
                    product_key=top["product_key"],
                    achieved_rate_bps=top["achieved_rate_bps"],
                    after_tax_interest_won=top["after_tax_interest_won"],
                    evidence_quotes=[top["bonuses"][0]["evidence_quote"]],
                )
            ],
        )

    def review(self, message, analysis, products, draft):
        return AnswerReview(approved=True)


def test_ask_runs_analyze_calculate_write_verify_review(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "agent.db"
    _seed_db(db_path)
    monkeypatch.setattr(nodes, "get_online_agent", lambda: SuccessfulAgent())
    client = _client(db_path)

    response = client.post(
        "/api/v1/ask",
        json={"message": "매달 30만 원씩 1년 넣고 급여이체는 가능해."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["used_fallback"] is False
    assert body["extracted_profile"]["monthly_deposit_won"] == 300_000
    assert body["products"][0]["achieved_rate_bps"] == 315
    assert body["products"][0]["bonuses"][0]["evidence_quote"] == "급여이체 실적 충족 시 연 0.7%p"
    assert "3.15%" in body["answer"]
    app.dependency_overrides.clear()


class MissingInputAgent(SuccessfulAgent):
    def analyze(self, message):
        return AnalyzedUserInput(
            monthly_deposit_won=300_000,
            monthly_deposit_quote="30만 원",
            term_months=None,
        )

    def write(self, *args, **kwargs):
        raise AssertionError("필수 입력이 없으면 Writer를 호출하면 안 됩니다.")


def test_ask_returns_question_when_term_is_missing(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "agent.db"
    _seed_db(db_path)
    monkeypatch.setattr(nodes, "get_online_agent", lambda: MissingInputAgent())
    client = _client(db_path)

    body = client.post("/api/v1/ask", json={"message": "매달 30만 원 넣을래."}).json()

    assert body["status"] == "needs_input"
    assert body["questions"] == ["몇 개월 동안 가입할 예정인가요?"]
    assert body["products"] == []
    app.dependency_overrides.clear()


class WrongThenCorrectWriter(SuccessfulAgent):
    def __init__(self):
        self.write_count = 0

    def write(self, message, analysis, products, feedback=None):
        self.write_count += 1
        result = super().write(message, analysis, products, feedback)
        if self.write_count == 1:
            result.product_claims[0].achieved_rate_bps += 100
        return result


def test_answer_number_mismatch_is_retried_once(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "agent.db"
    _seed_db(db_path)
    fake = WrongThenCorrectWriter()
    monkeypatch.setattr(nodes, "get_online_agent", lambda: fake)
    client = _client(db_path)

    body = client.post(
        "/api/v1/ask",
        json={"message": "매달 30만 원씩 1년 넣고 급여이체는 가능해."},
    ).json()

    assert body["status"] == "completed"
    assert body["retry_count"] == 1
    assert body["used_fallback"] is False
    assert fake.write_count == 2
    app.dependency_overrides.clear()


class UnavailableReviewer(SuccessfulAgent):
    def review(self, message, analysis, products, draft):
        raise OnlineAgentLlmError("review unavailable")


def test_reviewer_failure_uses_deterministic_fallback(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "agent.db"
    _seed_db(db_path)
    monkeypatch.setattr(nodes, "get_online_agent", lambda: UnavailableReviewer())
    client = _client(db_path)

    body = client.post(
        "/api/v1/ask",
        json={"message": "매달 30만 원씩 1년 넣고 급여이체는 가능해."},
    ).json()

    assert body["status"] == "completed"
    assert body["used_fallback"] is True
    assert body["retry_count"] == 1
    assert "검증된 계산 결과" in body["answer"]
    app.dependency_overrides.clear()


class MultiTurnAgent(SuccessfulAgent):
    def __init__(self):
        self.analyzed_messages = []

    def analyze(self, message):
        self.analyzed_messages.append(message)
        if "30만 원" not in message:
            return AnalyzedUserInput(
                monthly_deposit_won=None,
                term_months=12,
                term_quote="1년",
                facts=[
                    AnalyzedFact(
                        code=RequirementCode.SALARY_TRANSFER,
                        satisfied=True,
                        evidence_quote="급여이체는 가능",
                    )
                ],
            )
        return super().analyze(message)


def test_checkpointer_combines_follow_up_message_in_same_thread(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "agent.db"
    _seed_db(db_path)
    fake = MultiTurnAgent()
    monkeypatch.setattr(nodes, "get_online_agent", lambda: fake)
    client = _client(db_path)

    first = client.post(
        "/api/v1/ask",
        json={"message": "1년 동안 넣고 급여이체는 가능해."},
    ).json()
    assert first["status"] == "needs_input"
    assert first["questions"] == ["매월 얼마를 납입할 예정인가요?"]

    second = client.post(
        "/api/v1/ask",
        json={"message": "매달 30만 원이야.", "thread_id": first["thread_id"]},
    ).json()

    assert second["status"] == "completed"
    assert second["thread_id"] == first["thread_id"]
    assert "1년 동안 넣고" in fake.analyzed_messages[-1]
    assert "매달 30만 원이야" in fake.analyzed_messages[-1]
    app.dependency_overrides.clear()


def test_frontend_origin_is_allowed_by_cors() -> None:
    client = TestClient(app)
    response = client.options(
        "/api/v1/ask",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
