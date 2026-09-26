from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import ask, evaluate, health
from app.core.config import settings


app = FastAPI(
    title="Savings Product Matching Agent",
    version="0.1.0",
    description="추출·검증은 배치로 미리 하고, 사용자 조건 판정과 이자 계산은 코드로 즉시 처리합니다.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health.router)
app.include_router(evaluate.router, prefix="/api/v1")
app.include_router(ask.router, prefix="/api/v1")
