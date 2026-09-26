from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.agent.nodes import (
    analyze_input,
    calculate_products,
    fail,
    fallback,
    finalize,
    needs_input,
    prepare_retry,
    review_answer,
    route_after_review,
    route_after_validation,
    route_after_verification,
    validate_input,
    verify_answer,
    write_answer,
)
from app.agent.state import OnlineAgentState


def build_online_agent_graph(checkpointer=None):
    builder = StateGraph(OnlineAgentState)
    builder.add_node("analyze_input", analyze_input)
    builder.add_node("validate_input", validate_input)
    builder.add_node("calculate_products", calculate_products)
    builder.add_node("write_answer", write_answer)
    builder.add_node("verify_answer", verify_answer)
    builder.add_node("review_answer", review_answer)
    builder.add_node("prepare_retry", prepare_retry)
    builder.add_node("finalize", finalize)
    builder.add_node("fallback", fallback)
    builder.add_node("needs_input", needs_input)
    builder.add_node("fail", fail)

    builder.add_edge(START, "analyze_input")
    builder.add_edge("analyze_input", "validate_input")
    builder.add_conditional_edges(
        "validate_input",
        route_after_validation,
        {"calculate": "calculate_products", "needs_input": "needs_input", "fail": "fail"},
    )
    builder.add_edge("calculate_products", "write_answer")
    builder.add_edge("write_answer", "verify_answer")
    builder.add_conditional_edges(
        "verify_answer",
        route_after_verification,
        {"review": "review_answer", "retry": "prepare_retry", "fallback": "fallback"},
    )
    builder.add_conditional_edges(
        "review_answer",
        route_after_review,
        {"finalize": "finalize", "retry": "prepare_retry", "fallback": "fallback"},
    )
    builder.add_edge("prepare_retry", "write_answer")
    for node in ("finalize", "fallback", "needs_input", "fail"):
        builder.add_edge(node, END)
    return builder.compile(checkpointer=checkpointer)


online_agent_checkpointer = MemorySaver()
online_agent_graph = build_online_agent_graph(checkpointer=online_agent_checkpointer)
