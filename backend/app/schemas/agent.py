"""자연어 사용자 질의를 처리하는 온라인 Agent의 입출력 스키마."""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.requirements import RequirementCode
from app.schemas.user import UserFact, UserProfile


class AskRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2_000)
    thread_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="후속 대화에서 이전 응답의 thread_id를 그대로 전달합니다.",
    )


class AnalyzedFact(BaseModel):
    code: RequirementCode
    satisfied: bool
    amount_won: int | None = Field(default=None, ge=0)
    months: int | None = Field(default=None, ge=0)
    count: int | None = Field(default=None, ge=0)
    channel: str | None = None
    evidence_quote: str = Field(min_length=1, max_length=300)

    def to_user_fact(self) -> UserFact:
        return UserFact(
            satisfied=self.satisfied,
            amount_won=self.amount_won,
            months=self.months,
            count=self.count,
            channel=self.channel,
        )


class AnalyzedUserInput(BaseModel):
    monthly_deposit_won: int | None = Field(default=None, gt=0)
    monthly_deposit_quote: str | None = Field(default=None, max_length=100)
    term_months: int | None = Field(default=None, gt=0, le=60)
    term_quote: str | None = Field(default=None, max_length=100)
    facts: list[AnalyzedFact] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list, max_length=10)

    def to_user_profile(self) -> UserProfile:
        if self.monthly_deposit_won is None or self.term_months is None:
            raise ValueError("월 납입액과 가입 기간이 모두 필요합니다.")
        return UserProfile(
            monthly_deposit_won=self.monthly_deposit_won,
            term_months=self.term_months,
            facts={fact.code: fact.to_user_fact() for fact in self.facts},
        )


class BonusEvidenceResult(BaseModel):
    bonus_id: str
    label: str
    rate_bps: int
    satisfied: bool
    evidence_quote: str


class AgentProductResult(BaseModel):
    product_key: str
    institution_name: str
    product_name: str
    reserve_type: str
    term_months: int
    base_rate_bps: int
    achieved_rate_bps: int
    max_rate_bps: int
    after_tax_interest_won: int
    maturity_amount_won: int
    eligibility_warning: bool = False
    bonuses: list[BonusEvidenceResult] = Field(default_factory=list)


class DraftProductClaim(BaseModel):
    product_key: str
    achieved_rate_bps: int
    after_tax_interest_won: int
    evidence_quotes: list[str] = Field(default_factory=list)


class DraftAnswer(BaseModel):
    answer: str = Field(min_length=1, max_length=4_000)
    product_claims: list[DraftProductClaim] = Field(default_factory=list)


class AnswerReview(BaseModel):
    approved: bool
    findings: list[str] = Field(default_factory=list, max_length=10)


class AskResponse(BaseModel):
    thread_id: str
    status: Literal["completed", "needs_input", "failed"]
    answer: str
    extracted_profile: UserProfile | None = None
    products: list[AgentProductResult] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    used_fallback: bool = False
    retry_count: int = 0
    verification_errors: list[str] = Field(default_factory=list)
    disclaimer: str = (
        "예상 금리와 이자는 입력한 조건 및 금융감독원 공시 정보를 기준으로 계산한 "
        "근사치입니다. 실제 적용 여부와 금리는 가입 시 금융회사에서 확인하세요."
    )
