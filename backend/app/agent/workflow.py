import atexit
import sqlite3
from enum import Enum
from pydantic import BaseModel
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from app.core.config import settings
from app.schemas import agent, graph, user, evaluation, requirements

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


def sqlite_checkpointer(path):
    """pickle 없이 프로젝트의 명시적 스키마만 역직렬화한다."""
    allowed = [cls for module in (agent, graph, user, evaluation, requirements)
               for cls in vars(module).values()
               if isinstance(cls, type) and issubclass(cls, (BaseModel, Enum)) and cls.__module__.startswith("app.schemas.")]
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    return SqliteSaver(conn, serde=JsonPlusSerializer(allowed_msgpack_modules=allowed, allowed_json_modules=[(c.__module__, c.__name__) for c in allowed]))


settings.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
online_agent_checkpointer = sqlite_checkpointer(settings.checkpoint_path)
atexit.register(online_agent_checkpointer.conn.close)
online_agent_graph = build_online_agent_graph(checkpointer=online_agent_checkpointer)
