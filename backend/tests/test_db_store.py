import json

import pytest

from app.db.store import connect, log_extraction_result, save_product
from app.schemas.graph import (
    Bonus,
    BonusGroup,
    EligibilityRef,
    Evidence,
    Product,
    ProductCategory,
    RateOption,
    RequirementCombinator,
    RequirementRef,
    ReserveType,
)
from app.schemas.requirements import RequirementCode


@pytest.fixture
def conn():
    connection = connect(":memory:")
    yield connection
    connection.close()


def _sample_product(*, rate_bps: int = 100, disclosed_month: str = "202609") -> Product:
    bonus = Bonus(
        id="b1",
        label="급여이체",
        rate_bps=rate_bps,
        combinator=RequirementCombinator.SOLE,
        requirements=[RequirementRef(codes=[RequirementCode.SALARY_TRANSFER], param={"min_months": 6})],
        evidence=Evidence(quote="가. A: 1.0%p", source_field="spcl_cnd"),
    )
    option = RateOption(
        term_months=12,
        reserve_type=ReserveType.FREE,
        base_rate_bps=200,
        max_rate_bps=300,
        bonus_group=BonusGroup(id="g12", cap_bps=None, bonuses=[bonus], exclusive_pairs=[]),
    )
    return Product(
        institution_name="테스트은행",
        name="테스트적금",
        category=ProductCategory.SAVINGS,
        disclosed_month=disclosed_month,
        source_hash="hash-1",
        join_way="영업점,인터넷뱅킹",
        max_limit_won=10_000_000,
        eligibility=[
            EligibilityRef(
                codes=[RequirementCode.AGE_RANGE],
                param={"note": "만 19~34세"},
                evidence=Evidence(quote="만 19세 이상", source_field="join_member"),
            )
        ],
        rate_options=[option],
    )


def test_save_product_persists_full_graph(conn) -> None:
    product_id = save_product(conn, _sample_product())

    row = conn.execute(
        "SELECT p.name, i.name, p.disclosed_month, p.max_limit_won "
        "FROM products p JOIN institutions i ON i.id = p.institution_id WHERE p.id=?",
        (product_id,),
    ).fetchone()
    assert row == ("테스트적금", "테스트은행", "202609", 10_000_000)

    rate_option = conn.execute(
        "SELECT term_months, base_rate_bps, max_rate_bps FROM rate_options WHERE product_id=?",
        (product_id,),
    ).fetchone()
    assert rate_option == (12, 200, 300)

    bonus = conn.execute(
        "SELECT local_id, label, rate_bps, combinator FROM bonuses "
        "WHERE rate_option_id = (SELECT id FROM rate_options WHERE product_id=?)",
        (product_id,),
    ).fetchone()
    assert bonus == ("b1", "급여이체", 100, "sole")

    requirement = conn.execute(
        "SELECT codes_json, param_json FROM bonus_requirements "
        "WHERE bonus_id = (SELECT id FROM bonuses WHERE rate_option_id = "
        "(SELECT id FROM rate_options WHERE product_id=?))",
        (product_id,),
    ).fetchone()
    assert json.loads(requirement[0]) == ["salary_transfer"]
    assert json.loads(requirement[1]) == {"min_months": 6}

    eligibility = conn.execute(
        "SELECT codes_json, evidence_quote FROM eligibility WHERE product_id=?", (product_id,)
    ).fetchone()
    assert json.loads(eligibility[0]) == ["age_range"]
    assert eligibility[1] == "만 19세 이상"


def test_saving_same_product_again_replaces_old_data(conn) -> None:
    save_product(conn, _sample_product(rate_bps=100))
    save_product(conn, _sample_product(rate_bps=250))  # 재추출로 값이 바뀐 상황

    products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    assert products == 1  # 새로 추가되지 않고 교체됨

    bonus_rate = conn.execute("SELECT rate_bps FROM bonuses").fetchone()[0]
    assert bonus_rate == 250  # 옛날 값(100)이 아니라 최신 값


def test_different_disclosed_month_creates_separate_row(conn) -> None:
    save_product(conn, _sample_product(disclosed_month="202608"))
    save_product(conn, _sample_product(disclosed_month="202609"))

    count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    assert count == 2  # 공시월이 다르면 별개 이력으로 남는다


def test_exclusive_pairs_are_saved(conn) -> None:
    bonus_a = Bonus(
        id="b1", label="A", rate_bps=60, combinator=RequirementCombinator.SOLE,
        requirements=[RequirementRef(codes=[RequirementCode.SALARY_TRANSFER])],
        evidence=Evidence(quote="A", source_field="spcl_cnd"),
    )
    bonus_b = Bonus(
        id="b2", label="B", rate_bps=40, combinator=RequirementCombinator.SOLE,
        requirements=[RequirementRef(codes=[RequirementCode.UTILITY_AUTOPAY])],
        evidence=Evidence(quote="B", source_field="spcl_cnd"),
    )
    option = RateOption(
        term_months=12, reserve_type=ReserveType.FREE, base_rate_bps=200, max_rate_bps=260,
        bonus_group=BonusGroup(id="g", cap_bps=None, bonuses=[bonus_a, bonus_b], exclusive_pairs=[("b1", "b2")]),
    )
    product = Product(
        institution_name="테스트은행", name="테스트적금", category=ProductCategory.SAVINGS,
        disclosed_month="202609", source_hash="h", rate_options=[option],
    )
    product_id = save_product(conn, product)
    pair = conn.execute(
        "SELECT bonus_local_id_a, bonus_local_id_b FROM bonus_exclusive_pairs "
        "WHERE rate_option_id = (SELECT id FROM rate_options WHERE product_id=?)",
        (product_id,),
    ).fetchone()
    assert pair == ("b1", "b2")


def test_log_extraction_result(conn) -> None:
    log_extraction_result(conn, "테스트은행", "테스트적금", 12, "accepted", None, 0)
    log_extraction_result(conn, "테스트은행", "테스트적금2", 24, "excluded", "gap 불일치", 1)

    rows = conn.execute(
        "SELECT product_name, term_months, status, reason, retry_count FROM extraction_log ORDER BY id"
    ).fetchall()
    assert rows == [
        ("테스트적금", 12, "accepted", None, 0),
        ("테스트적금2", 24, "excluded", "gap 불일치", 1),
    ]
