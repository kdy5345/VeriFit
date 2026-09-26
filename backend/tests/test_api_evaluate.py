from fastapi.testclient import TestClient

from app.api.routes.evaluate import get_db
from app.db.store import connect, save_product
from app.main import app
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


def _seed_db(db_path) -> None:
    conn = connect(db_path)
    bonus = Bonus(
        id="b1", label="급여이체 실적", rate_bps=70, combinator=RequirementCombinator.SOLE,
        requirements=[RequirementRef(codes=[RequirementCode.SALARY_TRANSFER], param={"min_months": 6})],
        evidence=Evidence(quote="가.급여이체:연 0.7%p", source_field="spcl_cnd"),
    )
    option = RateOption(
        term_months=12, reserve_type=ReserveType.FREE, base_rate_bps=245, max_rate_bps=315,
        bonus_group=BonusGroup(id="g12", cap_bps=None, bonuses=[bonus], exclusive_pairs=[]),
    )
    save_product(
        conn,
        Product(
            institution_name="우리은행", name="테스트적금", category=ProductCategory.SAVINGS,
            disclosed_month="202609", source_hash="h", rate_options=[option],
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


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_evaluate_returns_achieved_rate_and_interest(tmp_path) -> None:
    db_path = tmp_path / "test.db"
    _seed_db(db_path)
    client = _client(db_path)

    response = client.post(
        "/api/v1/evaluate",
        json={
            "monthly_deposit_won": 300_000,
            "term_months": 12,
            "facts": {"salary_transfer": {"satisfied": True, "months": 12}},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) == 1
    result = body["results"][0]
    assert result["institution_name"] == "우리은행"
    assert result["achieved_rate_bps"] == 315  # 245 + 70
    assert result["pre_tax_interest_won"] > 0
    assert result["after_tax_interest_won"] < result["pre_tax_interest_won"]
    assert result["satisfied_bonus_labels"] == ["급여이체 실적"]
    assert body["next_question"] is None  # 유일한 조건을 이미 만족시킴
    assert "이자소득세" in body["disclaimer"]

    app.dependency_overrides.clear()


def test_evaluate_without_facts_suggests_next_question(tmp_path) -> None:
    db_path = tmp_path / "test.db"
    _seed_db(db_path)
    client = _client(db_path)

    response = client.post(
        "/api/v1/evaluate",
        json={"monthly_deposit_won": 300_000, "term_months": 12, "facts": {}},
    )
    body = response.json()
    assert body["results"][0]["achieved_rate_bps"] == 245  # 우대 미충족, 기본금리만
    assert body["next_question"]["code"] == "salary_transfer"

    app.dependency_overrides.clear()


def test_evaluate_filters_by_term_months(tmp_path) -> None:
    db_path = tmp_path / "test.db"
    _seed_db(db_path)
    client = _client(db_path)

    response = client.post(
        "/api/v1/evaluate",
        json={"monthly_deposit_won": 300_000, "term_months": 24, "facts": {}},
    )
    assert response.json()["results"] == []  # 저장된 상품은 12개월뿐

    app.dependency_overrides.clear()
