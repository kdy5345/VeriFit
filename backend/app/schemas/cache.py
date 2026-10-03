"""Explicit JSON schemas for cached graph outputs (no pickle or executable state)."""

from pydantic import BaseModel, Field

from app.schemas.agent import AgentProductResult, AnalyzedUserInput, AnswerReview, AskResponse, DraftAnswer
from app.schemas.evaluation import NextQuestion, ProductResult
from app.schemas.user import UserProfile


class CalculatedTurn(BaseModel):
    product_results: list[AgentProductResult] = Field(default_factory=list)
    next_question: NextQuestion | None = None
    excluded_products: list[ProductResult] = Field(default_factory=list)


class CachedTurn(CalculatedTurn):
    response: AskResponse
    analysis: AnalyzedUserInput | None = None
    profile: UserProfile | None = None
    draft: DraftAnswer | None = None
    review: AnswerReview | None = None
    questions: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    retry_count: int = 0
    llm_error: str | None = None

    def graph_update(self):
        return {name: getattr(self, name) for name in type(self).model_fields}
