# 09 — 배포

> **머리말.** 배포 준비 작업의 로그다. 컨테이너 이미지·오케스트레이션이 여기 들어간다.
> "지금 값이 무엇인가"는 [STATUS.md](../../STATUS.md) 를 본다.

<!-- BODY -->

## 1단계 — 백엔드 Dockerfile (2026-08-25)

브랜치 `feat/docker`. **이번 단계는 백엔드 이미지 하나다** — compose 도 배포도 하지 않았다.

### 계획

1. Python 3.12 + JVM(PMD) + Node(oxlint) 를 한 이미지에 → 검증: 컨테이너 안에서 네 린터가 실제로 돈다
2. 임베딩 모델을 빌드 시점에 굽기 → 검증: 네트워크를 끊고(`HF_HUB_OFFLINE=1`) 벡터가 나오고 **차원이 1024**
3. `.dockerignore` 로 `Back/cache/` 제외 → 검증: 컨텍스트 전송량이 GB 단위가 아니다
4. 무거운 다운로드를 코드 COPY 앞으로 → 검증: 레이어 순서
5. `.env` 는 굽지 않는다 → 검증: 이미지 안에 `/app/.env` 가 없고 `ANTHROPIC_API_KEY` 가 빈 값

### 만든 것

- `Back/Dockerfile`
- `.dockerignore` (저장소 루트. **컨텍스트가 루트다** — `docker build -f Back/Dockerfile .`)

### 왜 런타임이 셋인가

정적분석기가 넷인데 런타임이 셋이다. `ruff` 는 pip, `oxlint`·`stylelint` 는 Node,
`PMD` 는 JVM. **하나라도 빠지면 그 언어의 정적분석만 조용히 사라진다**
(`_run_*` 이 도구를 못 찾으면 `None` 을 돌려주고 로그 한 줄만 남긴다).
그래서 "이미지가 떴다"로는 검증이 안 되고, 네 개를 각각 태워 봐야 한다.

### 임베딩 모델을 굽는 자리

**fastembed 는 import 때가 아니라 첫 `embed()` 때 가중치를 받는다.** 그래서
`RUN python -c "... embed_query(...)"` 로 한 번 태워야 `cache/models/` 에 떨어진다.

그 앞에 **환경변수 7개를 `.env` 와 같게 박았다.** 기본값은 jina-code(768)인데 운영은
e5-large 계열(1024)이라, 기본값으로 구우면 **다른 모델이 들어가고 기존 색인과 벡터가 안 맞는다.**
`ENV` 로 박는 이유는 굽는 시점만이 아니라 **런타임도 같아야** 하기 때문이다 —
런타임이 기본값으로 돌면 이미지 안의 가중치를 두고 다시 받는다.
(비밀이 아니므로 `.env` 금지 규칙에 걸리지 않는다. 런타임에 덮을 수도 있다)

같은 `RUN` 에서 `len(v) == EMBEDDING_DIM` 을 단언한다. **768 이 나오면 빌드가 깨진다** —
잘못 구워진 이미지가 조용히 나가는 것보다 낫다.

굽는 데 필요한 파일은 `app/config.py`·`app/core/embeddings.py` **둘뿐**이라 그 둘만 먼저 COPY 한다.
앱을 통째로 앞당기면 라우터 한 줄 고칠 때마다 이 레이어가 깨져 650MB 를 다시 받는다.
반대로 이 둘이 바뀌면 다시 굽는 것이 맞다 — 모델 이름·차원·등록 방식이 거기 있다.

**등록 로직을 Dockerfile 에 복사하지 않았다.** `add_custom_model` 의 pooling·정규화를
베끼면 `embeddings.py` 와 갈라지고, 갈라져도 오류가 안 난다(캐시는 저장소 이름과 파일명으로만
결정된다). 실제 코드 경로를 그대로 태우면 그 위험이 없다.

### 레이어 순서

pip → npm → PMD → 모델 → **코드**. 앞의 넷이 합쳐 690MB 를 받는데, 코드 뒤에 두면
한 줄 고칠 때마다 그걸 다시 받는다.

### libgomp1 을 넣었다가 뺐다

`python:3.12-slim-bookworm` 에 `libgomp` 가 없어서(실측) onnxruntime 이 죽을 것이라 보고
넣었다. **확인해 보니 링크하는 것이 하나도 없었다** — site-packages 의 `.so` 를 전부
`ldd` 로 훑어 libgomp 를 찾는 것이 0개였고, 빼고 재빌드해도 임베딩이 그대로 돌았다.

*"slim 에 없다"와 "그래서 필요하다"는 다른 명제다.* 짐작으로 넣은 패키지는 주석까지
틀리게 만든다("없으면 죽는다"고 적어 뒀었다).

### Node 를 apt 로 받지 않은 이유

bookworm 의 `nodejs` 는 **18.20.4** 인데 `package.json` 의 두 도구가 그보다 높은 것을 요구한다
(실측: stylelint `>=20.19.0`, oxlint `^20.19.0 || >=22.12.0`). NodeSource 저장소를 붙이는
대신 공식 `node:22-bookworm-slim` 에서 `node` 바이너리와 `node_modules` 를 COPY 했다.

### 검증 결과 (로컬 Docker Desktop 28.3.2)

| 항목 | 결과 |
|---|---|
| 임베딩 모델 | `cache/models/models--intfloat--multilingual-e5-large` 553MB. `HF_HUB_OFFLINE=1` 로 로드해 질의·문서 벡터 **둘 다 dim=1024**, 입력 한도 512 |
| 임베딩 설정 7개 | 런타임 `config` 값이 `.env` 와 일치. **접두어 끝 공백도 보존**(`'query: '`·`'passage: '`) |
| PMD | `pmd-bin-7.26.0`, OpenJDK 17.0.20 위에서 샘플 Java 검사 → `EmptyCatchBlock` 검출 |
| oxlint | 1.79.0, Node 22.23.2 |
| 네 린터 동시 | `static_analysis.analyze()` 로 ruff 2건 · oxlint 2건 · pmd 2건 · stylelint 0건. **`find_tool`/`find_pmd` 가 넷 다 찾는다** |
| `.env` | 이미지에 없음. `ANTHROPIC_API_KEY` 빈 값 |
| 기동 | DB 없이 `/health` → `{"status":"ok"}` (문서대로 DB 기능만 꺼진다) |
| 이미지 크기 | **2.39GB** — site-packages 308MB · JVM 184MB · 모델 553MB · PMD 78MB · node_modules 52MB |

### 남겨 둔 것

- **root 로 돈다.** 비-root 사용자를 넣지 않았다. 린터 셋이 남의 코드를 실행하지 않도록
  고른 것들이라(§정적분석) 급하지는 않지만, 배포 전에 볼 것
- `HEALTHCHECK` 없음 — compose 단계에서 넣는 편이 낫다
- `Back/tests/` 는 `.dockerignore` 로 뺐다. 이미지 안에서 `pytest` 를 돌릴 수 없다
