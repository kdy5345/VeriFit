from langgraph.graph import END, START, StateGraph

from app.graph.nodes import (
    extract,
    finalize,
    prepare_retry,
    review,
    route_after_review,
    route_after_verify,
    verify,
)
from app.graph.state import ExtractionState


def build_extraction_graph():
    """상품 1개를 구조화하는 그래프.

    extract -> verify(코드: 근거대조+도달가능성)
        -> 문제 있고 재시도 예산 있음: prepare_retry -> extract 재진입
        -> 그 외: review(Reviewer LLM, 코드검증 통과한 term만 대상)
            -> 지적 있고 재시도 예산 있음: prepare_retry -> extract 재진입
            -> 그 외: finalize

    재시도는 상품 전체에 최대 1번. 코드 검증 실패와 Reviewer 지적이 같은
    retry_count 예산을 공유한다. finalize는 term(만기) 단위로 accept/exclude를
    가른다 — 같은 상품이라도 12개월은 통과하고 24개월은 제외될 수 있다.
    """
    builder = StateGraph(ExtractionState)
    builder.add_node("extract", extract)
    builder.add_node("verify", verify)
    builder.add_node("review", review)
    builder.add_node("prepare_retry", prepare_retry)
    builder.add_node("finalize", finalize)

    builder.add_edge(START, "extract")
    builder.add_edge("extract", "verify")
    builder.add_conditional_edges(
        "verify", route_after_verify, {"retry": "prepare_retry", "review": "review"}
    )
    builder.add_conditional_edges(
        "review", route_after_review, {"retry": "prepare_retry", "finalize": "finalize"}
    )
    builder.add_edge("prepare_retry", "extract")
    builder.add_edge("finalize", END)
    return builder.compile()


extraction_graph = build_extraction_graph()
