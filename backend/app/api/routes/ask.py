import sqlite3
from uuid import uuid4

from fastapi import APIRouter, Depends

from app.agent.workflow import online_agent_graph
from app.api.routes.evaluate import get_db
from app.db.queries import load_products
from app.schemas.agent import AskRequest, AskResponse


router = APIRouter(prefix="/ask", tags=["agent"])


@router.post("", response_model=AskResponse)
def ask(request: AskRequest, conn: sqlite3.Connection = Depends(get_db)) -> AskResponse:
    thread_id = request.thread_id or str(uuid4())
    result = online_agent_graph.invoke(
        {
            "thread_id": thread_id,
            "message": request.message,
            "conversation_messages": [request.message],
            "products": load_products(conn),
            "retry_count": 0,
        },
        config={"configurable": {"thread_id": thread_id}},
    )
    return result["response"]
