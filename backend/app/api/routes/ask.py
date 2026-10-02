import sqlite3
from uuid import uuid4
from threading import RLock

from fastapi import APIRouter, Depends, HTTPException

from app.agent.workflow import online_agent_graph
from app.api.routes.evaluate import get_db
from app.db.queries import load_products
from app.schemas.agent import AskRequest, AskResponse


router = APIRouter(prefix="/ask", tags=["agent"])
_thread_locks = [RLock() for _ in range(64)]


@router.get("/{thread_id}", response_model=AskResponse)
def restore(thread_id: str) -> AskResponse:
    snapshot = online_agent_graph.get_state({"configurable": {"thread_id": thread_id}})
    response = snapshot.values.get("response")
    if response is None:
        raise HTTPException(status_code=404, detail="저장된 대화를 찾지 못했습니다.")
    return response


@router.post("", response_model=AskResponse)
def ask(request: AskRequest, conn: sqlite3.Connection = Depends(get_db)) -> AskResponse:
    thread_id = request.thread_id or str(uuid4())
    # 같은 대화에 동시 요청이 오면 이전 턴의 완료를 기다린다 (단일 서버 프로세스).
    with _thread_locks[hash(thread_id) % len(_thread_locks)]:
        return _invoke(request, conn, thread_id)


def _invoke(request: AskRequest, conn: sqlite3.Connection, thread_id: str) -> AskResponse:
    result = online_agent_graph.invoke(
        {
            "thread_id": thread_id,
            "message": request.message,
            "conversation_messages": [request.message],
            "products": load_products(conn),
            "retry_count": 0,
            "analysis": None, "profile": None, "product_results": [],
            "draft": None, "review": None, "questions": [], "errors": [],
            "next_question": None, "excluded_products": [], "llm_error": None,
        },
        config={"configurable": {"thread_id": thread_id}},
    )
    return result["response"]
