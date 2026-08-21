"""분석 요약 캐시. 같은 저장소를 다시 분석할 때 LLM 호출을 건너뛴다.

저장은 PostgreSQL 의 repo_snapshots 다. 요약과 함께 build_context() 원문도 같은 행에
넣어 두고, 후속 질문(/chat)이 GitHub 을 다시 읽지 않고 그 원문을 재사용한다.

DB 조회·저장이 실패해도 캐시가 없는 것처럼 진행한다. 캐시 때문에 분석 자체가
막히면 안 되므로 예외를 올리지 않고 경고만 남긴다 (DB 가 꺼져 있을 때도 같다).
"""

import logging
import re
from datetime import datetime, timezone

from app.db import repos as repo_db
from app.db.pool import DB_ERRORS

# 키를 무엇으로 만들었는지 스냅샷 행에 남긴다.
# 나중에 커밋 SHA로 바꾸면 이 값이 달라져 옛 행과 섞이지 않는다.
KEY_SOURCE = "pushed_at"

logger = logging.getLogger(__name__)


def _owner_name(access: dict) -> tuple[str, str]:
    """정식 표기를 소문자화한 저장소 키.

    입력이 facebook/react 라도 실제 저장소가 react/react 로 이전됐다면 후자를 쓴다.
    입력 URL을 그대로 쓰면 같은 저장소가 옛 이름/새 이름으로 갈린다.
    """
    return access["owner"].lower(), access["name"].lower()


def _repo_key(access: dict) -> str:
    return "/".join(_owner_name(access))


def _version(access: dict) -> str:
    """pushed_at(ISO 8601)을 키에 넣기 안전한 숫자 문자열로 바꾼다.

    타임존 표기가 달라도 같은 시각이면 같은 키가 나오도록 UTC로 맞춘 뒤
    숫자만 남긴다. 2026-08-14T09:12:33Z → 20260814091233
    """
    raw = access.get("pushed_at") or ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        # 형식이 예상과 다르면 숫자만 남겨서라도 키를 만든다.
        return re.sub(r"\D", "", raw)
    return parsed.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")


def build_key(access: dict) -> str:
    """check_repo_access() 결과로 캐시 키를 만든다.

    저장소가 갱신되면 pushed_at이 바뀌므로 키도 바뀌고, 그때만 요약이 다시 생성된다.
    스냅샷 행에는 이 키가 (repo, key_source, version) 세 열로 나뉘어 들어간다.
    """
    return f"{_repo_key(access)}@{KEY_SOURCE}:{_version(access)}"


def get(access: dict) -> dict | None:
    """캐시된 스냅샷. 없거나 DB를 읽지 못하면 None.

    반환 dict에는 요약을 만든 model, 요약 본문, 대화용 context, 스냅샷 id가 들어 있다.
    """
    owner, name = _owner_name(access)
    try:
        return repo_db.get_snapshot(
            owner=owner, name=name, key_source=KEY_SOURCE, version=_version(access)
        )
    except DB_ERRORS as e:
        logger.warning("캐시를 읽지 못해 무시합니다 (%s): %s", build_key(access), e)
        return None


def put(access: dict, *, model: str, summary: str, context: str) -> dict | None:
    """스냅샷을 저장하고 그 행을 돌려준다. 저장하지 못하면 None.

    호출부는 반환된 id로 대화 세션을 만든다. None이면 요약은 그대로 응답하고
    대화만 시작할 수 없다.
    """
    owner, name = _owner_name(access)
    try:
        return repo_db.put_snapshot(
            owner=owner,
            name=name,
            display_owner=access["owner"],
            display_name=access["name"],
            key_source=KEY_SOURCE,
            version=_version(access),
            context=context,
            summary=summary,
            model=model,
        )
    except DB_ERRORS as e:
        logger.warning("캐시를 쓰지 못했습니다 (%s): %s", build_key(access), e)
        return None
