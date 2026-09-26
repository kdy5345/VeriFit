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
from app.schemas.user import UserFact, UserProfile
from app.services.matching import find_matches
from app.services.next_question import recommend_next_question


def _bonus(id_, rate_bps, code) -> Bonus:
    return Bonus(
        id=id_, label=id_, rate_bps=rate_bps, combinator=RequirementCombinator.SOLE,
        requirements=[RequirementRef(codes=[code])],
        evidence=Evidence(quote="x", source_field="spcl_cnd"),
    )


def _product(name, bonuses) -> Product:
    return Product(
        institution_name="은행", name=name, category=ProductCategory.SAVINGS,
        disclosed_month="202609", source_hash="h",
        rate_options=[
            RateOption(
                term_months=12, reserve_type=ReserveType.FREE, base_rate_bps=200, max_rate_bps=200 + sum(b.rate_bps for b in bonuses),
                bonus_group=BonusGroup(id="g", cap_bps=None, bonuses=bonuses, exclusive_pairs=[]),
            )
        ],
    )


def test_picks_code_with_highest_total_impact_across_products() -> None:
    p1 = _product("A", [_bonus("b1", 30, RequirementCode.SALARY_TRANSFER)])
    p2 = _product("B", [_bonus("b1", 50, RequirementCode.SALARY_TRANSFER)])
    p3 = _product("C", [_bonus("b1", 10, RequirementCode.UTILITY_AUTOPAY)])
    profile = UserProfile(monthly_deposit_won=100_000, term_months=12)

    matches = find_matches([p1, p2, p3], profile)
    result = recommend_next_question(matches, profile)

    assert result is not None
    code, label = result
    assert code == RequirementCode.SALARY_TRANSFER  # 30+50=80 > 10
    assert "급여" in label


def test_returns_none_when_nothing_left_to_ask() -> None:
    p1 = _product("A", [_bonus("b1", 30, RequirementCode.SALARY_TRANSFER)])
    profile = UserProfile(
        monthly_deposit_won=100_000, term_months=12,
        facts={RequirementCode.SALARY_TRANSFER: UserFact()},  # 이미 만족 → 더 물을 게 없음
    )
    matches = find_matches([p1], profile)
    assert recommend_next_question(matches, profile) is None


def test_other_code_is_never_suggested() -> None:
    p1 = _product("A", [_bonus("b1", 100, RequirementCode.OTHER)])
    profile = UserProfile(monthly_deposit_won=100_000, term_months=12)
    matches = find_matches([p1], profile)
    assert recommend_next_question(matches, profile) is None


def test_already_dissatisfying_amount_fact_still_counts_as_known_and_not_asked() -> None:
    """카드 실적 조건에 금액 사실이 이미 있지만 기준 미달이면, 이 조건은 '이미 안다'고
    보고 다시 묻지 않는다 (v1 범위: 세부 수치 재질문은 지원 안 함)."""
    p1 = _product("A", [_bonus("b1", 100, RequirementCode.CARD_USAGE_AMOUNT)])
    profile = UserProfile(
        monthly_deposit_won=100_000, term_months=12,
        facts={RequirementCode.CARD_USAGE_AMOUNT: UserFact(satisfied=False)},
    )
    matches = find_matches([p1], profile)
    assert recommend_next_question(matches, profile) is None
