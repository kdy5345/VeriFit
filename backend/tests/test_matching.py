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
from app.schemas.user import UserFact, UserProfile
from app.services.matching import evaluate_rate_option, find_matches


def _bonus(id_, rate_bps, codes, combinator=RequirementCombinator.SOLE, param=None, extra_req=None):
    reqs = [RequirementRef(codes=codes, param=param or {})]
    if extra_req:
        reqs.append(extra_req)
    return Bonus(
        id=id_, label=id_, rate_bps=rate_bps, combinator=combinator, requirements=reqs,
        evidence=Evidence(quote="x", source_field="spcl_cnd"),
    )


def _option(bonuses, base=200, max_=300, cap=None, exclusive=None) -> RateOption:
    return RateOption(
        term_months=12, reserve_type=ReserveType.FREE, base_rate_bps=base, max_rate_bps=max_,
        bonus_group=BonusGroup(id="g", cap_bps=cap, bonuses=bonuses, exclusive_pairs=exclusive or []),
    )


def test_sole_bonus_satisfied_with_matching_amount() -> None:
    option = _option([
        _bonus("b1", 50, [RequirementCode.CARD_USAGE_AMOUNT], param={"min_amount_won": 100_000}),
    ])
    profile = UserProfile(
        monthly_deposit_won=300_000, term_months=12,
        facts={RequirementCode.CARD_USAGE_AMOUNT: UserFact(amount_won=150_000)},
    )
    match = evaluate_rate_option(option, profile)
    assert match.achieved_rate_bps == 250
    assert [b.id for b in match.satisfied_bonuses] == ["b1"]


def test_sole_bonus_not_satisfied_when_amount_below_threshold() -> None:
    option = _option([
        _bonus("b1", 50, [RequirementCode.CARD_USAGE_AMOUNT], param={"min_amount_won": 100_000}),
    ])
    profile = UserProfile(
        monthly_deposit_won=300_000, term_months=12,
        facts={RequirementCode.CARD_USAGE_AMOUNT: UserFact(amount_won=50_000)},
    )
    match = evaluate_rate_option(option, profile)
    assert match.achieved_rate_bps == 200
    assert [b.id for b in match.unmet_bonuses] == ["b1"]


def test_unknown_code_is_treated_as_unsatisfied() -> None:
    option = _option([_bonus("b1", 50, [RequirementCode.SALARY_TRANSFER])])
    profile = UserProfile(monthly_deposit_won=300_000, term_months=12)  # facts 없음
    match = evaluate_rate_option(option, profile)
    assert match.achieved_rate_bps == 200


def test_and_combinator_requires_all() -> None:
    option = _option([
        _bonus(
            "b1", 30, [RequirementCode.MARKETING_CONSENT_CALL],
            combinator=RequirementCombinator.AND,
            extra_req=RequirementRef(codes=[RequirementCode.MARKETING_CONSENT_SMS]),
        )
    ])
    profile_partial = UserProfile(
        monthly_deposit_won=100_000, term_months=12,
        facts={RequirementCode.MARKETING_CONSENT_CALL: UserFact()},
    )
    assert evaluate_rate_option(option, profile_partial).achieved_rate_bps == 200

    profile_full = UserProfile(
        monthly_deposit_won=100_000, term_months=12,
        facts={
            RequirementCode.MARKETING_CONSENT_CALL: UserFact(),
            RequirementCode.MARKETING_CONSENT_SMS: UserFact(),
        },
    )
    assert evaluate_rate_option(option, profile_full).achieved_rate_bps == 230


def test_or_codes_within_single_requirement() -> None:
    option = _option([_bonus("b1", 40, [RequirementCode.SALARY_TRANSFER, RequirementCode.PENSION_TRANSFER])])
    profile = UserProfile(
        monthly_deposit_won=100_000, term_months=12,
        facts={RequirementCode.PENSION_TRANSFER: UserFact()},
    )
    assert evaluate_rate_option(option, profile).achieved_rate_bps == 240


def test_group_cap_limits_total() -> None:
    option = _option(
        [
            _bonus("b1", 60, [RequirementCode.SALARY_TRANSFER]),
            _bonus("b2", 40, [RequirementCode.UTILITY_AUTOPAY]),
        ],
        cap=80,
    )
    profile = UserProfile(
        monthly_deposit_won=100_000, term_months=12,
        facts={
            RequirementCode.SALARY_TRANSFER: UserFact(),
            RequirementCode.UTILITY_AUTOPAY: UserFact(),
        },
    )
    match = evaluate_rate_option(option, profile)
    assert match.achieved_rate_bps == 280  # 200 + min(100,80)


def test_exclusive_pair_keeps_only_higher_one() -> None:
    option = _option(
        [
            _bonus("b1", 60, [RequirementCode.SALARY_TRANSFER]),
            _bonus("b2", 40, [RequirementCode.UTILITY_AUTOPAY]),
        ],
        exclusive=[("b1", "b2")],
    )
    profile = UserProfile(
        monthly_deposit_won=100_000, term_months=12,
        facts={
            RequirementCode.SALARY_TRANSFER: UserFact(),
            RequirementCode.UTILITY_AUTOPAY: UserFact(),
        },
    )
    match = evaluate_rate_option(option, profile)
    assert match.achieved_rate_bps == 260  # 200 + 60만 인정, 40은 배타로 제외
    assert match.dropped_by_exclusivity == ("b2",)


def test_option_without_bonus_group_returns_base_rate() -> None:
    option = RateOption(term_months=12, reserve_type=ReserveType.FIXED, base_rate_bps=250, max_rate_bps=250)
    profile = UserProfile(monthly_deposit_won=100_000, term_months=12)
    assert evaluate_rate_option(option, profile).achieved_rate_bps == 250


def test_find_matches_filters_by_term_and_sorts_by_rate() -> None:
    def product(name, term, base, bonus_rate, code) -> Product:
        return Product(
            institution_name="은행", name=name, category=ProductCategory.SAVINGS,
            disclosed_month="202609", source_hash="h",
            rate_options=[_option([_bonus("b1", bonus_rate, [code])], base=base, max_=base + bonus_rate).model_copy(
                update={"term_months": term}
            )],
        )

    p1 = product("A", 12, 200, 50, RequirementCode.SALARY_TRANSFER)
    p2 = product("B", 12, 250, 30, RequirementCode.SALARY_TRANSFER)
    p3 = product("C", 24, 400, 0, RequirementCode.SALARY_TRANSFER)  # 다른 term이라 제외돼야 함

    profile = UserProfile(
        monthly_deposit_won=100_000, term_months=12,
        facts={RequirementCode.SALARY_TRANSFER: UserFact()},
    )
    matches = find_matches([p1, p2, p3], profile)
    assert [m.product.name for m in matches] == ["B", "A"]  # A=250, B=280 -> B가 위. C는 term 달라 제외
    assert matches[0].match.achieved_rate_bps >= matches[1].match.achieved_rate_bps


def test_eligibility_other_sets_warning_flag() -> None:
    product = Product(
        institution_name="은행", name="상품", category=ProductCategory.SAVINGS,
        disclosed_month="202609", source_hash="h",
        eligibility=[
            EligibilityRef(
                codes=[RequirementCode.OTHER], param={},
                evidence=Evidence(quote="중소기업 근로자", source_field="join_member"),
            )
        ],
        rate_options=[RateOption(term_months=12, reserve_type=ReserveType.FREE, base_rate_bps=200, max_rate_bps=200)],
    )
    profile = UserProfile(monthly_deposit_won=100_000, term_months=12)
    matches = find_matches([product], profile)
    assert matches[0].eligibility_warning is True
