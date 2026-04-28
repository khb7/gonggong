"""
app/main.py
FastAPI 앱 진입점
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.admin import router as admin_router
from app.api.v1.bidding import router as bidding_router
from app.api.v1.stats import router as stats_router
from app.jobs.scheduler import scheduler, setup_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_scheduler()
    scheduler.start()
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="공공입찰 통계 엔진",
    description="나라장터 입찰 데이터 기반 사정률 예측 및 투찰가 계산 API",
    version="0.1.0",
    lifespan=lifespan,
)

# React 개발 서버(localhost:5173 등) 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://localhost:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin_router, prefix="/api/v1", tags=["admin"])
app.include_router(bidding_router, prefix="/api/v1", tags=["bidding"])
app.include_router(stats_router, prefix="/api/v1", tags=["stats"])


@app.get("/admin", include_in_schema=False)
async def admin_redirect():
    return RedirectResponse(url="/api/v1/admin/import")


@app.get("/health")
async def health_check():
    return {"status": "ok"}


# 정적 파일 서빙 (프론트엔드 빌드 결과물)
DIST_DIR = Path(__file__).parent.parent / "frontend" / "dist"
if DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        file_path = DIST_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(DIST_DIR / "index.html")
