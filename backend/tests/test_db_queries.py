import pytest

from app.db.queries import load_products
from app.db.store import connect, save_product
from app.schemas.graph import (
    Bonus,
    BonusGroup,
    CompoundingType,
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


def _round_trip_product() -> Product:
    bonus_a = Bonus(
        id="b1",
        label="급여이체",
        rate_bps=70,
        combinator=RequirementCombinator.SOLE,
        requirements=[
            RequirementRef(
                codes=[RequirementCode.SALARY_TRANSFER, RequirementCode.PENSION_TRANSFER],
                param={"min_months": 6},
            )
        ],
        evidence=Evidence(quote="가.급여/연금 이체:연 0.7%p", source_field="spcl_cnd"),
    )
    bonus_b = Bonus(
        id="b2",
        label="마케팅 동의",
        rate_bps=10,
        combinator=RequirementCombinator.AND,
        requirements=[
            RequirementRef(codes=[RequirementCode.MARKETING_CONSENT_CALL]),
            RequirementRef(codes=[RequirementCode.MARKETING_CONSENT_SMS]),
        ],
        evidence=Evidence(quote="전화 및 SMS 모두 동의", source_field="spcl_cnd"),
    )
    option = RateOption(
        term_months=12,
        reserve_type=ReserveType.FREE,
        compounding=CompoundingType.COMPOUND,
        base_rate_bps=245,
        max_rate_bps=325,
        bonus_group=BonusGroup(
            id="g12", cap_bps=None, bonuses=[bonus_a, bonus_b], exclusive_pairs=[("b1", "b2")]
        ),
    )
    return Product(
        institution_name="우리은행",
        name="테스트적금",
        category=ProductCategory.SAVINGS,
        disclosed_month="202609",
        source_hash="hash-xyz",
        join_way="영업점,인터넷",
        max_limit_won=3_000_000,
        eligibility=[
            EligibilityRef(
                codes=[RequirementCode.AGE_RANGE],
                param={"note": "만 19~34세"},
                evidence=Evidence(quote="만 19세 이상 34세 이하", source_field="join_member"),
            )
        ],
        rate_options=[option],
    )


def test_load_products_round_trips_full_graph(conn) -> None:
    original = _round_trip_product()
    save_product(conn, original)

    loaded = load_products(conn)
    assert len(loaded) == 1
    product = loaded[0]

    assert product.institution_name == original.institution_name
    assert product.name == original.name
    assert product.category == original.category
    assert product.max_limit_won == 3_000_000

    assert len(product.eligibility) == 1
    assert product.eligibility[0].codes == [RequirementCode.AGE_RANGE]
    assert product.eligibility[0].evidence.quote == "만 19세 이상 34세 이하"

    assert len(product.rate_options) == 1
    option = product.rate_options[0]
    assert option.compounding == CompoundingType.COMPOUND
    assert option.reserve_type == ReserveType.FREE
    assert option.base_rate_bps == 245 and option.max_rate_bps == 325

    bonuses = {b.id: b for b in option.bonus_group.bonuses}
    assert bonuses["b1"].rate_bps == 70
    assert bonuses["b1"].requirements[0].codes == [
        RequirementCode.SALARY_TRANSFER,
        RequirementCode.PENSION_TRANSFER,
    ]
    assert bonuses["b1"].requirements[0].param == {"min_months": 6}
    assert bonuses["b2"].combinator == RequirementCombinator.AND
    assert option.bonus_group.exclusive_pairs == [("b1", "b2")]


def test_load_products_handles_option_without_bonuses(conn) -> None:
    product = Product(
        institution_name="은행",
        name="상품",
        category=ProductCategory.SAVINGS,
        disclosed_month="202609",
        source_hash="h",
        rate_options=[
            RateOption(term_months=6, reserve_type=ReserveType.FIXED, base_rate_bps=200, max_rate_bps=200)
        ],
    )
    save_product(conn, product)
    loaded = load_products(conn)
    assert loaded[0].rate_options[0].bonus_group is None
    assert loaded[0].rate_options[0].compounding == CompoundingType.SIMPLE  # 기본값


def test_load_products_returns_multiple_products(conn) -> None:
    save_product(conn, _round_trip_product())
    second = _round_trip_product().model_copy(update={"name": "두번째적금", "rate_options": []})
    second = second.model_copy(
        update={
            "rate_options": [
                RateOption(
                    term_months=24, reserve_type=ReserveType.FIXED, base_rate_bps=300, max_rate_bps=300
                )
            ]
        }
    )
    save_product(conn, second)

    loaded = load_products(conn)
    assert {p.name for p in loaded} == {"테스트적금", "두번째적금"}
