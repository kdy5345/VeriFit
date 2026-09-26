"""POST /api/v1/evaluate 요청·응답 스키마."""

from pydantic import BaseModel, Field


class ProductResult(BaseModel):
    institution_name: str
    product_name: str
    reserve_type: str
    compounding: str
    term_months: int
    base_rate_bps: int
    max_rate_bps: int
    achieved_rate_bps: int
    pre_tax_interest_won: int
    tax_won: int
    after_tax_interest_won: int
    maturity_amount_won: int
    satisfied_bonus_labels: list[str] = Field(default_factory=list)
    unmet_bonus_labels: list[str] = Field(default_factory=list)
    eligibility_warning: bool = False


class NextQuestion(BaseModel):
    code: str
    question: str


class EvaluateResponse(BaseModel):
    results: list[ProductResult] = Field(default_factory=list)
    next_question: NextQuestion | None = None
    disclaimer: str = (
        "세후 이자는 이자소득세 15.4%(일반과세) 기준 근사치입니다. 청년우대형·"
        "세금우대종합저축 같은 비과세·저율과세 특례는 반영하지 않았습니다. "
        "가입 자격에 '직접 확인 필요' 표시가 있으면 은행에 자격 조건을 다시 확인하세요."
    )
