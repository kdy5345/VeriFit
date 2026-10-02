import sqlite3
from collections.abc import Generator

from fastapi import APIRouter, Depends

from app.core.config import settings
from app.db.queries import load_products
from app.db.store import connect
from app.schemas.evaluation import EvaluateResponse, ScenarioRequest, ScenarioResponse
from app.schemas.user import UserProfile
from app.services.evaluation import compare_scenarios, evaluate_products


router = APIRouter(tags=["evaluate"])


def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = connect(settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


@router.post("/evaluate", response_model=EvaluateResponse)
def evaluate(profile: UserProfile, conn: sqlite3.Connection = Depends(get_db)) -> EvaluateResponse:
    return evaluate_products(load_products(conn), profile)


@router.post("/scenarios", response_model=ScenarioResponse)
def scenarios(request: ScenarioRequest, conn: sqlite3.Connection = Depends(get_db)) -> ScenarioResponse:
    return compare_scenarios(load_products(conn), request)
