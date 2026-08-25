# RepoDive 백엔드 이미지.
#
#   docker build -f Back/Dockerfile -t repodive-back .     ← 컨텍스트는 **저장소 루트**
#   docker run --env-file Back/.env -p 8000:8000 repodive-back
#
# **런타임이 셋이다.** 정적분석기가 셋이고 각각 다른 런타임 위에서 돈다:
#   ruff    pip
#   oxlint  Node (npm 이 플랫폼 바이너리를 받는다) · stylelint 도 같은 package.json
#   PMD     JVM (배포판 zip. pip·npm 에 없어 scripts/install_pmd.py 로 받는다)
#
# **.env 는 굽지 않는다.** API 키가 이미지에 박힌다. 런타임 환경변수로 준다.
# 다만 임베딩 설정 7개는 아래에서 ENV 로 박는다 — 그 값으로 모델을 구웠기 때문에
# 런타임이 다른 값으로 돌면 이미지에 있는 가중치를 안 쓰고 다시 받는다.

FROM python:3.12-slim-bookworm

# JVM 은 PMD 전용이라 headless JRE 로 충분하다 (JDK 는 컴파일러까지 들어와 더 크다).
#
# **libgomp1 은 넣지 않는다.** slim 에 없어서 넣었다가 뺐다 — site-packages 의 `.so` 를
# 전부 `ldd` 로 훑어 libgomp 를 링크하는 것이 하나도 없음을 확인했다(onnxruntime 포함).
# 다른 파이썬 패키지를 넣다가 OpenMP 링크가 생기면 그때 추가할 것.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      openjdk-17-jre-headless \
      ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Node 는 apt 가 아니라 공식 이미지에서 가져온다 — bookworm 의 nodejs 는 18.20.4 인데
# package.json 의 두 도구가 그보다 높은 버전을 요구한다
# (실측: stylelint `>=20.19.0`, oxlint `^20.19.0 || >=22.12.0`).
COPY --from=node:22-bookworm-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 앱 루트. **`Back/` 이 여기로 온다** — 코드가 경로를 이 배치로 계산한다:
#   node_modules/.bin  ← static_analysis.NODE_BIN   (app 의 부모)
#   cache/tools        ← static_analysis.PMD_HOME
#   cache/models       ← config.EMBEDDING_CACHE_DIR
WORKDIR /app

# ─────────────────────────────────────────────────────────────────────────
# 무거운 것부터. **전부 코드 COPY 보다 앞이다** — 뒤에 두면 코드를 한 줄 고칠
# 때마다 모델 650MB 와 PMD 78MB 를 다시 받는다.
# ─────────────────────────────────────────────────────────────────────────

COPY Back/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY Back/package.json Back/package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund && npm cache clean --force

# PMD 7.26.0. 버전은 스크립트가 고정한다 (최신을 따라가면 룰셋이 바뀌어 요약이 달라진다).
COPY Back/scripts/install_pmd.py ./scripts/
RUN python scripts/install_pmd.py

# ─────────────────────────────────────────────────────────────────────────
# **여기서부터 비-root 다.** 린터 셋은 남의 코드를 실행하지 않는 것들로 골랐지만
# (§정적분석), 뚫렸을 때 할 수 있는 일은 줄여 둔다.
#
# **모델을 굽기 전에 바꾼다.** 구운 뒤에 `chown -R` 하면 553MB 가 통째로 복사된
# 레이어가 하나 더 생겨 이미지가 3GB 로 커진다. 사용자를 먼저 바꾸면 가중치가
# 처음부터 그 사용자 소유로 떨어진다.
#
# 쓰기가 필요한 곳은 둘뿐이라 그 **디렉터리만** 넘긴다(-R 아님):
#   cache/  ← rate_limit.json (DB 폴백) · models/ (아래에서 굽는다)
#   logs/   ← runs.jsonl (DB 폴백)
# node_modules·cache/tools(PMD)·app 은 읽기만 하므로 root 소유로 둔다.
# ─────────────────────────────────────────────────────────────────────────
RUN useradd --create-home --uid 10001 app \
 && mkdir -p /app/logs \
 && chown app /app/cache /app/logs

USER app

# ─────────────────────────────────────────────────────────────────────────
# 임베딩 모델을 **빌드 시점에 굽는다.** fastembed 는 import 때가 아니라 첫 embed()
# 호출 때 가중치를 받으므로, 여기서 한 번 태워야 cache/models/ 에 떨어진다.
#
# **일곱 개를 .env 와 같게 맞춘다.** 기본값은 jina-code(768)인데, 운영은 e5-large
# 계열(1024)로 돈다. 기본값으로 구우면 jina 가 들어가고 기존 색인과 벡터가 안 맞는다.
# 접두어의 끝 공백은 값의 일부다 — E5 는 "query: 질문" 이어야 한다.
# ─────────────────────────────────────────────────────────────────────────
ENV EMBEDDING_MODEL=intfloat/multilingual-e5-large-int8 \
    EMBEDDING_DIM=1024 \
    EMBEDDING_QUERY_PREFIX="query: " \
    EMBEDDING_PASSAGE_PREFIX="passage: " \
    CHUNK_TABLE=code_chunks_1024_int8 \
    EMBEDDING_SOURCE_REPO=intfloat/multilingual-e5-large \
    EMBEDDING_MODEL_FILE=onnx/model_qint8_avx512_vnni.onnx

# 굽는 데 필요한 최소 두 파일만 먼저 넣는다. 앱 코드를 통째로 앞당기면 라우터 한 줄
# 고칠 때마다 이 레이어가 깨진다. 반대로 이 둘을 고치면 다시 굽는 것이 맞다 —
# 모델 이름·차원·등록 방식이 여기 있다.
COPY Back/app/__init__.py Back/app/config.py ./app/
COPY Back/app/core/__init__.py Back/app/core/embeddings.py ./app/core/

# 차원을 확인하고 틀리면 빌드를 깬다. 768 이 나오면 jina 가 구워진 것이다.
RUN python -c "\
from app.config import EMBEDDING_DIM, EMBEDDING_MODEL; \
from app.core.embeddings import embed_query; \
v = embed_query('빌드 시점 예열'); \
assert len(v) == EMBEDDING_DIM, f'{EMBEDDING_MODEL}: dim {len(v)} != {EMBEDDING_DIM}'; \
print(f'임베딩 모델 구움: {EMBEDDING_MODEL} dim={len(v)}')"

# ─────────────────────────────────────────────────────────────────────────
# 자주 바뀌는 것. 여기서부터는 캐시가 깨져도 재빌드가 몇 초다.
# ─────────────────────────────────────────────────────────────────────────
COPY Back/app ./app

EXPOSE 8000

# HEALTHCHECK 는 여기 없다 — compose 가 건다(간격·재시도는 배치의 몫이고,
# 그 값이 `depends_on: condition: service_healthy` 의 기동 순서를 정한다).

# **워커는 하나다.** 인덱싱 큐와 남용 방지 카운터가 프로세스 메모리에 있어서
# --workers 2 이상이면 상한이 워커 수만큼 늘어나고 색인이 중복된다.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
