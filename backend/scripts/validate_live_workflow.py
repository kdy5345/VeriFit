"""실제 상품 DB 복사본과 Gemini로 온라인 그래프를 검증한다 (API 비용 발생)."""
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from uuid import uuid4

from app.agent.workflow import build_online_agent_graph, sqlite_checkpointer
from app.core.config import settings
from app.db.queries import load_products
from app.db.store import connect


def main():
    settings.cache_enabled = False  # This script verifies actual model calls.
    # 기존 상품 DB·대화 기록은 변경하지 않는다.
    with TemporaryDirectory(prefix="verifit-live-") as temp:
        copied = Path(temp) / "products.db"
        with sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True) as source, sqlite3.connect(copied) as target:
            source.backup(target)
        conn = connect(copied)
        products = load_products(conn)
        conn.close()
        saver = sqlite_checkpointer(Path(temp) / "checkpoints.sqlite")
        graph = build_online_agent_graph(saver)
        thread_id = str(uuid4())
        summaries = []
        for message in ["월 30만 원씩 1년 넣고 싶어요. 급여이체는 월 50만 원으로 6개월 유지할 수 있어요. 카드는 안 써요.",
                        "월 납입액만 50만 원으로 바꿔줘."]:
            state = graph.invoke({"thread_id": thread_id, "message": message, "conversation_messages": [message],
                "products": products, "retry_count": 0, "analysis": None, "profile": None, "product_results": [],
                "draft": None, "review": None, "errors": [], "questions": [], "next_question": None, "excluded_products": []},
                {"configurable": {"thread_id": thread_id}})
            result = state["response"]
            summaries.append({"status": result.status, "products": len(result.products), "excluded": len(result.excluded_products),
                "used_fallback": result.used_fallback, "retry_count": result.retry_count,
                "monthly_deposit_won": result.extracted_profile.monthly_deposit_won if result.extracted_profile else None,
                "next_question": result.next_question.code if result.next_question else None, "verification_errors": result.verification_errors})
        saver.conn.close()
        print(json.dumps({"model": settings.online_agent_model, "product_count": len(products), "turns": summaries}, ensure_ascii=False, indent=2))
        if any(s["status"] != "completed" for s in summaries) or [s["monthly_deposit_won"] for s in summaries] != [300000, 500000]:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
