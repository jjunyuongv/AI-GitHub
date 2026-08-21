"""설정과 그 예시 파일이 어긋나지 않는가.

`.env.example` 은 사람이 손으로 갱신하는 문서라 **조용히 낡는다.** 실제로 그렇게 됐다 —
작성 시점에는 9개가 일치했는데, 그 뒤 추가된 `FULL_INJECTION_*` 두 개가 빠진 채로 남아
있었다. 예시에 없는 설정은 아무도 존재를 모르고, 예시에만 있는 설정은 오타이거나
이미 지워진 것이다. 둘 다 오류를 내지 않고 문서만 틀리게 만든다.
"""

import re
from pathlib import Path

BACK_DIR = Path(__file__).resolve().parents[1]

# config.py 가 읽는 키. 한 줄짜리와 여러 줄로 감싼 형태를 모두 잡는다.
#   os.environ.get("NAME", ...)  /  os.environ.get(\n    "NAME",\n ...)
ENV_GET = re.compile(r'os\.environ\.get\(\s*"([A-Z_0-9]+)"')

# .env.example 의 키. 주석(#) 안에 예시로 적힌 것은 세지 않는다.
ENV_LINE = re.compile(r"^([A-Z_0-9]+)=", re.MULTILINE)


def _config_keys() -> set[str]:
    return set(ENV_GET.findall((BACK_DIR / "app" / "config.py").read_text(encoding="utf-8")))


def _example_keys() -> set[str]:
    return set(ENV_LINE.findall((BACK_DIR / ".env.example").read_text(encoding="utf-8")))


def test_every_setting_is_documented():
    """config.py 가 읽는 환경변수는 모두 .env.example 에 있어야 한다."""
    missing = _config_keys() - _example_keys()
    assert not missing, (
        f".env.example 에 빠진 설정: {sorted(missing)}."
        " 기본값과 한 줄 설명을 함께 적을 것"
    )


def test_example_has_no_unknown_keys():
    """.env.example 에만 있는 키는 오타이거나 이미 지워진 설정이다."""
    unknown = _example_keys() - _config_keys()
    assert not unknown, (
        f"config.py 가 읽지 않는 키가 .env.example 에 있다: {sorted(unknown)}."
        " 이름이 틀렸거나 코드에서 제거된 설정이다"
    )


def test_key_extraction_actually_works():
    """두 정규식이 아무것도 못 잡아도 위 테스트는 통과한다 — 그 허위 통과를 막는다."""
    assert len(_config_keys()) > 10
    assert len(_example_keys()) > 10
