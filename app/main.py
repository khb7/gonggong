"""
app/main.py
FastAPI 앱 진입점
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.bidding import router as bidding_router
from app.api.v1.stats import router as stats_router

app = FastAPI(
    title="공공입찰 통계 엔진",
    description="나라장터 입찰 데이터 기반 사정률 예측 및 투찰가 계산 API",
    version="0.1.0",
)

# React 개발 서버(localhost:5173 등) 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://localhost:8080"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(bidding_router, prefix="/api/v1", tags=["bidding"])
app.include_router(stats_router, prefix="/api/v1", tags=["stats"])


@app.get("/health")
async def health_check():
    return {"status": "ok"}
