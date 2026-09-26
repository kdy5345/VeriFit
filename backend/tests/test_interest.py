from app.services.interest import calculate_savings_interest


def test_simple_interest_matches_standard_installment_formula() -> None:
    # 표준 공식: 월납입액 × 연이율 × n(n+1)/24
    # 100,000원 × 6% × 12×13/24 = 39,000원
    result = calculate_savings_interest(100_000, 12, annual_rate_bps=600, compounding="simple")
    assert result.pre_tax_interest_won == 39_000


def test_after_tax_applies_15_4_percent_tax() -> None:
    result = calculate_savings_interest(100_000, 12, annual_rate_bps=600, compounding="simple")
    assert result.tax_won == round(39_000 * 0.154)
    assert result.after_tax_interest_won == result.pre_tax_interest_won - result.tax_won


def test_maturity_amount_is_total_deposit_plus_after_tax_interest() -> None:
    result = calculate_savings_interest(100_000, 12, annual_rate_bps=600, compounding="simple")
    assert result.maturity_amount_won == 100_000 * 12 + result.after_tax_interest_won


def test_compound_interest_yields_more_than_simple_for_same_nominal_rate() -> None:
    simple = calculate_savings_interest(100_000, 24, annual_rate_bps=500, compounding="simple")
    compound = calculate_savings_interest(100_000, 24, annual_rate_bps=500, compounding="compound")
    assert compound.pre_tax_interest_won > simple.pre_tax_interest_won


def test_zero_rate_yields_zero_interest() -> None:
    result = calculate_savings_interest(200_000, 12, annual_rate_bps=0, compounding="simple")
    assert result.pre_tax_interest_won == 0
    assert result.after_tax_interest_won == 0
    assert result.maturity_amount_won == 200_000 * 12


def test_single_month_term() -> None:
    # n=1: 월납입액 × 연이율 × 1×2/24 = 월납입액 × 연이율 / 12
    result = calculate_savings_interest(1_000_000, 1, annual_rate_bps=1200, compounding="simple")
    assert result.pre_tax_interest_won == round(1_000_000 * 0.12 / 12)
