"""
tests/test_spa_path_traversal.py
SPA 폴백 라우트가 frontend/dist 밖의 파일을 서빙하지 않는지 검증한다.

배경: 운영 서버(140.245.76.153:8000)가 인터넷에 열려 있던 동안
`GET /../../../../../../etc/hostname` 이 200 과 함께 실제 파일 내용을 반환했다.
자동화 스캐너가 이 경로로 ~/.claude/.credentials.json, ~/.codex/auth.json 등
AI CLI 자격증명을 반복 시도한 흔적이 uvicorn.log 에 남아 있다.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import DIST_DIR, _resolve_within, app


@pytest.fixture
def dist(tmp_path):
    """dist 와 그 바깥에 놓인 비밀 파일."""
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html>spa")
    (root / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("TOP SECRET")
    return root


def test_serves_a_file_inside_dist(dist):
    assert _resolve_within(dist, "assets/app.js") == (dist / "assets" / "app.js").resolve()


def test_rejects_parent_traversal(dist):
    assert _resolve_within(dist, "../secret.txt") is None
    assert _resolve_within(dist, "../../../../../../etc/hostname") is None


def test_rejects_absolute_path(dist):
    # pathlib 의 / 연산자는 우변이 절대경로면 좌변을 통째로 버린다.
    assert _resolve_within(dist, "/etc/hostname") is None


def test_rejects_symlink_escape(dist, tmp_path):
    link = dist / "escape.txt"
    try:
        link.symlink_to(tmp_path / "secret.txt")
    except (OSError, NotImplementedError):
        pytest.skip("심볼릭 링크를 만들 권한이 없다")
    assert _resolve_within(dist, "escape.txt") is None


def test_rejects_null_byte(dist):
    assert _resolve_within(dist, "index.html\x00.png") is None


def test_missing_path_falls_back(dist):
    # SPA 클라이언트 라우트. 파일이 아니므로 None → index.html 폴백.
    assert _resolve_within(dist, "some/spa/route") is None


@pytest.mark.skipif(not DIST_DIR.exists(), reason="frontend/dist 빌드 결과물이 없다")
def test_http_traversal_serves_index_not_the_real_file():
    """퍼센트 인코딩된 ../ 는 httpx 가 정규화하지 않으므로 실제 공격 경로에 가깝다."""
    client = TestClient(app)
    # frontend/dist 기준 ../../requirements.txt = 프로젝트 루트의 requirements.txt
    response = client.get("/%2e%2e%2f%2e%2e%2frequirements.txt")

    assert response.status_code == 200
    assert "fastapi" not in response.text, "dist 밖 파일이 그대로 노출됐다"
    assert "<!doctype html" in response.text.lower()
