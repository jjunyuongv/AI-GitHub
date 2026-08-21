import time
from pathlib import Path

import anthropic
import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from app.core.chunk_rule import rule_version
from app.db import index_status, pool
from app.db import repos as repo_db
from app.db.pool import DB_ERRORS
from app.schemas.schemas import (
    RebuildRequest,
    ResummarizeRequest,
    RollbackRequest,
    RunRequest,
    RunResult,
)
from app import config as app_config
from app.services import (
    cleanup,
    index_queue,
    rate_limit,
    run_log,
    search_eval_log,
    summary_cache,
    usage_stats,
)
from app.services.claude_client import (
    DEFAULT_EFFORT,
    DEFAULT_MODEL,
    EFFORT_LEVELS,
    MODELS,
    SYSTEM_PROMPT,
    MissingAPIKeyError,
    run_summary,
)
from app.services.context_builder import build_context
from app.services.github_client import (
    RepoAccessError,
    check_repo_access,
    fetch_rate_limit,
    fetch_repo_context,
    parse_github_url,
)

router = APIRouter(prefix="/admin")
root_router = APIRouter()

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"


def _page(name: str) -> HTMLResponse:
    return HTMLResponse((TEMPLATES / name).read_text(encoding="utf-8"))


@root_router.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/admin")


# ── 페이지 ────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
def home_page():
    return _page("admin_home.html")


@router.get("/lab", response_class=HTMLResponse)
def lab_page():
    return _page("admin_lab.html")


@router.get("/runs", response_class=HTMLResponse)
def runs_page():
    return _page("admin_runs.html")


@router.get("/usage", response_class=HTMLResponse)
def usage_page():
    return _page("admin_usage.html")


@router.get("/search", response_class=HTMLResponse)
def search_page():
    return _page("admin_search.html")


@router.get("/snapshots", response_class=HTMLResponse)
def snapshots_page():
    return _page("admin_snapshots.html")


@router.get("/admin.css", include_in_schema=False)
def stylesheet():
    return Response(
        (TEMPLATES / "admin.css").read_text(encoding="utf-8"), media_type="text/css"
    )


# ── API ───────────────────────────────────────────────────

@router.get("/api/config")
def config():
    return {
        "models": [{"id": m, "effort": v["effort"]} for m, v in MODELS.items()],
        "effort_levels": EFFORT_LEVELS,
        "default_model": DEFAULT_MODEL,
        "default_effort": DEFAULT_EFFORT,
        "default_prompt": SYSTEM_PROMPT,
    }


@router.get("/api/runs")
def runs(limit: int = 100):
    return run_log.read(limit)


@router.get("/api/search-evals")
def search_evals(limit: int = 50):
    """코드 검색 품질 측정 기록.

    latest 는 모델(+테이블)마다 가장 최근 것만 골라 둔 것이고 비교 표의 재료다.
    history 는 같은 모델을 여러 번 잰 이력까지 포함한다.
    측정은 `pytest -m evaluation` 이 수행하며, 이 API 는 읽기만 한다.
    """
    return {
        "latest": search_eval_log.latest_per_model(limit),
        "history": search_eval_log.read(limit),
        "current": {
            "model": app_config.EMBEDDING_MODEL,
            "dim": app_config.EMBEDDING_DIM,
            "table": app_config.CHUNK_TABLE,
            "query_prefix": app_config.EMBEDDING_QUERY_PREFIX,
            "passage_prefix": app_config.EMBEDDING_PASSAGE_PREFIX,
        },
    }


@router.get("/api/usage")
def usage(days: int = 7):
    # today는 남용 방지 카운터라 /analyze만 센다. 실험실 호출은 포함되지 않는다.
    return {**usage_stats.build_report(days), "today": rate_limit.today_usage()}


@router.get("/api/github")
def github():
    try:
        return fetch_rate_limit()
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502, detail=f"GitHub API 오류 ({e.response.status_code})."
        )


def _require_db() -> None:
    if not pool.is_enabled():
        raise HTTPException(
            status_code=503, detail="DATABASE_URL 이 설정되지 않아 조회할 수 없습니다."
        )


@router.get("/api/snapshots")
def snapshots():
    """스냅샷별 색인 상태 + 어떤 청킹 규칙으로 만들었는지.

    **읽기 전용이다.** 낡은 색인을 여기서 다시 만들지 않는다 — 큰 저장소는 임베딩만
    수십 분이라, 화면을 여는 것이 곧 수십 분짜리 작업을 시작하는 일이 되면 안 된다.
    """
    _require_db()
    current = rule_version()
    active = app_config.CHUNK_TABLE
    rows = index_status.list_all()
    for row in rows:
        # **지금 쓰는 테이블만 '낡음'을 따진다.** 차원이 다른 옛 테이블은 아무도 읽지
        # 않으므로 규칙이 달라도 고칠 이유가 없다 — 신호에 섞이면 진짜 대상이 묻힌다.
        row["in_use"] = row["table_name"] == active
        row["stale"] = row["in_use"] and row["chunk_rule"] != current
    return {
        "current_rule": current,
        "chunk_table": active,
        "snapshots": rows,
        "stale_count": sum(1 for row in rows if row["stale"]),
    }


@router.post("/api/rebuild-index")
def rebuild_index(req: RebuildRequest):
    """청크만 다시 만든다. **LLM 을 부르지 않아 과금이 없다.**

    요약을 다시 만드는 것은 /api/resummarize 다. 둘을 한 엔드포인트로 합치지 않는 이유는
    과금 여부와 응답 형태(동기 200 vs 비동기 202)가 갈리기 때문이다 — 파라미터 하나로
    과금이 생겼다 없어졌다 하면 사고가 난다.

    큐에 넣고 즉시 돌아온다. 진행은 /api/builds 로 확인한다.
    """
    _require_db()
    try:
        target = repo_db.get_snapshot_repo(req.snapshot_id)
    except DB_ERRORS as e:
        raise HTTPException(status_code=503, detail=f"DB 오류: {e}")
    if target is None:
        raise HTTPException(
            status_code=404, detail=f"스냅샷 {req.snapshot_id} 을 찾을 수 없습니다."
        )

    build_id = index_queue.submit(
        req.snapshot_id, target["owner"], target["name"], table=req.table
    )
    if build_id is None:
        raise HTTPException(
            status_code=409, detail="이미 이 스냅샷의 색인을 만드는 중입니다."
        )
    return JSONResponse(
        status_code=202,
        content={
            "build_id": build_id,
            "snapshot_id": req.snapshot_id,
            "queued": index_queue.pending_count(),
        },
    )


@router.get("/api/builds")
def builds(snapshot_id: int, table: str | None = None, limit: int = 20):
    """이 스냅샷의 색인 빌드 이력. 롤백할 대상을 고를 때 쓴다."""
    _require_db()
    return {
        "snapshot_id": snapshot_id,
        "current_rule": rule_version(),
        "builds": index_status.list_builds(snapshot_id, table=table, limit=limit),
    }


@router.post("/api/rollback-index")
def rollback_index(req: RollbackRequest):
    """검색이 보는 빌드를 지정한 빌드로 되돌린다.

    청크는 보관 정책이 지우기 전까지 남아 있으므로, 새 색인이 나쁘면 즉시 되돌릴 수 있다.
    완료된 빌드만 가리킬 수 있다 — 진행 중인 빌드를 가리키면 절반만 임베딩된 코드로
    검색하게 된다.
    """
    _require_db()
    if not index_status.activate(req.snapshot_id, req.build_id, table=req.table):
        raise HTTPException(
            status_code=400,
            detail="그 빌드로 되돌릴 수 없습니다 (없거나, 다른 스냅샷이거나, 완료되지 않았습니다).",
        )
    return {"snapshot_id": req.snapshot_id, "active_build_id": req.build_id}


@router.post("/api/cleanup")
def cleanup_storage(apply: bool = False):
    """쌓인 것들을 정리한다. **기본은 dry-run** — apply=true 일 때만 실제로 지운다.

    지우는 것은 되돌릴 수 없으므로 무엇이 지워질지 먼저 보여준다.
    """
    _require_db()
    return cleanup.run(apply=apply)


def _summarize(
    *, github_url: str, model: str, effort: str, system_prompt: str, source: str
) -> tuple[dict, str, dict]:
    """파싱 → 접근 확인 → fetch → 요약 → 기록. (access, context, 기록된 레코드) 반환.

    관리자 경로(실험실·재인덱싱) 공용이다. 둘 다 캐시를 조회하지 않고 항상 LLM을 호출하며,
    남용 제한도 걸지 않는다 (관리자가 실험하다 공개 서비스를 막으면 안 된다).
    """
    try:
        owner, repo = parse_github_url(github_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    started = time.perf_counter()
    try:
        # LLM 호출 전에 접근 불가·빈 저장소를 먼저 걸러낸다.
        access = check_repo_access(owner, repo)
        ctx = fetch_repo_context(owner, repo, access=access)
    except RepoAccessError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=f"GitHub API 오류 ({e.response.status_code}). 잠시 후 다시 시도하세요.",
        )
    fetch_ms = int((time.perf_counter() - started) * 1000)

    context = build_context(ctx)
    try:
        result = run_summary(context, model=model, effort=effort, system=system_prompt)
    except MissingAPIKeyError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except anthropic.APIError as e:
        raise HTTPException(status_code=502, detail=f"Claude API 오류: {e}")

    record = run_log.append_run(
        source=source,
        repo=f"{owner}/{repo}",
        model=model,
        effort=effort if MODELS.get(model, {}).get("effort") else None,
        fetch_ms=fetch_ms,
        context=context,
        system_prompt=system_prompt,
        result=result,
    )
    return access, context, record


@router.post("/api/run", response_model=RunResult)
def run(req: RunRequest):
    _, _, record = _summarize(
        github_url=req.github_url,
        model=req.model,
        effort=req.effort,
        system_prompt=req.system_prompt or SYSTEM_PROMPT,
        source="lab",
    )
    return record


@router.post("/api/resummarize", response_model=RunResult)
def resummarize(req: ResummarizeRequest):
    """**요약만** 다시 만든다. LLM 을 호출하므로 과금된다.

    pushed_at 이 안 바뀌었는데도 요약을 갱신하고 싶을 때 쓴다 (프롬프트나
    컨텍스트 조립 로직을 고친 경우). 캐시 조회를 건너뛰므로 항상 LLM을 호출한다.

    **청크는 손대지 않는다.** 이름이 reindex 였을 때는 그 점이 함정이었다 —
    "재인덱싱"으로 읽히지만 실제로는 요약만 새로 만들고 코드 색인은 그대로였다.
    청크를 다시 만드는 것은 /api/rebuild-index 다(무과금·비동기).
    """
    # LLM을 부르기 전에 막는다. 나중에 저장에 실패하면 토큰만 버리는 셈이 된다.
    if not pool.is_enabled():
        raise HTTPException(
            status_code=503,
            detail="DATABASE_URL 이 설정되지 않아 스냅샷을 저장할 수 없습니다.",
        )

    model = req.model or DEFAULT_MODEL
    access, context, record = _summarize(
        github_url=req.github_url,
        model=model,
        effort=req.effort or DEFAULT_EFFORT,
        system_prompt=SYSTEM_PROMPT,
        source="resummarize",
    )

    # 같은 version 이면 기존 행을 덮어쓴다 (스냅샷 id 가 유지되므로 진행 중 대화가 끊기지 않는다).
    if summary_cache.put(access, model=model, summary=record["summary"], context=context) is None:
        raise HTTPException(
            status_code=502,
            detail="요약은 만들었지만 스냅샷 저장에 실패했습니다. 서버 로그를 확인하세요.",
        )
    return record
