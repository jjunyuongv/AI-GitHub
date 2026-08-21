"""Java 정적분석기(PMD)를 내려받는다. 이미 있으면 아무것도 하지 않는다.

    python scripts/install_pmd.py

**pip 나 npm 으로는 못 받는다.** PMD 는 배포판 zip(약 70MB)이고 JVM 위에서 돈다.
그래서 ruff·oxlint 와 달리 설치 절차가 하나 더 필요하다.

**받는 곳은 `cache/tools/`** — 임베딩 모델(`cache/models/`)과 같은 성격이라 같은 자리에 둔다.
`Back/cache/` 는 이미 .gitignore 대상이다.

**버전을 고정한다.** 최신을 따라가면 룰셋 내용이 바뀌어 요약이 조용히 달라진다
(ruff·oxlint 규칙을 명시적으로 못박은 것과 같은 이유다).
"""

import io
import sys
import urllib.request
import zipfile
from pathlib import Path

PMD_VERSION = "7.26.0"
PMD_URL = (
    f"https://github.com/pmd/pmd/releases/download/pmd_releases%2F{PMD_VERSION}"
    f"/pmd-dist-{PMD_VERSION}-bin.zip"
)

TOOLS_DIR = Path(__file__).resolve().parents[1] / "cache" / "tools"
TARGET = TOOLS_DIR / f"pmd-bin-{PMD_VERSION}"


def main() -> int:
    if TARGET.exists():
        print(f"이미 있습니다: {TARGET}")
        return 0

    print(f"내려받는 중 ({PMD_VERSION}, 약 70MB)...")
    try:
        with urllib.request.urlopen(PMD_URL, timeout=300) as resp:
            data = resp.read()
    except OSError as e:
        print(f"내려받기 실패: {e}", file=sys.stderr)
        print("서비스는 PMD 없이도 돕니다 — Java 정적분석만 빠집니다.", file=sys.stderr)
        return 1

    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        archive.extractall(TOOLS_DIR)

    # POSIX 에서는 실행 비트가 필요하다 (zip 이 보존하지 않는 경우가 있다).
    launcher = TARGET / "bin" / "pmd"
    if launcher.exists():
        launcher.chmod(0o755)

    print(f"설치 완료: {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
