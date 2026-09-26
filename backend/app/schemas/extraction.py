"""Extractor LLM이 실제로 채우는 출력 스키마.

원칙: 기관명·상품명·기간·기본금리·최고금리는 금융상품 한눈에 API가 이미 정확한
값으로 주므로 LLM에게 다시 시키지 않는다. LLM은 자유 텍스트 두 곳
(spcl_cnd=우대조건, join_member=가입자격)을 구조화하는 일만 한다.

param을 열린 dict 대신 명시적 필드로 둔 이유: Gemini의 responseJsonSchema가
dict[str, str|int] 같은 열린 타입을 안정적으로 못 만들고, 나중에 사용자 조건과
비교할 때(예: min_amount_won <= 사용자 입력)도 필드가 고정돼 있어야 코드가
비교하기 쉽다.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.requirements import RequirementCode


class LlmRequirementRef(BaseModel):
    codes: list[RequirementCode] = Field(
        min_length=1,
        description="이 중 하나라도 충족하면 인정. 보통 원소 1개. "
        "'급여/연금 이체'처럼 원문이 양자택일이면 2개.",
    )
    min_amount_won: int | None = Field(default=None, description="금액 기준 (원)")
    min_months: int | None = Field(default=None, description="실적 인정에 필요한 개월 수")
    min_count: int | None = Field(default=None, description="횟수 기준")
    channel: str | None = Field(default=None, description="마케팅 동의 채널 등 기타 구분자")


class LlmBonus(BaseModel):
    id: str = Field(description="이 상품 안에서만 고유하면 됨. 예: b1, b2")
    label: str = Field(max_length=100)
    rate_bps: int = Field(
        ge=0,
        le=2_000,
        description="원문에 숫자가 없으면(예: '재직기간에 따라 최고 X%p'처럼 구간표가 "
        "없는 경우) 0을 넣고 codes에 other를 포함시켜라.",
    )
    combinator: Literal["and", "or", "sole"]
    requirements: list[LlmRequirementRef] = Field(min_length=1)
    evidence_quote: str = Field(
        min_length=1, max_length=300, description="이 항목의 근거가 되는 원문을 그대로 인용"
    )


class LlmRateOptionBonuses(BaseModel):
    """이미 알고 있는 (term_months, base_rate_bps, max_rate_bps) 하나에 대응하는 우대 목록."""

    term_months: int
    bonuses: list[LlmBonus]
    group_cap_bps: int | None = Field(
        default=None,
        description="개별 항목과 별도로 원문에 '합산 최대 X%p'처럼 전체 상한이 "
        "명시된 경우에만 채운다. 없으면 null.",
    )
    exclusive_bonus_id_pairs: list[list[str]] = Field(
        default_factory=list,
        description="원문에 '①,② 중 하나만 적용', '중복 적용 불가'처럼 두 항목을 "
        "동시에 인정하지 않는다는 표현이 있으면 그 두 bonus id를 [id1, id2]로.",
    )


class LlmEligibility(BaseModel):
    codes: list[RequirementCode] = Field(min_length=1)
    note: str | None = Field(default=None, max_length=100)
    evidence_quote: str = Field(min_length=1, max_length=300)


class LlmExtraction(BaseModel):
    status: Literal["extracted", "no_bonus"] = Field(
        description="spcl_cnd에 실질적인 우대조건이 없으면(예: '해당없음') no_bonus"
    )
    eligibility: list[LlmEligibility] = Field(default_factory=list)
    rate_options: list[LlmRateOptionBonuses] = Field(default_factory=list)
