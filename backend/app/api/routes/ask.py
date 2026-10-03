import sqlite3
from uuid import uuid4
from threading import RLock

from fastapi import APIRouter, Depends, HTTPException

from app.agent.workflow import online_agent_graph
from app.api.routes.evaluate import get_db
from app.db.queries import load_products
from app.schemas.agent import AskRequest, AskResponse
from app.schemas.cache import CachedTurn
from app.core.cache import cached, fingerprint
from app.core.config import settings


router = APIRouter(prefix="/ask", tags=["agent"])
_thread_locks = [RLock() for _ in range(64)]


@router.get("/{thread_id}", response_model=AskResponse)
def restore(thread_id: str) -> AskResponse:
    snapshot = online_agent_graph.get_state({"configurable": {"thread_id": thread_id}})
    response = snapshot.values.get("response")
    if response is None:
        raise HTTPException(status_code=404, detail="저장된 대화를 찾지 못했습니다.")
    return cached("restore", {"thread_id": thread_id, "checkpoint": snapshot.config}, AskResponse,
                  lambda: response, settings.cache_response_ttl)


@router.post("", response_model=AskResponse)
def ask(request: AskRequest, conn: sqlite3.Connection = Depends(get_db)) -> AskResponse:
    thread_id = request.thread_id or str(uuid4())
    # 같은 대화에 동시 요청이 오면 이전 턴의 완료를 기다린다 (단일 서버 프로세스).
    with _thread_locks[hash(thread_id) % len(_thread_locks)]:
        return _invoke(request, conn, thread_id)


def _invoke(request: AskRequest, conn: sqlite3.Connection, thread_id: str) -> AskResponse:
    config = {"configurable": {"thread_id": thread_id}}
    previous = online_agent_graph.get_state(config).values
    products = load_products(conn)
    history = previous.get("conversation_messages", []) + [request.message]
    state_input = {
            "thread_id": thread_id,
            "message": request.message,
            "conversation_messages": [request.message],
            "products": products,
            "retry_count": 0,
            "analysis": None, "profile": None, "product_results": [],
            "draft": None, "review": None, "questions": [], "errors": [],
            "next_question": None, "excluded_products": [], "llm_error": None,
        }
    computed = False

    def run():
        nonlocal computed
        computed = True
        return CachedTurn.model_validate(online_agent_graph.invoke(state_input, config=config))

    turn = cached("answer", {
        "history": history,
        "products": [p.model_dump(mode="json") for p in products],
        "model": settings.online_agent_model,
        "account": fingerprint(settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else ""),
    }, CachedTurn, run, settings.cache_response_ttl,
        cacheable=lambda value: value.response.status in ("completed", "needs_input")
        and not value.response.used_fallback and not value.response.verification_errors and not value.errors)

    if not computed:
        # Cached output is reusable, but the caller gets its own thread and checkpoint.
        turn.response = turn.response.model_copy(update={"thread_id": thread_id})
        terminal = "needs_input" if turn.response.status == "needs_input" else "finalize"
        online_agent_graph.update_state(config, {**state_input, **turn.graph_update()}, as_node=terminal)
    return turn.response
