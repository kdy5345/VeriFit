"""적금 이자 계산. 전부 Decimal로 계산해 원 단위로 반올림한다 (finance_agent에서
쓴 방식과 같은 이유: 부동소수점 오차가 금액 계산에 섞이면 안 된다).

공식 (매월 초 납입, 만기까지 보유 가정):
  단리: 이자 = 월납입액 × 연이율 × n(n+1) / (12 × 2)
    각 회차 납입금이 만기까지 남은 개월 수만큼 단리로 이자를 받는다는 뜻.
  복리(월복리): 이자 = Σ_{k=1..n} 월납입액 × ((1+월이율)^(n-k+1) - 1)
    k번째 납입금이 (n-k+1)개월 동안 매달 복리로 불어난다는 뜻.

세후 이자는 이자소득세 15.4%(소득세 14% + 지방소득세 1.4%)를 적용한다. 청년우대형,
세금우대종합저축 같은 비과세·저율과세 특례는 반영하지 않는다 — 이 계산기는 그런
특례가 없는 일반 과세 기준의 근사치이고, 실제로는 상품마다 다를 수 있다는 점을
결과에 항상 같이 표시해야 한다.
"""

from decimal import ROUND_HALF_UP, Decimal, getcontext

from pydantic import BaseModel

getcontext().prec = 28

TAX_RATE = Decimal("0.154")  # 이자소득세 14% + 지방소득세 1.4%
WON = Decimal("1")


class InterestResult(BaseModel):
    pre_tax_interest_won: int
    tax_won: int
    after_tax_interest_won: int
    maturity_amount_won: int  # 원금 총 납입액 + 세후 이자


def _round_won(value: Decimal) -> int:
    return int(value.quantize(WON, rounding=ROUND_HALF_UP))


def _simple_interest(monthly_deposit: Decimal, annual_rate: Decimal, n: int) -> Decimal:
    return monthly_deposit * annual_rate * Decimal(n * (n + 1)) / Decimal(24)


def _compound_interest(monthly_deposit: Decimal, annual_rate: Decimal, n: int) -> Decimal:
    monthly_rate = annual_rate / Decimal(12)
    total_principal_and_interest = Decimal(0)
    for k in range(1, n + 1):
        months_growing = n - k + 1
        total_principal_and_interest += monthly_deposit * (Decimal(1) + monthly_rate) ** months_growing
    return total_principal_and_interest - monthly_deposit * Decimal(n)


def calculate_savings_interest(
    monthly_deposit_won: int,
    term_months: int,
    annual_rate_bps: int,
    compounding: str = "simple",
) -> InterestResult:
    deposit = Decimal(monthly_deposit_won)
    rate = Decimal(annual_rate_bps) / Decimal(10_000)

    if compounding == "compound":
        pre_tax = _compound_interest(deposit, rate, term_months)
    else:
        pre_tax = _simple_interest(deposit, rate, term_months)

    pre_tax_won = _round_won(pre_tax)
    tax_won = _round_won(Decimal(pre_tax_won) * TAX_RATE)
    after_tax_won = pre_tax_won - tax_won
    total_deposit = monthly_deposit_won * term_months

    return InterestResult(
        pre_tax_interest_won=pre_tax_won,
        tax_won=tax_won,
        after_tax_interest_won=after_tax_won,
        maturity_amount_won=total_deposit + after_tax_won,
    )
