import operator
from typing import Annotated, TypedDict

from app.schemas.agent import (
    AgentProductResult,
    AnalyzedUserInput,
    AnswerReview,
    AskResponse,
    DraftAnswer,
)
from app.schemas.graph import Product
from app.schemas.user import UserProfile
from app.schemas.evaluation import NextQuestion, ProductResult


class OnlineAgentState(TypedDict, total=False):
    thread_id: str
    message: str
    # 같은 thread_id의 후속 요청마다 새 메시지가 append된다. Analyzer는 누적된 대화를
    # 하나의 사용자 문맥으로 읽고, 첫 요청에서 빠졌던 금액·기간을 다음 답에서 보완한다.
    conversation_messages: Annotated[list[str], operator.add]
    products: list[Product]

    analysis: AnalyzedUserInput | None
    profile: UserProfile | None
    product_results: list[AgentProductResult]
    next_question: NextQuestion | None
    excluded_products: list[ProductResult]
    draft: DraftAnswer | None
    review: AnswerReview | None

    questions: list[str]
    errors: list[str]
    retry_count: int
    llm_error: str | None
    response: AskResponse
