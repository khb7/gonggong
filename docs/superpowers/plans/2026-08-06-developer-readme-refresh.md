# Developer README Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the minimal root README with an accurate developer onboarding guide for the current public-bidding analysis application.

**Architecture:** Keep the README as the single developer entry point. Derive every feature, route, command, and configuration note from the implemented FastAPI service, React application, package configuration, and tests; link readers to FastAPI OpenAPI for complete request and response schemas.

**Tech Stack:** Python, FastAPI, SQLAlchemy, Alembic, SQLite/PostgreSQL, React, TypeScript, Vite, pytest, Vitest.

## Global Constraints

- Modify only `README.md`; do not change application behavior or configuration.
- Use Korean for explanatory prose and preserve commands exactly as runnable shell snippets.
- Describe implemented behavior only; do not claim fixed data counts, accuracy, or planned features.
- Never place credentials, API keys, account details, or private-key material in the README.
- Explain that a blank `G2B_API_KEY` enables the mock G2B fetcher.

---

### Task 1: Replace the root README with the developer guide

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: `requirements.txt`, `.env.example`, `app/main.py`, `app/api/v1/*.py`, `frontend/package.json`, `frontend/src/App.tsx`, and the ETL scripts under `scripts/`.
- Produces: A self-contained developer onboarding document with runnable setup and verification instructions.

- [ ] **Step 1: Write the README outline**

Replace the current two-line content with these top-level sections, in this order:

```markdown
# 공공입찰 통계 엔진

## 프로젝트 개요
## 주요 기능
## 기술 구성
## 빠른 시작
## API 및 화면
## 데이터 흐름
## 테스트와 품질 확인
## 운영 시 유의사항
```

- [ ] **Step 2: Add code-verified project and architecture content**

Document the FastAPI backend, React/Vite frontend, Alembic migrations, `app/`, `frontend/`, `scripts/`, `tests/`, and `data/` directory roles. Describe the following implemented areas without performance claims: bid calculation, offset distribution, statistics pages, CSV import, ETL, and optional data collection scheduling.

- [ ] **Step 3: Add the local setup and run commands**

Include exact command blocks for virtual environment creation, `pip install -r requirements.txt`, `.env` creation from `.env.example`, `alembic upgrade head`, backend startup, frontend dependency installation, and `npm run dev` in `frontend/`. State that PostgreSQL is the default `DATABASE_URL` and that SQLite is supported through SQLAlchemy configuration when an appropriate URL is supplied.

- [ ] **Step 4: Add API, UI, and data-flow references**

Use a compact table covering `/health`, `POST /api/v1/bid/calculate`, `POST /api/v1/bid/distribution`, `/api/v1/stats/*`, and `/api/v1/admin/*`. List the implemented frontend paths `/`, `/bid-distribution`, `/overview`, `/clients`, `/distribution`, and `/collection`. Explain the CSV/Info21c collection → ETL → database → API/UI path and name the relevant `scripts/` entry points without documenting login details.

- [ ] **Step 5: Add test and limitation guidance**

Provide the exact verification commands below and explain that the backend API provides full interactive schema documentation at `/docs` when running:

```bash
pytest

cd frontend
npm run lint
npm test
npm run build
```

State the mock-data behavior, the need for a real database and G2B key for live collection, and that analytical output is decision support rather than a guarantee of award or price prediction.

- [ ] **Step 6: Verify the completed document**

Run these checks and fix every failure before committing:

```bash
rg -n "TODO|TBD|nw8856|G2B_API_KEY=.*[^e]" README.md
git diff --check -- README.md
pytest
```

Expected: no placeholder or credential matches in the README, no whitespace errors, and the Python test suite passes.

- [ ] **Step 7: Commit the documentation update**

```bash
git add README.md
git commit -m "docs: refresh developer README"
```
