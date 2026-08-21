# 01 · Stage 1–2

2026-08-13 ~ 08-15 · [plan.md](../../plan.md) 로 돌아가기

포함된 절:
- Stage 1: URL 입력 → 프로젝트 요약 (MVP)
- Stage 2: 대화 이력 저장 (백엔드) - 2026-08-15

<!-- BODY -->

## Stage 1: URL 입력 → 프로젝트 요약 (MVP)

### Back
- [x] FastAPI 스캐폴드 + config + /health - 2026-08-13
  - Python 3.14 환경. pydantic 버전 고정 시 wheel 빌드 실패해서 `>=` 로 완화.
- [x] GitHub fetch 서비스 (`github_client.py`) - 2026-08-13
  - `/repos/{o}/{r}`, `/readme`, `/git/trees?recursive=1`, `/contents/{path}` 사용
  - 조직 이전 repo가 301을 반환해서 `follow_redirects=True` 추가
  - 매니페스트 탐색은 잘리기 전 전체 트리에서 수행 (200개 컷 이후 검색하니 pyproject.toml 누락됨)
- [x] 컨텍스트 조립 (`context_builder.py`) - 2026-08-13
- [x] Claude 요약 서비스 (`claude_client.py`) - 2026-08-13
  - claude-sonnet-5, effort=medium, system 프롬프트에 prompt caching 적용
- [x] POST /analyze 통합 - 2026-08-13
  - 400(URL 형식) / 404(repo 없음) / 502(GitHub API 오류) 응답 확인

### Front
- [x] Vite + React + TS 스캐폴드 - 2026-08-13
  - `npm create vite -- --template react-ts` 인자가 먹지 않아 vanilla-ts로 생성됨.
    react/react-dom/@vitejs/plugin-react 수동 설치 후 main.tsx·vite.config.ts 작성으로 전환.
- [x] URL 입력 → /analyze 호출 → 마크다운 요약 표시 - 2026-08-13
- [x] GitHub 다크 테마 + 레이아웃 적용 - 2026-08-13
  - App.css에 GitHub 다크 팔레트(CSS 변수) + 마크다운 본문 스타일 추가
  - 레이아웃: 상단 바(브랜드 + URL 폼) / 레포 헤더(owner/name + Public 배지) /
    2컬럼 그리드(요약 본문 + About 사이드바), 900px 이하 1컬럼
  - octicon(repo/star) SVG는 App.tsx에 인라인. public/icons.svg는 무관한 아이콘셋이라 미사용

### 리팩터링
- [x] 백엔드 레이어 분리 (api / services / schemas) - 2026-08-13
  - github_client·claude_client·context_builder → `app/services/`, schemas.py → `app/schemas/schemas.py`
  - `/health`, `/analyze` → `app/api/`의 APIRouter로 분리, main.py는 앱 생성 + CORS + include_router만
  - `.env`·requirements.txt는 Back/ 루트 유지 (load_dotenv가 실행 CWD 기준이라 옮길 이유 없음)
  - config.py는 `app/` 유지 → services의 `from app.config import ...` 수정 불필요
  - 검증: uvicorn 기동 후 /health 200, /analyze 잘못된 URL 400

### 관리자 페이지 (로컬 실험/비교 도구) - 2026-08-13
목표: 모델·effort·프롬프트를 바꿔가며 돌리고 처리시간/토큰/비용/응답을 비교. 기록은 파일에 누적.
- [x] `services/claude_client.py` 확장 — `run_summary()`가 응답+소요시간+토큰+비용 반환, MODELS/PRICING 추가
  - Haiku 4.5는 effort 미지원 → MODELS에 플래그를 두고 미지원이면 output_config 자체를 뺀다 (보내면 API가 거부)
  - sonnet-5 단가는 도입가 $2/$10 기준. 2026-08-31 지나면 $3/$15로 수정 필요
  - 기존 `summarize_repo()`는 str 반환 그대로 유지 → /analyze 경로 무손상
- [x] `services/run_log.py` — Back/logs/runs.jsonl append/read (최신순)
- [x] `api/admin.py` — GET /admin, /admin/config, /admin/runs, POST /admin/run
- [x] `templates/admin.html` — 실행 폼 + 기록 테이블 + 클릭 시 응답/프롬프트 상세
- [x] 검증: 4개 엔드포인트 200, 잘못된 URL 400, JSONL 기록→조회 왕복 확인
  - LLM 실호출은 과금이라 미검증 (사용자가 직접 실행)
- 타 제공사(OpenAI/Gemini) 비교는 범위에서 제외 — Anthropic 모델 간 비교부터

### 관리자 페이지 재구성 (홈 → 하위 기능) - 2026-08-14
- [x] 라우팅 분리 — 페이지 `/admin`(홈) `/admin/lab` `/admin/runs`, API는 `/admin/api/*`로 이동
  - 기존 GET `/admin/runs`(JSON)가 기록 페이지 경로와 충돌해서 API 전체에 `/api` 접두사를 붙임
- [x] 템플릿 3분할 — `admin_home.html`(기능 카드) / `admin_lab.html`(실행 폼+결과) / `admin_runs.html`(필터·정렬 표)
  - 사이드바·팔레트 CSS 3중복을 피하려고 `templates/admin.css` 분리 후 `/admin/admin.css`로 서빙
  - 기록 뷰어: 출처/모델/repo 필터, 열 헤더 클릭 정렬, 건수+비용 합계
- [x] 프론트 호출도 로깅 — `/analyze`가 `run_log.append_run(source="analyze")` 기록
  - 레코드에 `source`("lab"|"analyze") 추가. 옛 기록엔 없어서 화면에서 "lab"으로 간주
  - `run_log.append_run()` 헬퍼로 두 경로의 레코드 형태를 통일
  - `claude_client.summarize_repo()` 제거 — analyze가 `run_summary()`를 직접 쓰면서 미사용
- [x] 검증: 8개 라우트 200/307, 잘못된 URL에 `/admin/api/run`·`/analyze` 400, append_run→read→RunResult 왕복

### 사용량 페이지 - 2026-08-14
- [x] `services/usage_stats.py` — runs.jsonl 집계 (호출 횟수 / 토큰 / 비용 / 평균 LLM 시간)
  - 출처별·모델별·일자별. 빈 날짜도 0으로 채워서 반환
  - 날짜 구분은 로컬 타임존. `source` 없는 옛 기록은 "lab", `cost_usd` 없으면 0으로 취급
- [x] `github_client.fetch_rate_limit()` — core/search/graphql 잔여 요청
- [x] `api/admin.py` — GET /admin/usage(페이지), /admin/api/usage, /admin/api/github
- [x] `templates/admin_usage.html` — 요약 타일 + 출처별/모델별/일자별 표 + GitHub rate limit 표
- [x] 검증: 합성 로그로 집계 정확도(구간 필터·None 처리·빈 날짜·평균) + 실제 runs.jsonl로 /admin/api/usage 200,
      /admin/api/github 200(실호출), 7개 라우트 200

**Anthropic Admin API는 도입했다가 되돌림** — `/v1/organizations/{usage_report/messages,cost_report}`로
조직 실청구를 붙였으나 **Admin API는 개인 계정에서 사용 불가**(조직 + admin 역할 필요)라 로컬 집계로 회귀.
나중에 조직 계정이 생기면 다시 붙일 때 참고할 점:
- Admin 키는 `sk-ant-admin01-...`, 일반 API 키와 별개. Console → Settings → Admin keys. 발급·호출 자체는 무과금
- usage_report에 **요청 수 필드가 없다** (토큰 + web_search_requests뿐) → 호출 횟수는 여전히 로컬 로그가 필요
- cost의 `amount`는 센트 단위 decimal 문자열 → /100
- bucket_width=1d는 한 페이지 최대 31버킷 → 그 이상은 `next_page` 페이지네이션 필요

### URL 정규화 - 2026-08-14
목적: 로그인이 없어 같은 레포 재분석을 걸러낼 수 없으니, 우선 "같은 레포 = 같은 키"를 만든다 (캐싱의 선행 작업).
- [x] `github_client.parse_github_url()` 재작성 — 소문자 owner/repo 반환
  - 정규식 `...$` 앵커 때문에 `tree/main`·`?tab=` 이 붙으면 400이 나던 문제도 같이 해결
  - `urlsplit`으로 분해 → 호스트 검사(github.com/www) → 3번째 이후 세그먼트 버림 → `.git` 제거 →
    이름 문자 검증 → 예약 경로(`RESERVED_OWNERS`) 차단 → 소문자화
- [x] 표시 표기 분리 — `fetch_repo_context()`의 `meta.owner/name`을 GitHub 응답의 `owner.login`/`name`으로
  - 소문자 키를 그대로 쓰면 헤더가 `microsoft/typescript`로 보임. 키(API 호출·로그)와 표시를 분리
  - `run_log`의 `repo`는 식별 키이므로 소문자 유지 → analyze.py/admin.py는 수정 없음
- [x] `tests/test_github_client.py` + requirements에 pytest — 35 passed
  - 검증: `.venv`로 pytest 35/35, `fetch_repo_context('microsoft','typescript').meta` → `microsoft/TypeScript`,
    `/health` 200, `/analyze`에 gitlab·예약경로·repo누락 각 400. Claude 실호출은 안 함(토큰 절약)
- **주의:** repo별 집계를 붙일 때는 `record["repo"].lower()`로 묶을 것. 정규화 이전 옛 기록은
  사용자 입력 대소문자 그대로라 안 묶으면 갈린다 (`admin_runs.html`의 repo 검색은 이미 소문자 비교 중)

### 사전 접근 확인 - 2026-08-14
목적: 비공개/삭제/빈 레포를 LLM 호출 전에 걸러 토큰을 아낀다.
- [x] `github_client.check_repo_access(owner, repo)` — `GET /repos` 한 번으로 판정 + 메타 반환
  - 404→404(비공개/없음), 403·429→429(한도 초과), 그 외 비200→502, `size==0`→422
  - 반환: 정식 표기 owner/name, default_branch, size_kb, archived, description, language, stars
- [x] `RepoAccessError(message, status_code)` 도입 — `RepoNotFoundError` 대체(호출부 2곳 정리)
  - 서비스가 상태코드를 들고 있고 API는 `HTTPException(e.status_code, str(e))` 한 줄로 변환
- [x] `fetch_repo_context(owner, repo, access=None)` — access 재사용으로 `GET /repos` 중복 제거
  - access 없이 부르면 내부에서 check를 호출하는 폴백 유지 (스크립트/직접 호출 경로 보호)
- [x] `analyze.py` / `admin.py` 둘 다 파싱 직후 check → fetch 순서로 연결
- [x] 크기 차단은 **기본 끔** — `config.MAX_REPO_SIZE_KB` 기본값 0(무제한), .env로만 켬
  - GitHub `size`는 git 히스토리 포함이라 LLM 입력량과 무관(트리·파일은 이미 잘림).
    react 1.0GB / TypeScript 2.9GB / linux 6.3GB — 낮게 잡으면 정상 레포가 거절된다
- [x] 검증: pytest 44 passed(응답 위조로 404/403/429/500/빈레포/크기상한),
      실호출로 요청 수 실측, `/analyze` 없는 레포 404·gitlab 400. Claude 실호출 없음

**analyze 1회당 GitHub 요청 = 3 + 매니페스트 수** (`/repos` + `/readme` + `/git/trees` + `/contents`×N)
실측: fastapi 4회 · requests 5회 · react 6회. check 도입 전과 동일(access 재사용).
미인증 60/h → 시간당 10~15개 레포. 404로 걸러지면 1회만 소모(60개/h). 토큰 있으면 5,000/h → 약 1,000개.

### 요약 캐시 - 2026-08-14
목적: 같은 레포를 다시 분석할 때 LLM 호출을 건너뛴다.
- [x] `services/summary_cache.py` — `build_key()` / `get(access)` / `put(access, ...)`
  - 키 = `{정식표기 소문자}@{key_source}:{버전}` 예) `react/react@pushed_at:20260813154443`
  - 입력 URL이 아니라 `check_repo_access()`의 정식 표기를 쓴다 → 리다이렉트로 갈리던 문제 해결
    (`facebook/react`·`react/react` 둘 다 `react/react@...` 로 모임을 실호출로 확인)
- [x] 무효화 기준은 **커밋 SHA가 아니라 `pushed_at`** — `/repos` 응답에 이미 있어 추가 요청 0회
  - SHA는 `GET /git/ref/heads/{branch}` 가 필요해 레포당 요청이 1회 늘어난다. 고유성만 필요해서 반려
  - 기본 브랜치가 아닌 곳에 푸시해도 갱신되는 과잉 무효화가 있지만 안전한 방향의 오차
  - 키에 `key_source`를 박아뒀으므로 나중에 SHA로 바꿔도 옛 키와 섞이지 않는다. 레코드에도 남긴다
- [x] ISO 타임스탬프 정규화 — UTC로 맞춘 뒤 숫자만 (`2026-08-14T09:12:33Z` → `20260814091233`)
  - 타임존 표기가 달라도(`+09:00` vs `Z`) 같은 시각이면 같은 키
- [x] 저장은 파일 (`Back/cache/summaries.json`), `.gitignore`에 `Back/cache/` 추가
  - 저장소 접근은 `get`/`put` 뒤에 감춤 → PostgreSQL 이전 시 이 둘의 내부만 교체
  - 읽기·쓰기 실패는 `logger.warning` 만 남기고 캐시 미스처럼 진행 (캐시가 분석을 막지 않는다)
  - `put()` 시 같은 레포의 옛 버전 키는 삭제 → 파일이 무한정 커지지 않는다
- [x] `/analyze` 연결: 파싱 → check → **캐시 조회(히트면 즉시 반환)** → fetch → LLM → 캐시 저장
  - 히트 시 응답의 repo 정보는 캐시가 아니라 access에서 만든다(별점·설명은 항상 최신)
  - `admin/api/run`은 캐시 **미적용** — 모델·프롬프트를 바꿔가며 비교하는 실험 도구라 캐시하면 목적이 깨진다
- [x] 검증: pytest 59 passed, 캐시 히트 시 GitHub 요청 1회(check만)·LLM 미호출을 실측
      (`run_summary`를 예외 발생 함수로 갈아끼워 도달 시 실패하게 두고 확인)

**캐시 히트 시 GitHub 요청 1회** → 미인증 60/h 기준 시간당 60개, 미스는 4~6회 그대로.
참고: 현재 `.env`에 GITHUB_TOKEN이 설정돼 있어 실제 한도는 5,000/h다.

### 캐시 히트율 - 2026-08-14
- [x] `run_log.append_cache_hit()` — 히트도 같은 로그에 남긴다. 토큰·비용·llm_ms 전부 0
  - `append_run()`에는 `cached: False` 추가. 두 함수의 레코드 필드 집합이 같은지 테스트로 고정
  - 기록되는 model은 **그 요약을 만들 때 쓴 모델**(캐시 레코드의 model)이지 이번에 부른 모델이 아니다
- [x] `schemas.RunResult.cached` 추가 (기본값 False) — `cached` 없는 옛 기록도 그대로 파싱됨
- [x] `usage_stats` — `cache_hits` / `llm_calls` / `hit_rate` 를 totals·by_source·by_model·daily 전부에 추가
  - **평균 LLM 시간의 분모에서 히트를 뺐다.** 안 빼면 히트가 늘수록 평균이 0으로 끌려가 응답 속도를 못 읽는다
  - `cached` 없는 옛 기록은 LLM 호출로 간주 (히트로 오인하면 절감량이 부풀려진다)
- [x] `admin_usage.html` — 히트율 타일(‘N건 캐시 · M건 LLM 호출’) + 출처별·일자별 히트율 열
  - 모델별 표의 '호출'은 `llm_calls`로 바꿈 — 이 표는 LLM 사용량 비교용이라 히트가 섞이면 안 된다
- [x] 검증: pytest 70 passed, 캐시 히트 2건+옛 기록 1건으로 히트율 66.7%·평균 3000ms(분모 1) 확인,
      실제 runs.jsonl로 `/admin/api/usage` hit_rate 0.0(옛 기록 오인 없음), admin 4개 라우트 200
  - 화면 렌더링은 미확인(Chrome 확장 미설치). JS가 참조하는 id 18개가 모두 정의됐는지만 정적 확인

### 남용 방지 - 2026-08-14
목적: 로그인이 없어 누구나 무제한 호출할 수 있으므로 서비스 전체 상한 + IP별 제한을 건다.
- [x] `services/rate_limit.py` — `check_and_reserve(ip)` / `record_tokens(n)` / `today_usage()` / `client_ip(request)`
  - **캐시 히트에는 두 제한 모두 미적용.** 호출부가 캐시 조회 뒤 미스일 때만 검사한다
  - 일일 상한은 사용자별이 아니라 **서비스 전체 합산** (로그인이 없어 사용자를 못 가른다)
  - 횟수는 호출 **전** 예약(동시 요청이 함께 상한을 넘지 못하게), 토큰은 호출 **후** 기록
  - 토큰 상한은 사후 판정 — 호출 전엔 쓸 양을 모르니 상한을 넘기는 마지막 한 번은 통과한다
  - LLM 호출이 실패해도 예약분은 되돌리지 않는다 (덜 쓰는 쪽이 안전)
- [x] 동시성 — 모듈 `threading.Lock`으로 read-modify-write 직렬화
  - 스레드 5개×10회 동시 실행에서 카운트 50 유지되는지 테스트로 고정
  - **단일 프로세스 한정.** `uvicorn --workers 2` 이상이면 워커마다 Lock이 달라 어긋난다 → PostgreSQL 이전 시점
- [x] IP 판별 — `TRUST_PROXY_HEADERS=1` 일 때만 `X-Forwarded-For`(맨 앞) → `X-Real-IP` 순으로 신뢰
  - 기본은 꺼둔다. 헤더는 클라이언트가 위조할 수 있어 프록시 없이 신뢰하면 IP 제한이 무력화된다
  - IP 윈도우는 슬라이딩. 날짜가 바뀌어도 비우지 않는다 — 자정에 같이 비우면 그 순간이 우회 구멍
- [x] 환경변수 (전부 `config.py`, 0이면 해당 제한 끔)
  - `DAILY_LLM_CALL_LIMIT=500` `DAILY_TOKEN_LIMIT=5000000` `IP_RATE_LIMIT=20`
    `IP_RATE_WINDOW_SECONDS=3600` `TRUST_PROXY_HEADERS=0`
- [x] 저장 `Back/cache/rate_limit.json` — `_read_state()`/`_write_state()` 뒤에 감춤(PostgreSQL 이전 대비)
  - 읽기·쓰기 실패는 경고만 남기고 진행 (상한 장치 때문에 서비스가 멈추면 안 된다)
- [x] `admin/api/run`(실험실)은 **제한도 기록도 안 함** — 관리자가 실험하다 공개 서비스를 막는 상황 방지
- [x] `/admin/usage` 상단에 '오늘 사용량' 섹션 — 호출·토큰 미터(80% 노랑/100% 빨강) + IP 제한 요약
- [x] 검증: pytest 90 passed. TestClient로 캐시 히트 25회(IP 한도 3) → **전부 200, 카운터 calls/tokens/ips 모두 0**,
      한도 소진 후 미스 429이지만 히트는 계속 200, 일일 호출·토큰 상한 각각 429, `/admin/api/usage`에 today 포함
  - 화면 렌더링은 미확인(Chrome 확장 미설치). JS 참조 id 22개 정의 여부만 정적 확인

### /analyze 흐름 점검 + 상태코드 정리 - 2026-08-14
순서는 "싼 검사 먼저, 비싼 호출 마지막" 원칙과 이미 일치해서 **재배치 없음**. 확정된 순서:
`본문검증(0) → URL파싱(0) → check_repo_access(GitHub 1회) → 캐시조회(히트면 종료)
 → 남용제한(0) → fetch_repo_context(GitHub 3+N회) → build_context → LLM → 기록`
- 제한 검사가 GitHub 1회 뒤에 있는 건 구조상 불가피 — 캐시 키가 `pushed_at`에서 나오고,
  캐시 히트에 제한을 안 걸려면 캐시 조회가 제한보다 앞서야 한다. 제한에 걸린 요청도 GitHub 1회는 쓴다
- [x] 빈 저장소 **422 → 400** — 422는 FastAPI 본문 검증이 이미 쓴다(detail이 배열).
      겹치면 프론트가 `body.detail`을 그대로 표시할 때 `[object Object]`가 된다
- [x] `anthropic.APIError` **500 → 502** — analyze.py에 except가 없어 미처리 500이었다. admin.py와 통일
- [x] 429에 **Retry-After** 헤더 — IP는 윈도우 잔여 초, 일일 상한은 자정까지 남은 초
- [x] `run_log.append()` 쓰기 실패 방어 — 이 함수는 LLM 호출 **뒤**에 불려서, 예외가 나면
      토큰은 쓰고 응답은 잃는 최악의 실패였다. summary_cache·rate_limit과 같은 방침(경고만)
- [x] 검증: pytest 93 passed. TestClient로 8개 실패 경로 실측
      (본문검증 422 / 파싱 400 / 없는repo 404 / IP 429+3598s / 일일 429+2978s / APIError 502 / 키없음 503)

- [x] 프론트 `App.tsx` — `errorMessage(detail, status)` 추가
  - 문자열이면 그대로, 배열(FastAPI 검증)이면 각 항목 `msg`를 합치고, 없으면 "입력 형식이 올바르지 않습니다"
  - 그 전에는 `body.detail`을 그대로 Error에 넣어 배열일 때 `[object Object]`가 표시됐다
  - 검증: `tsc --noEmit` 통과, `npm run build` 성공, 실측 응답 11종으로 함수 동작 확인
  - 주의: 검증 msg는 FastAPI가 주는 영어 그대로다("Field required"). 프론트가 항상 문자열을
    보내므로 정상 사용에선 안 나오는 방어 경로. 거슬리면 한국어 고정 문구로 바꿀 것

**상태코드 규약** — 400 입력·대상이 부적합(형식 오류, 예약 경로, 빈 저장소) / 404 대상 없음·비공개 /
413 크기 초과(기본 꺼짐) / 422 **FastAPI 본문 검증 전용** / 429 한도(우리 제한 + GitHub 한도, Retry-After 동반) /
502 외부 의존(GitHub·Claude) 장애 / 503 서버 설정 미비(API 키 없음)

### 미완료
- [x] `/admin/usage` 화면 눈으로 확인 (히트율 타일·오늘 사용량 미터) - 2026-08-18 (Phase 3)
- [x] `Back/.env.example` 작성 - 2026-08-14
  - 변수 9개 전부 기본값 + 한 줄 설명. 남용 방지 블록에 "단일 프로세스 전제, --workers 2 이상이면
    상한이 워커 수만큼 느슨해진다"를 명시
  - 검증: config.py의 `os.environ.get` 키 목록과 예시 파일 키가 9개 모두 일치
- [x] Claude API end-to-end 실호출 검증 - 2026-08-18 (Phase 3, `/analyze` → `/chat` 왕복)
- [x] 브라우저 수동 확인 - 2026-08-17~18 (Chrome 확장 연결됨)

## Stage 2: 대화 이력 저장 (백엔드) - 2026-08-15
목표: 분석 결과를 대화의 출발점으로 만든다. 후속 질문이 GitHub을 다시 읽지 않도록
`build_context()` 원문을 스냅샷에 저장해 두고 대화 내내 재사용한다.

### 저장소 도입
- [x] PostgreSQL 17 (`Back/docker-compose.yml`) + `psycopg[binary,pool]` 3.x - 2026-08-15
  - **ORM·마이그레이션 도구 없음.** 코드베이스가 전부 sync이고 쿼리가 10여 개라 생 SQL.
    스키마는 `app/db/schema.sql`을 기동 시 멱등 실행(`CREATE TABLE IF NOT EXISTS`)
  - `DATABASE_URL`이 비면 DB 없이 동작 — 요약 캐시가 꺼지고(매번 LLM) `/chat`은 503
- [x] `app/db/` 신설 (CLAUDE.md §6에 없는 종류라 위치를 먼저 확정) - 2026-08-15
  - `pool.py` 연결 풀·커서·`init_schema()` / `schema.sql` / `repos.py` / `chats.py`
  - 풀 생성은 **lazy**. import 시점에 접속하면 DB 없이 도는 테스트가 전부 막힌다
  - `init_schema()` 실패는 경고만 — DB 장애가 앱 기동과 `/health`를 막지 않는다
  - **접속 타임아웃 5초** (`connect_timeout` + 풀 `timeout`). 기본값은 무제한 대기라
    응답 없는 주소(방화벽이 SYN을 버리는 경우)에 걸리면 요청이 130초 매달린다 — 실측 후 추가
  - `atexit.register(close)` — 스크립트가 풀을 열어 둔 채 끝나면 psycopg_pool이
    종료 시점에 워커 join을 시도해 `PythonFinalizationError`를 뱉는다
- [x] 테이블 4개 — `repos` / `repo_snapshots` / `chat_sessions` / `messages` - 2026-08-15
  - `chat_sessions`에 `repo_id`를 두지 않는다 — `snapshot_id`로 조인하면 나오고,
    두 곳에 두면 어긋난다. 세션이 보는 코드 버전은 스냅샷 하나로 확정된다
  - `messages`에 토큰·비용 열을 두지 않는다 — 사용량 집계는 `runs.jsonl`이 이미 담당

### 요약 캐시 → DB
- [x] `summary_cache` 저장 위치만 `repo_snapshots`로 교체 - 2026-08-15
  - 키 생성 로직(`_repo_key`/`_version`/`build_key`)은 그대로. DB의 `version` 열이 그 값이다
  - `put()`에 `context` 인자 추가 → 요약과 컨텍스트 원문이 같은 행에 모인다
  - **옛 스냅샷을 지우지 않는다** (파일 캐시와 달라진 점) — 진행 중인 대화가 그 행을
    참조하므로 지우면 후속 질문이 볼 코드가 사라진다. 누적 정리는 별도 과제
  - 실패 정책은 유지: DB 오류는 경고만 남기고 캐시 미스처럼 진행
  - `Back/cache/summaries.json`은 폐기 (마이그레이션 안 함 — 옛 항목엔 context가 없어 대화에 못 쓴다)

### 대화 엔드포인트
- [x] `claude_client` — `_call()` 공통 추출 + `run_chat()` + `CHAT_SYSTEM_PROMPT` - 2026-08-15
  - `run_summary()`의 시그니처·반환 dict는 그대로 → `/analyze`·`/admin/api/run` 무손상
  - **`cache_control`은 스냅샷 원문(첫 사용자 메시지)에 건다.** 대화가 길어져도 그 앞은
    캐시에서 읽혀 입력 비용이 1/10 단가
  - 메시지 구성: `user(스냅샷)` → `assistant(요약)` → 이력 → `user(새 질문)`.
    요약을 assistant 턴으로 끼우면 역할이 자연히 번갈아 나온다
  - 이력은 최근 20개(`MAX_HISTORY_MESSAGES`)만. 자르는 지점이 캐시 지점보다 뒤라 접두사가 안 깨진다
- [x] `api/chat.py` — `POST /chat`, `GET /chat/{session_id}` - 2026-08-15
  - `github_url`을 받지 않는다. 세션은 `/analyze`가 만들고 `session_id`를 응답에 담는다
  - **질문·답변 저장은 LLM 성공 후, `chats.add_exchange()`로 한 트랜잭션.**
    계획은 질문을 먼저 저장하는 순서였는데, 호출이 실패하면 질문만 남아 다음 요청의
    이력이 `user`로 끝나고 → 역할이 번갈아 나오지 않아 API가 호출을 거부한다
  - 남용 제한 적용(`/analyze` 캐시 미스와 같은 무게) + `runs.jsonl`에 `source="chat"`
    → `usage_stats`의 출처별 표에 자동으로 잡힌다
  - UUID 형식 검증을 먼저 한다 — 아니면 DB가 형식 오류를 내고 503으로 뭉개진다(400이 맞다)
  - `GET /chat/{id}`는 외부 호출 0회. 그래서 응답의 repo는 `{owner, name}`만
    (설명·별점은 GitHub을 불러야 알 수 있다)
- [x] `/analyze`에 세션 연결 — `AnalyzeResponse.session_id` - 2026-08-15
  - 캐시 히트·미스 양쪽에서 세션을 만든다 (히트는 그 스냅샷 id를 그대로 쓰므로 추가 호출 0)
  - **세션 생성 실패는 요약을 막지 않는다** — `session_id=None`으로 200. 프론트는 값이
    없으면 질문 입력을 숨기면 된다
  - 순서 재배치 없음: `파싱 → check → 캐시조회 → 남용제한 → fetch → LLM → 스냅샷·세션`

### 재인덱싱
- [x] `POST /admin/api/reindex` — 스냅샷 강제 재생성 - 2026-08-15
  - `pushed_at`이 안 바뀌었는데 요약을 갱신하고 싶을 때(프롬프트 수정 등). 캐시 조회를 건너뛴다
  - **관리자 전용.** 사용자용 강제 새로고침을 열면 로그인이 없는 상태에서 캐시 우회 =
    토큰 구멍이 된다. `/admin/api/run`과 같이 남용 제한·오늘 사용량 카운터에 넣지 않는다
  - LLM을 부르기 **전에** `pool.is_enabled()`를 확인한다 — 나중에 막히면 토큰만 버린다
  - `runs.jsonl`에 `source="reindex"`. 같은 version이면 행을 덮어써 스냅샷 id가 유지된다
    (진행 중 대화가 끊기지 않는다)
  - `admin.py`의 `_summarize()`로 실험실 경로와 공통화 (파싱~기록이 30줄 중복이었다)
  - 관리자 페이지 버튼은 만들지 않았다 — 지금은 curl/PowerShell로 호출

### 검증
- [x] pytest **134 passed** (기존 93 + 41). `DATABASE_URL`을 못 쓰는 환경에서는 **19 skip, 115 passed**
  - 통합 테스트는 **별도 DB**(`repodive_test`)에 붙어 `TRUNCATE repos CASCADE`로 시작한다.
    개발용 DB를 비우면 직접 만들어 본 대화 이력이 매번 지워진다 (`tests/conftest.py`)
  - API 테스트는 `chats`·`summary_cache`·`run_chat`을 대역으로 갈아끼워 DB·과금 없이 돈다
- [x] 실측: uvicorn 기동 → 테이블 4개 생성, `/health` 200,
      `GET /chat/{없는 uuid}` 404 · `/chat/not-a-uuid` 400 · `POST /chat` 본문 누락 422 ·
      `reindex` gitlab URL 400 · `/admin/usage`·`/admin/api/usage` 200,
      실제 DB에 스냅샷·세션·메시지를 넣고 `GET /chat/{id}` 왕복 확인
  - **Claude 실호출은 안 함**(토큰 절약). `/analyze → /chat` 왕복은 사용자가 직접 확인

### 프론트 채팅 UI - 2026-08-15
목적: 백엔드가 만든 `session_id`가 응답에 담겨 와도 프론트가 받지 않아 대화 기능이
사용자에게 닿지 못했다. 로그인이 없어 `session_id`가 유일한 식별자이므로 브라우저에 보관한다.
- [x] `Front/src/api.ts` 신설 — `API_BASE` / `errorMessage()` / `ChatMessage` 타입
  - 계획은 `App.tsx`에서 export 하는 것이었으나 **App→Chat→App 순환 import**가 되어 별도 파일로 분리
  - `errorMessage()`에 `fallback` 인자 추가 → analyze("분석에 실패했습니다")·chat("답변을 받지 못했습니다")가 공용
- [x] `Front/src/Chat.tsx` — 대화 패널 (messages / question / pending / error)
  - **전송 중 질문은 `messages`가 아닌 `pending`에 둔다.** 백엔드는 LLM 성공 후에야 질문·답변을
    한 트랜잭션으로 저장하므로(`chats.add_exchange`), 실패한 질문을 화면에 남기면 새로고침 때 사라져
    화면과 DB가 어긋난다. 실패 시 입력창으로 되돌린다
  - 답변은 `.markdown` 클래스를 재사용하되 `.msg .markdown`으로 상자 스타일만 지운다(이중 테두리 방지)
  - textarea Enter 전송 / Shift+Enter 줄바꿈. 새 답변만 `scrollIntoView` — 첫 렌더에도 스크롤하면
    이력 복원 시 요약을 지나쳐 대화 끝으로 튄다
- [x] `App.tsx` — `resolveChat()` + localStorage 레포별 보관
  - 키 `repodive:session:{owner}/{name}` 소문자. **입력 URL이 아니라 응답의 정식 표기로 만든다** —
    백엔드 캐시 키와 같은 기준이라 저장소가 이전돼도 같은 대화로 모인다
  - 저장된 id가 있으면 `GET /chat/{id}` → 200이면 이어가고, 아니면 이번에 만들어진 세션을 쓴다
  - `localStorage` 접근은 try/catch. 실패하면 "저장된 세션 없음"으로 취급 —
    `summary_cache`가 DB 오류를 캐시 미스로 넘기는 것과 같은 방침
  - `session_id`가 null(DB 장애)이면 대화 UI를 통째로 숨긴다
- [x] `App.css` — `.main-col` 래퍼로 왼쪽 컬럼에 요약+대화를 세로로 쌓음
  - 그리드 아이템 수가 2개로 유지돼 900px의 `.sidebar { order: -1 }`이 그대로 동작 → **미디어쿼리 수정 없음**
  - 신규 CSS 변수 없음. `.chat textarea`·`.chat button`은 `.topbar` 것과 같은 값
- [x] 검증: `tsc --noEmit` 통과, `npm run build` 성공, pytest **134 passed**(백엔드 무수정 확인)
  - **LLM 호출 없이** 프론트 의존 계약을 실서버로 확인: 요약 캐시를 미리 심어
    `/analyze`를 캐시 히트로 만든 뒤 → `session_id` 반환됨 / 재분석 시 다른 세션 발급됨(복원 필요 확인) /
    `GET /chat/{id}` → `messages: [{role, content, created_at}]`, user→assistant 순서
  - 검증용으로 심은 `octocat/hello-world` 행과 `runs.jsonl` 기록 4건은 지웠다
  - **화면 렌더링은 미확인** (Chrome 확장 미설치)

**함정: DB가 없으면 대화 UI가 말없이 사라진다** - 2026-08-16에 실제로 겪음.
Docker(=PostgreSQL)를 안 띄운 채 분석하면 `_start_session`이 None → 프론트가 대화를 통째로 숨겨서
"채팅 기능이 없는" 것처럼 보인다. 요약은 정상이라 원인을 짚기 어렵다. 같은 상태에서 요약 캐시도
꺼지므로 매 분석이 LLM 실호출이 된다. **웹을 열기 전에 `cd Back; docker compose up -d`.**
빠른 진단: `GET /chat/{아무 uuid}` → 404면 DB 정상, 503이면 DB 끊김.

### 분석 진행 표시 - 2026-08-16
목적: `/analyze` 응답이 올 때까지 버튼 문구("분석 중…")만 바뀌어서, 사용자가 멈춘 건지
진행 중인지 알 수 없었다.
- [x] `Front/src/Progress.tsx` 신설 — 스피너 + 3단계 체크 목록 + 경과 시간
  - **경과 시간 기반 추정이다.** `/analyze`가 단일 POST라 서버 진행을 알 방법이 없다.
    SSE로 실제 단계를 흘리는 안과 비교했고, 백엔드 리팩터링 없이 얻는 체감 개선이
    커서 프론트만으로 결정 (실제 진행과 어긋날 수 있음은 감수)
  - 전환 시점 0s / 1.5s / 5s — 근거는 위 실측(check 1회, fetch 3~6회, 나머지는 전부 LLM)
  - 마지막 단계는 끝내지 않고 계속 진행 중으로 둔다 (완료 시점을 알 수 없다)
  - 표시하는 시간은 단계별이 아니라 **전체 경과**. `aria-hidden` — 1초마다 바뀌어
    `role="status"` 낭독이 계속 끊긴다
- [x] `App.tsx` — `{loading && <AnalyzeProgress />}`, 안내 문구는 `!loading` 조건 추가
- [x] `App.css` — `.progress` 블록. 신규 CSS 변수 없음. `prefers-reduced-motion`이면 회전 느리게
- [x] 검증: `tsc --noEmit` 통과, `npm run build` 성공, 산출물에 클래스 7종·문구 5종 포함 확인,
      pytest 115 passed / 19 skipped(DB 없는 환경 — 백엔드 무수정 확인). LLM 실호출 없음
  - 캐시 히트는 1초 안에 끝나 첫 단계만 스치듯 보인다 (의도된 동작)
  - **화면 렌더링은 미확인** (Chrome 확장 미설치)

### 미완료
- [x] 브라우저에서 대화 UI 눈으로 확인 + `/chat` 실호출 - 2026-08-18 (Phase 3)
- [x] `rate_limit.json`·`runs.jsonl`의 DB 이전 - 2026-08-19
      ('rate_limit.json·runs.jsonl 의 DB 이전' 절. DB 우선 + 파일 폴백.
      실측: 프로세스 5개에서 파일 3/50 · DB 50/50)
- [x] 참조 없는 오래된 스냅샷 정리 — `services/cleanup.py` + `/admin/api/cleanup` - 2026-08-18
      (기본 dry-run. 대화가 참조하는 스냅샷과 저장소별 최신은 지우지 않는다. **아직 실행은 안 했다**)
- [x] 빈 `chat_sessions` 누적 — **원인을 없앴다** - 2026-08-19 ('미뤄 둔 과제 정리' 절)
      당시 "그 정보는 localStorage 에만 있어 서버가 먼저 알 방법이 없다"로 닫았는데,
      **클라이언트가 알려주면 된다.** `AnalyzeRequest.session_id` 로 받아 같은 스냅샷이면 재사용

