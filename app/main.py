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
from app.api.v1.distribution import router as distribution_router
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
app.include_router(distribution_router, prefix="/api/v1", tags=["distribution"])
app.include_router(stats_router, prefix="/api/v1", tags=["stats"])


@app.get("/admin", include_in_schema=False)
async def admin_redirect():
    return RedirectResponse(url="/api/v1/admin/import")


@app.get("/health")
async def health_check():
    return {"status": "ok"}


# 정적 파일 서빙 (프론트엔드 빌드 결과물)
DIST_DIR = Path(__file__).parent.parent / "frontend" / "dist"


def _resolve_within(root: Path, relative: str) -> Path | None:
    """root 안에 실제로 존재하는 파일이면 그 절대경로를, 아니면 None 을 돌려준다.

    pathlib 의 `/` 는 `..` 를 접지 않고, 우변이 절대경로면 좌변을 통째로 버린다.
    `.is_file()` 은 그렇게 만들어진 경로를 OS 에 그대로 물어보므로 검사 없이
    쓰면 root 밖 임의 파일이 서빙된다. resolve() 로 `..` 와 심볼릭 링크를 모두
    편 뒤 root 안에 있는지 확인한다.
    """
    root_resolved = root.resolve()
    try:
        candidate = (root_resolved / relative).resolve()
    except (OSError, ValueError):  # 널 바이트, 경로 길이 초과 등
        return None
    if not candidate.is_relative_to(root_resolved):
        return None
    return candidate if candidate.is_file() else None


if DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        target = _resolve_within(DIST_DIR, full_path)
        if target is not None:
            return FileResponse(target)
        # 나머지는 전부 클라이언트 라우팅으로 넘긴다.
        return FileResponse(DIST_DIR / "index.html")
