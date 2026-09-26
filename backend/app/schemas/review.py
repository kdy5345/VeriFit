"""Reviewer LLM의 출력 스키마.

Extractor와 마찬가지로 Reviewer의 지적도 그냥 믿지 않는다. 모든 지적(finding)에
원문 인용을 강제하고, 그 인용이 원문에 실제로 없으면 app.services.review_verification
에서 그 지적 자체를 버린다 (Reviewer가 없는 문제를 지어내는 것도 오류이기 때문).
"""

from typing import Literal

from pydantic import BaseModel, Field


class ReviewFinding(BaseModel):
    term_months: int
    bonus_id: str | None = Field(
        default=None, description="특정 우대 항목을 지적하는 경우 그 id. 전반적인 문제면 null."
    )
    description: str = Field(
        max_length=300,
        description="무엇이 왜 틀렸다고 보는지 한국어로 구체적으로. '이상함' 같은 모호한 서술 금지.",
    )
    quote: str = Field(
        min_length=1,
        max_length=300,
        description="이 지적의 근거가 되는 원문(spcl_cnd 또는 join_member) 문장을 그대로 인용.",
    )


class ReviewResult(BaseModel):
    findings: list[ReviewFinding] = Field(
        default_factory=list,
        description="실제 오류라고 확신하는 것만 담는다. 확신 없으면 findings를 비워둔다.",
    )
