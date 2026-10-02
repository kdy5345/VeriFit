"""POST /api/v1/evaluate 요청·응답 스키마."""

from pydantic import BaseModel, Field
from app.schemas.user import ConditionStatus, UserProfile


class ProductResult(BaseModel):
    product_key: str = ""
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
    eligibility_status: ConditionStatus = ConditionStatus.SATISFIED
    eligibility_reasons: list[str] = Field(default_factory=list)
    unknown_bonus_labels: list[str] = Field(default_factory=list)
    potential_rate_bps: int = 0
    potential_after_tax_interest_won: int = 0
    disclosed_month: str = ""
    updated_at: str | None = None
    source_hash: str = ""


class NextQuestion(BaseModel):
    code: str
    question: str
    interest_gain_won: int = 0
    affected_products: int = 0
    missing_fields: list[str] = Field(default_factory=list)
    hypothetical: bool = True
    explanation: str = "조건을 충족한다고 가정한 비교이며 실제 우대 적용을 보장하지 않습니다."


class EvaluateResponse(BaseModel):
    results: list[ProductResult] = Field(default_factory=list)
    next_question: NextQuestion | None = None
    excluded_results: list[ProductResult] = Field(default_factory=list)
    disclaimer: str = (
        "세후 이자는 이자소득세 15.4%(일반과세) 기준 근사치입니다. 청년우대형·"
        "세금우대종합저축 같은 비과세·저율과세 특례는 반영하지 않았습니다. "
        "가입 자격에 '직접 확인 필요' 표시가 있으면 은행에 자격 조건을 다시 확인하세요."
    )


class Scenario(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    profile: UserProfile


class ScenarioRequest(BaseModel):
    baseline: UserProfile
    scenarios: list[Scenario] = Field(min_length=1, max_length=5)


class ScenarioDelta(BaseModel):
    product_key: str
    product_name: str
    after_tax_interest_delta_won: int | None
    baseline_rank: int | None
    scenario_rank: int


class ScenarioResult(BaseModel):
    name: str
    evaluation: EvaluateResponse
    deltas: list[ScenarioDelta]


class ScenarioResponse(BaseModel):
    baseline: EvaluateResponse
    scenarios: list[ScenarioResult]
    disclaimer: str = "가정 비교입니다. 납입액이나 기간 변경으로 원금도 달라질 수 있으며, 가입 가능 여부와 세후 이자를 함께 확인하세요."
