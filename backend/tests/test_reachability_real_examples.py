"""2026-09 금융상품 한눈에 적금 공시 실데이터 3건을 손으로 스키마에 채워 검증한다.

Extractor LLM을 만들기 전에, 스키마와 도달가능성 검사기가 실제 원문 패턴을
버텨내는지 사람이 먼저 확인하는 단계다. 세 상품은 일부러 서로 다른 이유로 골랐다:
  - 우리SUPER주거래적금: 조건 여러 개 + 표준 목록 밖 항목이 섞여 있지만, 그
    항목을 빼도 나머지만으로 최고금리에 도달한다 → 등록되어야 한다.
  - IBK중기근로자우대적금: 핵심 우대가 "재직기간에 따라 최고 X%p"처럼 정확한
    폭을 알 수 없다 → 도달 불가로 제외되어야 한다.
  - KB국민프리미엄적금: 헤드라인 우대(①)가 "단체가입/나라사랑/쿠폰"처럼 표준
    조건으로 쪼갤 수 없는 묶음이다 → 도달 불가로 제외되어야 한다.
"""

from app.schemas.graph import (
    Bonus,
    BonusGroup,
    Product,
    ProductCategory,
    RateOption,
    RequirementCombinator,
    RequirementRef,
    ReserveType,
)
from app.schemas.graph import Evidence
from app.schemas.requirements import RequirementCode
from app.services.reachability import check_reachability


def _evidence(quote: str) -> Evidence:
    return Evidence(quote=quote, source_field="spcl_cnd")


def test_woori_super_reaches_max_by_excluding_unmappable_coupon_item() -> None:
    """가+나+다+마케팅동의만으로 정확히 140bp(=3.85%-2.45%) 도달, 금리쿠폰 항목은 제외."""
    bonuses = [
        Bonus(
            id="b1",
            label="급여/연금이체 실적",
            rate_bps=70,
            combinator=RequirementCombinator.SOLE,
            requirements=[
                RequirementRef(
                    codes=[RequirementCode.SALARY_TRANSFER, RequirementCode.PENSION_TRANSFER],
                    param={"min_months": 6, "term_months": 12},
                )
            ],
            evidence=_evidence("가.급여/연금 이체:연 0.7%p"),
        ),
        Bonus(
            id="b2",
            label="공과금 자동이체 실적",
            rate_bps=30,
            combinator=RequirementCombinator.SOLE,
            requirements=[
                RequirementRef(codes=[RequirementCode.UTILITY_AUTOPAY], param={"min_months": 6})
            ],
            evidence=_evidence("나.공과금 자동이체 출금: 0.3%p"),
        ),
        Bonus(
            id="b3",
            label="카드결제 실적",
            rate_bps=30,
            combinator=RequirementCombinator.SOLE,
            requirements=[
                RequirementRef(
                    codes=[RequirementCode.CARD_USAGE_AMOUNT],
                    param={"min_amount_won": 100_000, "min_months": 6},
                )
            ],
            evidence=_evidence("다.우리카드사 신용/체크카드 결제 10만원 이상: 연 0.3%p"),
        ),
        Bonus(
            id="b4",
            label="마케팅 동의(전화+SMS)",
            rate_bps=10,
            combinator=RequirementCombinator.AND,
            requirements=[
                RequirementRef(codes=[RequirementCode.MARKETING_CONSENT_CALL]),
                RequirementRef(codes=[RequirementCode.MARKETING_CONSENT_SMS]),
            ],
            evidence=_evidence("전화(휴대폰) 및 SMS항목을 모두 동의 후 만기까지 유지 : 연 0.1%p"),
        ),
        Bonus(
            id="b5",
            label="금리쿠폰 적용 (폭 미기재)",
            rate_bps=0,
            combinator=RequirementCombinator.SOLE,
            requirements=[RequirementRef(codes=[RequirementCode.OTHER])],
            evidence=_evidence("3. 금리쿠폰을 적용"),
        ),
    ]
    option = RateOption(
        term_months=12,
        reserve_type=ReserveType.FREE,
        base_rate_bps=245,
        max_rate_bps=385,
        bonus_group=BonusGroup(id="g1", cap_bps=None, bonuses=bonuses),
    )
    result = check_reachability(option)
    assert result.reachable is True
    assert result.gap_bps == 140
    assert set(result.best_combo) == {"b1", "b2", "b3", "b4"}
    assert result.max_achievable_bps == 140
    assert result.overshoot is False
    assert result.excluded_other == ("b5",)


def test_ibk_worker_savings_is_excluded_variable_tenure_bonus_unmeasurable() -> None:
    """급여이체(100bp)만으로는 220bp 갭에 못 미치고, 재직기간 우대는 폭을 특정할 수 없어 OTHER."""
    bonuses = [
        Bonus(
            id="b1",
            label="재직기간별 우대 (정확한 구간 미기재)",
            rate_bps=0,
            combinator=RequirementCombinator.SOLE,
            requirements=[RequirementRef(codes=[RequirementCode.OTHER])],
            evidence=_evidence("가입시점 중소기업 근로자로 확인된 경우 : 재직기간에 따라 최고 연 1.2%p"),
        ),
        Bonus(
            id="b2",
            label="급여이체 실적",
            rate_bps=100,
            combinator=RequirementCombinator.SOLE,
            requirements=[
                RequirementRef(
                    codes=[RequirementCode.SALARY_TRANSFER],
                    param={"min_amount_won": 500_000, "min_months": 6},
                )
            ],
            evidence=_evidence("당행 급여이체 실적(월50만원 이상) 6개월 이상인 경우 : 연 1.0%p"),
        ),
    ]
    option = RateOption(
        term_months=12,
        reserve_type=ReserveType.FREE,
        base_rate_bps=250,
        max_rate_bps=470,
        bonus_group=BonusGroup(id="g1", cap_bps=None, bonuses=bonuses),
    )
    result = check_reachability(option)
    assert result.reachable is False
    assert result.gap_bps == 220
    assert result.excluded_other == ("b1",)


def test_kb_premium_all_terms_excluded_headline_bonus_is_unmappable_bundle() -> None:
    """①(단체가입/나라사랑/쿠폰)이 표준 조건으로 안 쪼개져 OTHER, ②(30bp)만으론 3개 만기 전부 미달."""

    def option_for(term: int, base: int, max_: int, bundle_bps: int) -> RateOption:
        bonuses = [
            Bonus(
                id="b1",
                label="단체가입/나라사랑/쿠폰 우대",
                rate_bps=0,
                combinator=RequirementCombinator.SOLE,
                requirements=[RequirementRef(codes=[RequirementCode.OTHER])],
                evidence=_evidence(f"① 단체가입/나라사랑/쿠폰 우대이율: {term}년: 연 {bundle_bps / 100:.1f}%p"),
            ),
            Bonus(
                id="b2",
                label="교차거래 우대",
                rate_bps=30,
                combinator=RequirementCombinator.SOLE,
                requirements=[RequirementRef(codes=[RequirementCode.LINKED_PRODUCT_HELD])],
                evidence=_evidence("② 교차거래 우대이율: 연 0.3%p"),
            ),
        ]
        return RateOption(
            term_months=term,
            reserve_type=ReserveType.FIXED,
            base_rate_bps=base,
            max_rate_bps=max_,
            bonus_group=BonusGroup(id=f"g{term}", cap_bps=None, bonuses=bonuses),
        )

    options = [option_for(12, 275, 365, 60), option_for(24, 295, 395, 70), option_for(36, 305, 425, 90)]
    for option in options:
        result = check_reachability(option)
        assert result.reachable is False, f"{option.term_months}개월은 제외돼야 하는데 통과함"


def test_product_wrapper_accepts_valid_rate_options() -> None:
    """Product 스키마 자체(가입자격, 여러 RateOption 묶기)도 문제없이 채워지는지 확인."""
    option = RateOption(
        term_months=12,
        reserve_type=ReserveType.FREE,
        base_rate_bps=245,
        max_rate_bps=245,  # 우대 없음 케이스도 스키마상 허용되어야 함
    )
    product = Product(
        institution_name="우리은행",
        name="우리SUPER주거래적금",
        category=ProductCategory.SAVINGS,
        disclosed_month="202609",
        source_hash="dummy-hash-for-test",
        rate_options=[option],
    )
    assert product.rate_options[0].bonus_group is None


def test_overshoot_is_detected_when_all_bonuses_stack_above_gap() -> None:
    """60+40+20이 전부 동시 적용 가능한데 gap이 100bp뿐이면, 60+40=100인 부분집합이
    있어도 통과시키면 안 된다. 진짜 최댓값(120)이 gap을 넘는다는 걸 잡아야 한다
    (그룹 한도나 중복 불가 조건이 빠졌다는 신호)."""
    bonuses = [
        Bonus(
            id="b1", label="A", rate_bps=60, combinator=RequirementCombinator.SOLE,
            requirements=[RequirementRef(codes=[RequirementCode.SALARY_TRANSFER])],
            evidence=_evidence("A: 0.6%p"),
        ),
        Bonus(
            id="b2", label="B", rate_bps=40, combinator=RequirementCombinator.SOLE,
            requirements=[RequirementRef(codes=[RequirementCode.UTILITY_AUTOPAY])],
            evidence=_evidence("B: 0.4%p"),
        ),
        Bonus(
            id="b3", label="C", rate_bps=20, combinator=RequirementCombinator.SOLE,
            requirements=[RequirementRef(codes=[RequirementCode.CARD_USAGE_AMOUNT])],
            evidence=_evidence("C: 0.2%p"),
        ),
    ]
    option = RateOption(
        term_months=12, reserve_type=ReserveType.FREE, base_rate_bps=200, max_rate_bps=300,
        bonus_group=BonusGroup(id="g1", cap_bps=None, bonuses=bonuses),
    )
    result = check_reachability(option)
    assert result.max_achievable_bps == 120  # 60+40+20, 셋 다 동시 적용 가능
    assert result.overshoot is True
    assert result.reachable is False  # 120 != gap(100)이므로 그대로 통과시키면 안 됨


def test_group_cap_prevents_overshoot() -> None:
    """같은 60+40+20 조합이라도, 그룹 한도(cap_bps=100)가 원문에서 확인되면 정상 통과."""
    bonuses = [
        Bonus(
            id="b1", label="A", rate_bps=60, combinator=RequirementCombinator.SOLE,
            requirements=[RequirementRef(codes=[RequirementCode.SALARY_TRANSFER])],
            evidence=_evidence("A: 0.6%p"),
        ),
        Bonus(
            id="b2", label="B", rate_bps=40, combinator=RequirementCombinator.SOLE,
            requirements=[RequirementRef(codes=[RequirementCode.UTILITY_AUTOPAY])],
            evidence=_evidence("B: 0.4%p"),
        ),
        Bonus(
            id="b3", label="C", rate_bps=20, combinator=RequirementCombinator.SOLE,
            requirements=[RequirementRef(codes=[RequirementCode.CARD_USAGE_AMOUNT])],
            evidence=_evidence("C: 0.2%p"),
        ),
    ]
    option = RateOption(
        term_months=12, reserve_type=ReserveType.FREE, base_rate_bps=200, max_rate_bps=300,
        bonus_group=BonusGroup(id="g1", cap_bps=100, bonuses=bonuses),
    )
    result = check_reachability(option)
    assert result.max_achievable_bps == 100  # 120이 아니라 cap(100)에서 잘림
    assert result.overshoot is False
    assert result.reachable is True


def test_exclusive_pair_prevents_overshoot() -> None:
    """b1·b2가 중복 불가로 명시되면, 최댓값은 둘 중 큰 것 + b3."""
    bonuses = [
        Bonus(
            id="b1", label="A", rate_bps=60, combinator=RequirementCombinator.SOLE,
            requirements=[RequirementRef(codes=[RequirementCode.SALARY_TRANSFER])],
            evidence=_evidence("A: 0.6%p"),
        ),
        Bonus(
            id="b2", label="B", rate_bps=40, combinator=RequirementCombinator.SOLE,
            requirements=[RequirementRef(codes=[RequirementCode.UTILITY_AUTOPAY])],
            evidence=_evidence("B: 0.4%p"),
        ),
        Bonus(
            id="b3", label="C", rate_bps=20, combinator=RequirementCombinator.SOLE,
            requirements=[RequirementRef(codes=[RequirementCode.CARD_USAGE_AMOUNT])],
            evidence=_evidence("C: 0.2%p"),
        ),
    ]
    option = RateOption(
        term_months=12, reserve_type=ReserveType.FREE, base_rate_bps=200, max_rate_bps=280,
        bonus_group=BonusGroup(id="g1", cap_bps=None, bonuses=bonuses, exclusive_pairs=[("b1", "b2")]),
    )
    result = check_reachability(option)
    assert result.max_achievable_bps == 80  # b1(60)+b3(20), b2는 b1과 중복 불가라 제외
    assert result.reachable is True
