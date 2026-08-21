# plan.md

RepoDive — GitHub 레포를 읽고 프로젝트/기술스택을 요약하는 어시스턴트.

> **문제·해결 색인은 [TROUBLESHOOTING.md](TROUBLESHOOTING.md) 에 있다.**
> 이 문서는 **시간순 작업 로그**다 — 무엇을 언제 왜 했는지.
> 증상으로 찾을 때(전에 이걸 겪었나?)는 그쪽을 본다.

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

## Stage 3: RAG (대화에서 실제 코드를 보게 한다) - 2026-08-16 착수

**문제:** 대화가 "추정"으로만 답한다. `context_builder.py`가 넣는 건 README·매니페스트·
**파일 경로 목록**뿐이고 소스 본문은 한 줄도 없다 (`CHAT_SYSTEM_PROMPT`에도 그렇게 명시돼 있다).
사용자가 "로그인 부분 어디야?" → 파일명만 보고 추정 → "안에 코드는 못 보는거야?" → "네, 맞습니다".

**대안 검토:** 온디맨드 파일 읽기(tool use)를 권장했으나 **사용자가 RAG를 선택**.
tool use는 임베딩·벡터DB 없이 필요한 파일만 읽는 방식이고, RAG는 대형 레포까지 대비하는 방향.

**확정된 선택지**
- 임베딩: **로컬 fastembed(ONNX)** — 무과금. torch 불필요(onnxruntime만). 검증도 실호출로 가능
- 청킹: **tree-sitter 구문 파서** — 함수/클래스 경계를 정확히 자른다
- 인덱싱 시점: **첫 질문 때 lazy** — `/analyze`는 지금 속도를 유지하고, 요약만 보고 떠나는
  사용자에게는 비용 0. 대신 첫 질문이 느려지므로 로딩 표시가 필요하다

**Python 3.14 호환성 (착수 전 실측)**
- `tree-sitter 0.26.0` cp314 wheel 있음 / `tree-sitter-language-pack 1.14.3`은 **cp310-abi3**라 3.14 안전
- `tree-sitter-languages`(구 패키지)는 3.14 배포판 없음 → language-pack 을 쓴다
- `fastembed 0.8.0`, `pgvector 0.5.0` 순수 파이썬. torch도 cp314 wheel이 있지만 불필요

**파일 배치** — CLAUDE.md §6은 "벡터DB/청킹/임베딩 → `app/core/`"지만, SQL 접근만은
`app/db/chunks.py`에 둔다. §6의 '벡터DB'는 Chroma 같은 별도 DB를 상정한 문구이고,
지금은 PostgreSQL+pgvector라 `repos.py`·`chats.py`와 같은 성격이다.

### 단계
- [x] 0. 의존성 설치 + requirements.txt - 2026-08-16
  - fastembed 0.8.0(onnxruntime 1.28) / tree-sitter 0.26 / language-pack 1.14 / pgvector 0.5
  - **torch 불필요** — fastembed가 ONNX로 돈다 (torch도 cp314 wheel은 있지만 122MB를 아꼈다)
  - 검증: 임베딩 차원 768, 한국어 질문 → 인증 코드 0.3802 vs 무관 코드 0.0065(58배 격차),
    tree-sitter Java class/method·Python function 경계 정확
- [x] 1. 소스 파일 수집 — `github_client.fetch_source_files()` - 2026-08-16
  - **tarball 1회 요청**으로 받는다. `/contents`를 파일마다 부르면 요청이 파일 수만큼 늘어
    rate limit이 먼저 터진다 (47개 파일 → 48회 vs 2회)
  - `ref`를 비우면 GitHub이 기본 브랜치를 쓴다 → 브랜치 이름 알아내려 check를 또 부를 필요 없음
  - 상한은 받으면서 검사(`iter_bytes`) — 다 받은 뒤 재면 이미 메모리를 먹은 뒤다
  - `app/core/languages.py`로 확장자↔언어 매핑을 단일화 (수집과 청킹이 같은 판단을 해야 한다)
  - migrations는 일부러 제외 목록에서 뺐다 — 노이즈지만 "DB 스키마" 질문의 유일한 근거일 때가 있다
  - 검증: 실제 레포 47개 파일 / 111,857자 / 1.4초, SecurityConfig.java 본문 수신 확인
- [x] 2. pgvector 도입 - 2026-08-16
  - 이미지 `postgres:17` → `pgvector/pgvector:pg17` (같은 pg17이라 pgdata 볼륨 그대로)
  - **교체 전 `Back/cache/pre_pgvector_backup.sql`로 백업** — 사용자가 만든 대화가 들어 있었다
  - `code_chunks`는 repo가 아니라 **snapshot**에 매단다. 세션이 보는 코드 버전이 스냅샷으로
    확정돼 있어(chat_sessions.snapshot_id), 저장소가 갱신돼도 진행 중 대화는 자기 코드를 계속 본다
  - `repo_snapshots.indexed_at` 추가 — 청크 0개(소스 없는 repo)를 매번 재인덱싱하지 않기 위해
  - 검증: 대화 6행 전부 보존, pgvector 0.8.6, HNSW 인덱스 생성, 코사인 거리 정렬 정상
- [x] 3. `app/core/chunker.py` — tree-sitter 청킹 - 2026-08-16
  - **컨테이너(클래스·인터페이스)는 크기와 무관하게 메서드로 내려간다.** 클래스를 통째로 두면
    그 벡터가 "클래스가 하는 모든 일"의 평균이 되어 어떤 질문에도 어중간하게 걸린다
    (실측: 컨트롤러 클래스들이 질문과 무관하게 늘 상위 1~4위를 차지했다)
  - import 노드 제외 → 청크 122개 중 47개가 import였다. 중앙값 402자 → 1068자
  - 주석만 있는 헤더(`/*작성자*/` + 선언)도 제외 — 파일마다 모양이 같아 서로 유사도가 높다
  - 40자 미만 부스러기 제거, 파싱 실패는 라인 기준 폴백(검색에서 통째로 사라지면 안 된다)
  - 검증: 실제 레포 145청크/0.09초, MAX 초과 0개, 라인 번호 정합 145/145, pytest 14건
- [x] 4. `app/core/embeddings.py` - 2026-08-16
  - 모델 **지연 로드** + 스레드 락 (import 시 올리면 모델을 안 쓰는 요청·테스트도 비용을 문다)
  - 캐시 경로를 `Back/cache/models`로 고정 — 기본값은 OS 임시 폴더라 윈도우가 청소하면 655MB 재다운
  - **`batch_size=8`** — 기본값(256)보다 1.7배 빠르다. 배치가 크면 짧은 청크까지
    가장 긴 청크에 맞춰 패딩돼 계산이 낭비된다 (실측 461ms → 265ms/청크).
    `parallel=0`(8코어)은 윈도우 프로세스 생성 비용 때문에 효과 없었다
- [x] 5. `app/db/chunks.py` — 저장·검색 - 2026-08-16
  - **`%s::vector` 캐스트 필수.** `register_vector`를 등록해도 파이썬 list는 `float8[]`로 가고
    `<=>`는 vector끼리만 정의돼 있어 UndefinedFunction이 난다 (어댑터는 numpy와 결과 파싱 담당)
  - 삭제→삽입→시각기록을 한 트랜잭션 — '반쯤 인덱싱된' 상태로 남지 않게
- [x] 6. `app/services/indexer.py` — lazy 인덱싱 - 2026-08-16
  - 스냅샷별 락으로 동시 질문의 중복 인덱싱 방지 (다른 저장소끼리는 안 막는다)
  - 실패는 예외를 올리지 않는다 — 코드 근거 없이 답하는 게 질문을 막는 것보다 낫다
  - 검증: 첫 호출 145청크 저장, 두 번째 호출 0.03초로 건너뜀
- [x] 7. `/chat` 연결 - 2026-08-16
  - **검색된 코드는 마지막 사용자 메시지에만 붙인다.** 질문마다 내용이 달라지므로
    `cache_control`이 걸린 스냅샷 블록에 넣으면 매 질문이 캐시를 깨뜨려
    스냅샷 전체를 정가로 다시 계산하게 된다 → 테스트 2건으로 고정
  - `CHAT_SYSTEM_PROMPT` 갱신 — "파일 목록에는 내용이 없습니다"가 더는 사실이 아니다
  - `chats.get_session()`에 owner/name(소문자 키) 추가 — 인덱싱이 GitHub을 부를 때 쓴다
  - main.py lifespan에서 모델 예열(별도 스레드) — 안 하면 첫 질문이 모델 로딩까지 기다린다
- [x] 8. 프론트 — 첫 질문 대기 안내 - 2026-08-16
  - 8초를 넘기면 "코드를 처음 읽는 중" 안내를 덧붙인다. 두 번째 질문부터는 뜨기 전에 끝난다

### 검증
- [x] pytest **153 passed** (기존 134 + 신규 19: chunker 14, 캐시 지점 3, /chat 연결 2)
- [x] 실측: 사용자 본인 레포(`jjunyuongv/Air`)로 수집→청킹→임베딩→검색 왕복.
      **"로그인 관련 부분은 어디에 있어?" → SecurityConfig.java 89-95행**
      (`customAuthenticationSuccessHandler`) 1위. 화면에서 추정만 하던 그 질문이다
- **Claude 실호출은 안 했다** (임베딩은 로컬이라 무과금)

### 남은 문제 / 다음 과제
- [x] **첫 질문이 느리다** → Stage 3.6 에서 (b) 백그라운드 인덱싱으로 해결 - 2026-08-17.
      임베딩 자체도 배치 크기 조정으로 2.4배 빨라졌다. 소형 모델 안(a)은 여전히 미검토
- [x] **검색 품질 미검증** → Stage 3.5 에서 평가 하네스(질의 33개)를 만들어 해소.
      2026-08-18 에는 화면에서도 판정했다 (Phase 3 / marryday 확인)
- [x] **작은 저장소는 RAG 없이 통째로 넣어도 된다** → **'1번 과제 완료 — 작은 저장소 RAG 우회'**
      에서 해결 - 2026-08-19. 임계값 57,000토큰(비용 4배 규칙에서 역산),
      `indexer._try_full_injection()` 이 수집 직후 판정, 인용 정확도 0.75 → 1.00
  - 당시 적어 둔 "air 11만 자 ≈ 30k 토큰"은 **틀린 추정이었다** — 실측 62,380토큰이라
    그 저장소는 임계값에 걸려 탈락한다 (자/토큰 비율을 3.2로 잡았는데 실측 2.05)
- [x] 재인덱싱 트리거 — Stage 4 에서 해결 (규칙 해시 + `/admin/api/rebuild-index` + 큐).
      옛 빌드 누적도 `KEEP_BUILDS` 보관 정책으로 정리된다 - 2026-08-18

**주의:** 도커 이미지 교체 시점에 `repos` 1행 / `repo_snapshots` 1행 / `chat_sessions` 1행 /
`messages` 6행(사용자가 직접 만든 대화)이 들어 있었다. 볼륨을 지우지 말 것.

## Stage 3.5: 검색 품질 개선 - 2026-08-16

**문제:** 한국어로 물으면 못 찾는다. 같은 정답을 두고 질의 표현만 바꿔 재보니
"PasswordEncoder 어디서 만들어?"는 1위인데 "비밀번호는 어떻게 암호화해?"는 17위였다.

**원인:** 현재 모델 `jina-embeddings-v2-base-code`의 "Multilingual"은
**프로그래밍 언어 30종**을 뜻하고 자연어는 **영어 전용**이다. 한국어 지원이 애초에 없었다.
앞서 "로그인" 질의가 맞았던 것도 그 코드에 한국어 주석(`logger.info("로그인 성공!...")`)이
있어 한국어끼리 맞은 것이지 한국어→영문 매핑이 된 게 아니었다.

### STEP 0. 평가 하네스 - 완료
- [x] `tests/search_eval_dataset.py` — 질의 17개(한국어 개념어 12 + 영문 식별자 5)
  - **특정 문장을 맞히는 게 목표가 아니다.** 보안·전자결재·일정·채팅·회원·신고·유틸에
    걸쳐 흩어 놓았다. 한 질의에 맞춰 튜닝하면 그것만 좋아지고 나머지가 나빠진다
  - 정답은 청크 id 가 아니라 **(파일 접미사 + 포함 문자열)** — 청킹 규칙을 바꾸면
    청크 경계가 달라져 id 기반 정답은 전부 무효가 된다
  - 저장소 소스를 먼저 읽고 **정답이 실재하는 질의만** 채택했다
- [x] `tests/test_search_quality.py` — 전체 순위·MRR·Recall 측정, 인덱싱 비용·메모리·잘림 수 기록
- [x] `app/services/search_eval_log.py` — 측정 기록 저장·조회 (`logs/search_evals.jsonl`)
  - 관리자 페이지가 같은 파일을 읽으므로 읽기 로직이 테스트 안에 있으면 안 된다
- [x] `tests/conftest.py` — `evaluation` 마커 등록 + **기본 실행에서 제외**
  - 일반 `pytest` 한 번에 수 분이 걸리면 아무도 테스트를 안 돌린다

**baseline (jina-embeddings-v2-base-code, 768차원)**

| 구분 | MRR | Recall@8 | 평균순위 |
|---|---|---|---|
| 전체 17개 | 0.2528 | 0.35 | 51.25 |
| **한국어 12개** | **0.0665** | **0.17** (2/12) | **67.92** |
| 영문 식별자 5개 | 0.7000 | 0.80 | 1.25 |

인덱싱 145청크: 수집 1.3s · 청킹 0.03s · 임베딩 38.4s · 저장 0.25s, 피크 126MB, 잘림 0개

**측정하다 발견한 청킹 버그** — `id_04`(TextWebSocketHandler)는 순위가 아니라 **정답 자체가
인덱스에 없었다.** `public class ChatHandler extends TextWebSocketHandler` 줄이 어느 청크에도
없다. 클래스 헤더가 `MIN_CHUNK_CHARS`(200자)에 못 미쳐 통째로 버려진 것이다.
클래스가 무엇을 상속하는지가 사라지는 손실이라 STEP 2에서 고친다.

### STEP 1. 다국어 모델 교체 + A/B - 진행 중
- [x] **모델 조사** — `fastembed 0.8.0`이 이미 최신이고, `TextEmbedding`/`SparseTextEmbedding`/
      `LateInteractionTextEmbedding` 전 클래스에 **`bge-m3`는 없다.**
      E5 계열은 `intfloat/multilingual-e5-large` 하나뿐이라 그것으로 간다.
      `paraphrase-multilingual-*`은 STS 모델이라 검색에 부적합해 제외
- [x] **접두어를 직접 붙인다** — fastembed 의 `query_embed()`는 접두어를 붙여주지 않고
      `embed()`를 그대로 호출할 뿐이다(`text_embedding_base.py:57-61`). E5 는 접두어가
      필수라 빠지면 측정이 무효가 되므로 `config.EMBEDDING_QUERY_PREFIX`/`PASSAGE_PREFIX`로
      명시 부착하고 테스트로 고정했다
  - `.env` 에 쓸 때는 **따옴표 필수** — 파서가 끝 공백을 잘라 `query:비밀번호...`가 된다
- [x] **차원별 테이블** — `vector(N)`은 차원이 고정이라 1024 벡터를 `vector(768)` 컬럼에
      넣을 수 없다. model 이름 컬럼을 추가하는 방식으로는 A/B 가 불가능해서
      `code_chunks_1024`를 따로 만들었다. 기존 `code_chunks`(768)는 손대지 않는다
  - `chunks.py` 네 함수가 `table` 을 받는다(기본값 `config.CHUNK_TABLE`).
    테이블명은 `psycopg.sql.Identifier` 로 조립
  - `is_indexed()`는 `repo_snapshots.indexed_at` 이 아니라 **해당 테이블의 청크 존재 여부**로
    판단하도록 바꿨다 — 테이블이 둘이 되면서 시각 하나로는 어느 쪽이 끝났는지 못 가린다
- [x] e5-large 측정 및 baseline 대비 비교

**결과 (같은 청킹·같은 평가셋, 모델만 교체)**

| 구분 | jina-code 768 | e5-large 1024 | 변화 |
|---|---|---|---|
| **한국어 MRR** | 0.0665 | **0.4909** | **7.4배** |
| **한국어 Recall@8** | 0.17 (2/12) | **0.67 (8/12)** | **4배** |
| 한국어 평균순위 | 67.92 | 12.83 | 5.3배 개선 |
| 식별자 MRR | 0.7000 | 0.6000 | **14% 악화** |
| 식별자 Recall@8 | 0.80 | 0.80 | 동일 |
| 전체 MRR | 0.2528 | 0.5230 | 2.1배 |
| 임베딩 시간(145청크) | 38.4s | 73.2s | 1.9배 느림 |
| 모델 크기 | 655MB | 2,149MB | 3.3배 |
| **잘린 청크** | 0개 | **15개 (10.3%)** | 악화 |

한국어 12개가 **전부** 좋아졌다. 특히 ko_08 101→1, ko_10 121→22, ko_06 55→1.
**나빠진 것은 id_01 하나뿐**(1위→2위). id_04 는 양쪽 다 실패인데 검색이 아니라 청킹 문제다.

**잘림 측정에서 실수할 뻔한 것** — 처음엔 "잘린 청크 0개"로 나왔다. 토크나이저에
truncation 이 걸려 있어 `encode()` 가 **이미 512 에서 잘라** 돌려주므로, 초과(>)로 세면
영원히 0 이 나온다. 도달(>=)로 세야 실제 15개가 잡힌다. 한도도 모델 이름으로 짐작하지 않고
`tokenizer.truncation["max_length"]` 에서 읽도록 고쳤다.

**피크 메모리 수치는 믿지 말 것** — `tracemalloc` 은 파이썬 힙만 재고 ONNX 런타임의
네이티브 할당은 못 본다. 2.1GB 모델이 68MB 로 찍힌 이유다. 프로세스 RSS 로 다시 재야 한다.

### e5 로 전환 - 2026-08-16
- [x] `Back/.env` 에 다섯 줄 추가 (모델·차원·질의 접두어·문서 접두어·테이블)
  - 접두어는 **따옴표 필수**. 없으면 파서가 끝 공백을 잘라 `query:질문` 이 된다
  - 되돌리려면 그 다섯 줄만 지우면 된다 — 768 인덱스가 `code_chunks` 에 그대로 남아 있다
- [x] `tests/test_embeddings.py` 에 설정 정합성 테스트 추가
  - E5 모델이면 접두어·차원·테이블이 아귀가 맞는지 확인한다. 설정 실수는 에러를 내지 않고
    **조용히 검색 품질만 떨어뜨리므로** 테스트로 잡는다
  - 같이 고친 것: `test_no_prefix_by_default` 가 .env 값을 읽어 전환하자마자 깨졌다.
    테스트가 개발자의 환경 설정에 좌우되면 안 되므로 monkeypatch 로 명시적으로 비우도록 수정
- [x] 실제 대화 스냅샷(#3)을 **미리 인덱싱** — 전환 직후 첫 질문이 76초를 기다리지 않게
- [x] 검증: 접두어 끝 공백 보존 확인, pytest **159 passed**, 검색 실동작 확인

**전환 후에도 남은 것** — "비밀번호는 어떻게 암호화해?" 의 상위 3개는 여전히
`AirApplication.main`, `SafeEduDTO` 헤더, `UserService` 헤더다(정답은 4위).
TOP_K=8 이라 답변 근거에는 들어가지만, 헤더 청크 노이즈는 STEP 2 에서 다룬다.

### 관리자 검색 품질 페이지 - 완료
- [x] `GET /admin/search` + `GET /admin/api/search-evals`, `templates/admin_search.html`
  - 모델별 최신 측정을 **나란히** 비교. 질의별 순위는 행=질의, 열=모델로 놓고
    기준 모델 대비 **좋아진 것은 초록, 나빠진 것은 빨강**으로 칠한다(나빠진 것도 그대로 보인다)
  - 이 화면은 **읽기 전용**이다. 측정은 `pytest -m evaluation` 이 한다
  - 나머지 admin 4개 페이지 네비게이션과 홈 카드에도 링크 추가
- [x] 검증: 5개 라우트 200, JS 참조 id 누락 없음, pytest **158 passed** (기존 153 + 접두어 5)

### STEP 3a. 도메인 용어 사전 자동 생성 - 2026-08-16

**왜.** 사용자는 "결재 승인은 어디서 처리해?" 라고 묻는데 코드에는 한국어가 한 글자도 없고
`ApprovalController.approve` 만 있다. 다국어 임베딩으로도 이 간극이 다 메워지지 않았다
(그 질의의 정답이 18위였다).

**왜 정적 파일이 아닌가.** 임의의 저장소를 받는 도구라 프로젝트마다 쓰는 말이 다르다.
이 저장소만 해도 `Cbn`=객실, `Mnal`=매뉴얼, `Atch`=첨부, `srch`=검색, `udt`=수정일시 처럼
그 팀만 아는 축약어를 쓴다. 그래서 **저장소를 처음 분석할 때 자동 생성**한다.

- [x] `app/core/symbols.py` — tree-sitter 로 정의 이름을 긁고 도메인 후보만 남긴다
  - camelCase·PascalCase·snake_case 분해 (`HTTPServer` → `HTTP`,`Server` 처럼 연속 대문자도 처리)
  - 3중 필터: 역할 꼬리표(Controller/Service/Repository…), 동작 머리말(get/set/find…),
    언어·프레임워크 어휘(String/List/spring…). 빈도순으로 상위 N개만 LLM 에 보낸다
- [x] `app/db/glossary.py` + `repo_glossary` 테이블 — **repo 단위**로 저장
  - 코드가 바뀌어 새 스냅샷이 생겨도 그 프로젝트가 쓰는 말은 잘 안 바뀐다.
    스냅샷마다 만들면 LLM 호출만 낭비된다
  - `lang` 열을 둔 이유는 **언어를 코드에 박지 않기 위해서**다. 지금은 `ko` 만 채우지만
    `GLOSSARY_LANGUAGES=ko,en` 처럼 늘리면 같은 표에 쌓인다
- [x] `claude_client.run_glossary()` — **저장소당 LLM 1회**. structured outputs 로 형식 강제
  - 응답 스키마에 언어를 키로 박지 않고 `lang` 을 값으로 뒀다 (스키마 변경 없이 언어 추가)
  - `_call()` 에 `output_format` 인자 추가 — 기존 effort 설정과 병합되게
- [x] `services/glossary.py` — 생성(LLM 1회)과 질의 확장(**호출 없음**)
- [x] `/analyze` 통합 — 사전이 이미 있으면 tarball 도 LLM 도 건너뛴다.
      실패는 경고만 (사전이 없으면 확장만 안 될 뿐 요약·대화는 그대로)
- [x] `indexer.search_code(expand=True)` — 임베딩 전에 사전으로 질의를 넓힌다
- [x] `tests/test_glossary.py` 12개 (LLM 없이 파싱·확장 로직 검증)

**실제 생성 결과** — 식별자 120개 → 용어 88개, 입력 1,993 / 출력 3,348 토큰, **$0.0375**, 29초.
축약어가 정확히 풀렸다: `Cbn`→객실·캐빈, `Mnal`→매뉴얼·지침서, `Atch`→첨부파일,
`Ctnt`→내용·본문, `logi`→물류, `phys`→실물·물리적 문서, `udt`→수정일시.

**측정 결과 (e5 + 사전, 같은 청킹)**

| 질의 | 사전 없음 | 사전 있음 |
|---|---|---|
| ko_04 결재 승인은 어디서 처리해? | 18 | **2** |
| ko_05 결재를 반려하는 기능이 있어? | 53 | **5** |
| ko_01 비밀번호는 어떻게 암호화해? | 4 | 6 |
| ko_03 관리자만 어떻게 막았어? | 47 | 56 |
| ko_06 일정을 저장하는 코드는? | 1 | 2 |
| ko_07 일정 삭제는 어떻게 동작해? | 1 | 3 |
| 나머지 11개 | — | 변화 없음 |

| 지표 | 사전 없음 | 사전 있음 |
|---|---|---|
| 한국어 Recall@8 | 0.67 (8/12) | **0.83 (10/12)** |
| 한국어 평균순위 | 12.83 | **8.67** |
| 한국어 MRR | 0.4909 | 0.4386 |

**지시받은 확인 대상(ko_04/ko_05)은 목표 달성.** 다만 **이미 잘 찾던 4개가 나빠졌다.**
MRR 이 떨어진 것은 1위였던 ko_06·ko_07 이 밀려서다 — MRR 은 1위를 크게 보상한다.
실사용 기준(TOP_K=8 안에 드는가)인 Recall@8 은 0.67 → 0.83 으로 올랐다.

**악화의 원인**: 확장은 이미 잘 맞는 질의에 노이즈를 더한다. "일정"이 `Schedule`·`Schedules`·
`event`·`Recurring` 을 한꺼번에 붙여 초점이 흐려지고, "관리자"의 `Admin` 은 SecurityConfig 보다
`/admin/**` 매핑이 많은 UserController 를 끌어올린다.

**사전이 못 잡은 것**: ko_10 "회원"(사전엔 `User`→사용자만), ko_11 "신고"(`Report`→보고서만).
LLM 이 코드 기준으로 옮기다 보니 사용자가 쓰는 다른 표현이 빠졌다.

### STEP 3a 되돌림 - 2026-08-16
측정 결과를 보고 **전부 제거**했다. 못 찾던 둘은 크게 좋아졌지만 이미 잘 찾던 넷이 나빠졌고,
확장한 식별자가 원래 질의의 초점을 흐리는 것이 원인이라 부분 수정으로 해결될 문제가 아니었다.

지운 것: `core/symbols.py`, `services/glossary.py`, `db/glossary.py`, `tests/test_glossary.py`,
`repo_glossary` 테이블(88행), `claude_client.run_glossary()` + 응답 스키마,
`config.GLOSSARY_*`, `/analyze` 의 사전 생성 단계, `search_code(expand=...)`.

같이 되돌린 것 — 사전 때문에 넣었던 곁가지들이라 남기면 죽은 코드가 된다:
- `_call(output_format=...)` (structured outputs) — 쓰는 곳이 사전뿐이었다
- `test_search_quality.py` 의 `EVAL_DISABLE_GLOSSARY` 분기와 `import os`

남긴 것:
- **요약 생성 단계는 그대로** (사전과 분리된 기능이었다)
- `search_eval_log.latest_per_model()` 이 note 를 키에 포함하는 것 — 사전 A/B 때문에
  고쳤지만 조건이 다른 실험을 구분하는 일반적인 개선이라 유지
- `schema.sql` 에 왜 뺐는지 주석만 남겼다. 다시 붙일 자리를 표시해 둔 것

**DROP 을 schema.sql 에 두지 않았다** — 그 파일은 기동할 때마다 멱등 실행되므로
DROP 이 영구히 남는다. CREATE 만 지우고 테이블은 일회성 스크립트로 떨궜다.

측정 기록도 지웠다 — `logs/search_evals.jsonl` 의 사전 실험 2건과 그 백업 파일.
`/admin/search` 에는 이제 jina(768) 과 e5(1024) 둘만 남는다.
(`runs.jsonl` 에는 사전 호출이 없다. 스크립트로 직접 만들어 `/analyze` 경로를 타지 않았다.)

검증: pytest **159 passed** (사전 12개가 빠져 STEP 3a 직전 수치로 정확히 복귀).
평가셋 재실행으로 **Recall@8 0.67 / ko_04 18위 / ko_05 53위** 복귀 확인 — 17개 질의 전부
사전 도입 전과 같아 다른 변경이 섞이지 않았음을 확인했다.

## Stage 3.6: 큰 저장소 대응 — 백그라운드 인덱싱 - 2026-08-17

**증상 두 가지** (사용자가 화면에서 겪음):
질문할 때마다 "코드를 처음 읽고 있습니다" 안내가 뜨고, 챗봇이 "소스 코드가 포함되지
않았습니다"라며 파일 목록만 보고 답했다.

**원인.** `jjunyuongv/marryday` 의 tarball 이 `MAX_ARCHIVE_BYTES`(80MB)를 넘어
수집이 413 으로 실패 → 청크 0개 → 검색 결과 없음 → 코드 없이 답변. 게다가
`chunks.is_indexed()` 가 **청크 행 존재 여부**로 완료를 판단해서 질문마다 80MB 를
다시 받았다(`runs.jsonl` 의 chat 6건 전부 `fetch_ms` 9~11초, air 는 6~8ms).
- 이건 회귀였다. `schema.sql` 과 `indexer.py` 주석은 "청크 0개도 완료로 남긴다"고
  적어 뒀는데, STEP 1(차원별 테이블)에서 판단 기준을 `indexed_at` → 청크 존재로
  바꾸면서 깨졌다. 테이블이 둘이 되어 시각 하나로는 못 가린 게 이유였다
- 프론트 안내는 **8초만 넘으면** 뜨는 시간 추정이라, 이미 인덱싱된 저장소에서도 떴다

**규모** (상한을 풀고 실측): 소스 181파일 / 226만 자 / **청크 1,683개**.
수집 15~20초, 청킹 1.3초, 저장 3초, **임베딩 29분**. 첫 질문에 동기로 붙일 수 없다.

### 임베딩 처리량 점검
- [x] 배치 크기 재측정 — **`EMBED_BATCH_SIZE` 8 → 32** (2.4배 빠름)
  - 200청크 실측: 8 = 2,461ms/청크 · 16 = 1,616 · **32 = 1,032** · 64 = 1,173
  - 8 은 jina-code(768) 시절 값이었다. 모델을 바꾸면 최적 배치도 바뀐다
  - `threads` 를 코어 수로 명시하면 오히려 느렸다(onnxruntime 기본 0 = 자동이 낫다)
  - 이미 배치 호출이었고(개별 호출 아님), DB 는 `executemany`, 모델은 싱글턴 + 예열 —
    나머지 후보는 전부 병목이 아니었다

### 백그라운드 인덱싱
- [x] `MAX_ARCHIVE_BYTES` 80MB → **500MB**, 받는 버퍼를 `SpooledTemporaryFile`(32MB 초과분은
      디스크)로. 상한만 올리면 수백 MB 가 전부 메모리에 올라온다
- [x] `snapshot_index_status` 테이블 — `(snapshot_id, table_name)` 키,
      status pending/running/completed/failed + `chunks_total`/`chunks_done`/`error`
  - `table_name` 이 키에 있는 이유: 차원별로 청크 테이블이 갈려 스냅샷 하나가 모델마다
    다른 진행 상태를 가진다
  - **완료 판정을 여기로 옮겼다** (`chunks.is_indexed()` 제거 → `index_status.is_completed()`).
    청크 0개도 완료는 완료 — 위 회귀의 근본 수정이다
  - `schema.sql` 에 멱등 백필 — 이미 인덱싱된 스냅샷(air 145청크)을 completed 로 채운다.
    안 하면 기동하자마자 통째로 재인덱싱한다
  - `begin()` 은 판정과 표시를 **한 문장**(INSERT … ON CONFLICT … WHERE)으로 한다.
    조회 후 갱신으로 나누면 동시 요청 둘이 함께 인덱싱을 시작할 수 있다
  - `reset_running()` — 기동할 때 남아 있는 running 을 pending 으로. 인덱싱 스레드는
    프로세스와 함께 사라져서, 안 되돌리면 재시도가 영원히 막힌다(단일 프로세스 전제)
- [x] `indexer.ensure_indexed()`(동기) → `indexer.start()`(논블로킹 + 데몬 스레드)
  - 진행률은 **청크 수 기준**. `embed_documents(texts, on_progress)` 가 배치마다 보고한다
  - 청크 저장은 끝에 한 번(한 트랜잭션) — 부분 인덱스를 검색에 쓰지 않으므로 중간 저장의
    이득이 없다
- [x] `/analyze` 가 요약을 돌려주기 직전 `start()` — **캐시 히트 경로에서도** 부른다
      (요약만 재사용할 뿐 그 스냅샷은 아직 인덱싱 전일 수 있다)
- [x] `/chat` — **완료됐을 때만 검색한다.** 진행 중이면 요약만으로 답하고 색인을 시작시킨다
  - 부분 인덱스로 검색하면 아직 임베딩하지 않은 코드가 '저장소에 없는 코드'처럼 보여
    틀린 답을 만든다. 테스트로 고정했다
- [x] `GET /chat/{session_id}/index` — status·진행·`eta_seconds`·error. 외부 호출 0회라 제한 없음
  - ETA 는 지금까지의 실제 속도로 계산한다(고정값은 기기·저장소마다 틀린다)
  - **기준 시각은 임베딩 시작 시점**(`set_total()` 이 `started_at` 을 다시 찍는다).
    수집 시작부터 재면 tarball 15~20초가 청크당 속도에 섞여 29분짜리가 58분으로 나온다 — 실측함
- [x] 프론트 — 색인 배너(진행/남은 시간/실패 사유) + 3초 폴링, **8초 문구 제거**
  - 시간 추정이라 이미 인덱싱된 저장소에서도 떴다. 그게 "매번 내려받느냐"는 오해의 원인이었다

### 검증
- [x] pytest **179 passed** (기존 159 + 신규 20: index_status 8, indexer 6, /chat·상태 API 6)
- [x] 실측(**LLM 호출 없음** — marryday 는 요약 캐시 히트라 과금 0):
      기동 시 백필로 air 4행 completed / marryday `/analyze` → 색인 running →
      1,683청크 확정 → 진행률·ETA 가 실제 속도로 수렴 → **22분 만에 completed(1,683청크)**
- [x] 검색 확인 — 사용자가 화면에서 실패했던 그 질문이 이제 맞는다:
      "body_analysis.py 안에 코드 보여줘" → `routers/body_analysis.py` 569-633행 **1위**,
      "체형 분석은 어떻게 해?" → `BodyAnalysis.jsx`, "이미지 합성은 어디서 처리해?" → `composition.py`
- **화면 렌더링은 미확인** (Chrome 확장 미설치). 색인 배너는 사용자가 직접 확인

### 첫 화면 분리 - 2026-08-17
목적: 처음 들어오면 상단 바에 작은 입력창 하나뿐이라 무엇을 하는 도구인지, 어디에
입력해야 하는지가 약했다. 분석 전에는 링크 입력만 남기고, 분석 후에는 지금 화면을 그대로 쓴다.
- [x] `App.tsx` — `result` 가 없으면 **랜딩만 렌더**(상단 바·레포 헤더·사이드바 없음)
  - 폼 JSX 를 `urlForm` 변수로 뽑아 랜딩과 상단 바가 **같은 폼**을 쓴다. 크기는 감싼 쪽이 정한다
  - 분석 중에는 폼 자리에 `<AnalyzeProgress />` 가 들어간다 — 화면이 튀지 않는다
  - 결과 화면의 `{error && ...}` 는 제거했다. 분석을 시작하면 `result` 가 null 이 되어
    에러는 항상 랜딩에서 표시된다 (죽은 분기였다)
  - `.empty` 문구는 랜딩 리드 문구로 옮겨가 사라졌다 (CSS 규칙도 제거)
- [x] `App.css` — `.landing` 블록 추가. 기존 `.topbar input/button` 규칙에 `.landing` 선택자를
      더해 공통 스타일을 나눠 쓰고, 크기(padding·font-size)만 랜딩에서 키웠다. 신규 CSS 변수 없음
  - `min-height: 100vh` + padding 이라 `box-sizing: border-box` 가 없으면 스크롤바가 생긴다 (실제로 생겨서 고침)
  - 600px 이하에서는 폼이 세로로 쌓인다
- [x] 검증: `tsc --noEmit`·`npm run build` 통과, **브라우저에서 눈으로 확인**(Chrome 확장 연결됨) —
      랜딩(상단 바 없음, 스크롤바 없음) → marryday 분석(요약 캐시 히트라 LLM 호출 0) →
      기존 2컬럼 결과 화면으로 전환 확인
  - 분석 중 화면(가운데 진행 표시)은 캐시 히트라 순식간에 지나가 캡처하지 못했다

## Stage 3.7: STEP 2 청킹 개선 - 2026-08-17 진행 중

Stage 3.5 에서 예고만 하고 미뤄 둔 세 결함을 **하나씩** 고치고 매 단계 평가한다
(`pytest -m evaluation`, 주 지표 Recall@8). 대상은 평가 저장소 `jjunyuongv/Air`.

- [x] **2a. 클래스 헤더 손실** — 짧은 헤더를 버리던 조건 제거 (`_has_code` + MIN_CHUNK_CHARS 검사)
  - `public class ChatHandler extends TextWebSocketHandler` 가 인덱스에 없어 id_04 는
    **순위가 아니라 정답 자체가 부재**했다. 이제 17/17 전부 인덱스에 존재한다
  - 헤더가 살아나며 `_merge_small` 의 **연쇄 병합**이 메서드 둘을 한 청크로 뭉치게 만들어,
    "작은 조각은 이웃 하나에만 붙는다"로 바꿨다 (테스트 2개 추가로 고정)
  - 테스트 샘플(JAVA)의 메서드가 200자 미만이라 병합 규칙에 걸렸다 → 실제 코드 크기로 키움
- [x] **2b. 청크 잘림** — `MAX_CHUNK_CHARS` 2400 → **800**, 라인 분할에 3줄 겹침 추가
  - 상한은 실측에서 역산했다: e5-large 한도 512토큰, 문자/토큰 비율 최악 **1.60**
    (한국어 주석이 섞인 청크). 512 × 1.60 ≈ 819 → 접두어 몫을 빼고 800
  - 잘린 14개 중 **10개가 CSS**였다 (한국어 주석 + 긴 선언)
  - `indexer._warn_if_truncated()` — 잘림은 조용히 일어나므로 인덱싱 후 경고를 남긴다
- [x] **2c. 저정보 청크 감점** — 진입점·선언만 있는 헤더·스타일시트를 **제외가 아니라 감점**
  - **감점은 검색 단계에서 한다** (`indexer.search_code`). 저장 단계에 플래그를 두면 규칙을
    바꿀 때마다 재인덱싱(6분)이 필요한데, 검색 단계면 벡터가 그대로라 **감점값 A/B 가 수초**다
  - 후보를 `limit × 5` 로 넓게 가져와 다시 세운다 — 상위 limit 만 가져와 감점하면
    감점 대상에 밀려 못 들어온 진짜 근거가 영영 안 보인다
  - **CSS 가 노이즈의 주범이었다.** 한국어 주석(`/* 페이지네이션 링크 스타일 */`)이 많아
    한국어 질의와 곧잘 맞는다. 진단해 보니 ko_03·ko_05·ko_08 의 상위 절반이 CSS 였고,
    2b 에서 잘게 쪼개지며 **온전히 임베딩되어 오히려 더 잘 맞게 된** 역설이 있었다
  - 저정보 판정 62/236 = CSS 35 + Java 헤더 27(작성자 주석 + 필드 선언만)
  - **상속·구현 선언은 감점 제외** — id_04 의 정답이 바로 그 헤더다. 선언만 있다고
    뭉뚱그리면 2a 에서 살린 것을 2c 가 도로 망가뜨린다 (테스트로 고정)
  - 감점값 0.03: 실측에서 0.03 부터 한국어 Recall@8 이 회복되고 **0.05 이상은 변화가 없다**
    (저정보가 완전히 밀려 사실상 '제외'가 되는 구간) → 포화 직전에서 멈췄다

**단계별 측정 (같은 모델·같은 평가셋)**

| 지표 | baseline | 2a | 2b | **2c (최종)** |
|---|---|---|---|---|
| 잘린 청크 | 15 | 14 | **0** | **0** |
| 청크 수 | 145 | 182 | 236 | 236 |
| id_04 순위 | **없음** | 1 | 1 | **1** |
| 식별자 Recall@8 | 0.80 | 1.00 | 1.00 | **1.00** |
| 식별자 MRR | 0.6000 | 0.8667 | 0.8667 | **0.9000** |
| 한국어 Recall@8 | 0.67 | 0.58 | 0.50 | **0.67** |
| 한국어 MRR | 0.4909 | 0.4573 | 0.4122 | **0.5028** |
| 한국어 평균순위 | 12.83 | 14.75 | 22.67 | **11.25** |
| 전체 Recall@8 | 0.71 | 0.71 | 0.65 | **0.76** |
| 전체 MRR | 0.5230 | 0.5777 | 0.5458 | **0.6196** |

**baseline 대비 모든 지표가 같거나 좋아졌다.** 2a·2b 가 한국어를 깎아 먹은 것은
"살려낸 헤더와 잘게 쪼갠 조각이 상위를 차지"한 탓이었고, 2c 가 정확히 그것을 되돌렸다.
개별로는 ko_01 4→1, ko_03 47→30, ko_10 22→15, id_04 없음→1 이 크게 좋아졌고,
ko_08(1→5)·ko_12(2→6) 는 baseline 보다 나빠졌지만 둘 다 Recall@8 안에 있다.

- [x] 검증: pytest **188 passed**(신규 9: 청킹 2, 감점 7), 평가 하네스 4회 실행 기록
      (`/admin/search` 에서 비교 가능). LLM 실호출 없음 — 임베딩은 로컬이다

### 평가셋 확장 — 다른 언어로 - 2026-08-17
목적: 위 세 수정이 **Java 저장소 하나에만 맞춘 것은 아닌지** 확인한다.

- [x] `tests/search_eval_dataset.py` — `EVAL_SETS` 구조로 바꾸고 `jjunyuongv/marryday`
      (FastAPI 86 py + React) 질의 **16개** 추가 (한국어 10 + 식별자 6)
  - 여기서도 저장소 소스를 먼저 읽고 **정답이 실재하는 질의만** 채택했다 (후보 17개 전부 확인)
  - `py_id_06`("BaseModel 을 상속한 요청 스키마")은 2a 가 Java 밖에서도 듣는지 보는 질의다
- [x] `test_search_quality.py` — 저장소별로 `parametrize`. `search_eval_log.latest_per_model()`
      키에 **repo 추가** (없으면 저장소가 다른 두 측정이 한 칸에 겹쳐 하나가 사라진다)
- [x] **확장하자마자 결함이 하나 나왔다** — `chunk_file()` 이 "정의가 아닌 최상위 요소"를
      **크기 검사 없이** 통째로 넣고 있었다. Java 에는 그런 요소가 거의 없어 안 보이다가
      Python/JS 에서 터졌다: `document.addEventListener(...)` 한 덩어리 4,115자,
      긴 프롬프트 상수 3,213자, `if __name__ == "__main__":` 블록 → **청크 11개가 잘렸다**
  - 그 분기도 `MAX_CHUNK_CHARS` 를 넘으면 `_line_chunks` 로 내려보내도록 수정
- [x] 청킹 검증(임베딩 없이): 두 저장소 모두 **잘린 청크 0 · 정답 부재 0**

| 저장소 | 파일 | 청크 | 잘림 | 최대 토큰 | 저정보 |
|---|---|---|---|---|---|
| air (Java) | 47 | 236 | 0 | 375 | 62 (26%) |
| marryday (Python/JS) | 181 | 4,364 | 0 | **507** | 1,666 (39%) |

**marryday 의 507 토큰은 한도(512)에 거의 닿아 있다.** 한국어 비중이 아주 높은 청크는
800자로도 아슬아슬하다는 뜻이라, `indexer._warn_if_truncated()` 경고를 남겨 둔 이유가 여기 있다.

- [x] marryday 순위 측정 — **16/16 정답 발견, 한국어 Recall@8 0.80**

| 지표 | air (Java) | marryday (Python/JS) |
|---|---|---|
| 한국어 Recall@8 | 0.67 | **0.80** |
| 한국어 MRR | 0.5028 | 0.5399 |
| 한국어 평균순위 | 11.25 | 30.8 |
| 식별자 Recall@8 | 1.00 | 0.83 |
| 식별자 MRR | 0.9000 | 0.4846 |
| 전체 Recall@8 | 0.76 | **0.81** |
| 정답 부재 · 잘린 청크 | 0 · 0 | 0 · 0 |

**청킹 개선은 Java 전용이 아니었다.** Python/JS 저장소에서도 한국어 질의 10개가 전부
잡히고 Recall@8 0.80 이다. `py_id_06`(BaseModel 상속) 5위 → **2a 가 Python 에서도 듣는다.**

> **주: 이 근거는 뒤에 보강됐다** (평가셋 v2, 2026-08-19). 당시 `py_id_06` 의 정답이
> 질의("**요청** 스키마")와 어긋나 **응답** 스키마를 5위로 맞춘 것이었다. 진짜 요청 스키마
> (`ComposeV25Request`)로 고쳐 다시 재니 **1위**다 — 결론은 그대로이고 근거가 더 분명해졌다.

**이상치 두 개가 평균순위를 끌어올렸다** (나머지 14개는 1~16위):
- `py_ko_05` "의상 영역은 어떻게 분리해?" **278위** — 정답 파일이 38,705자로 이 저장소에서 가장
  크고, `SegFormer` 가 13파일에 154번 나와 정답이 같은 주제의 청크 더미에 묻혔다
  → **셋 결함이 아니라 어려운 질의로 확정**. v2 에서 `difficulty: "hard"` 로 표시하고 남겼다
- `py_id_03` "genai.Client 로 Gemini 호출" **134위** — `genai.Client` 자체가 8파일에 12번
  나온다. **평가셋 설계 문제로 의심된다**(정답을 `body_service.py` 한 곳으로 못 박았는데
  다른 파일도 사실상 정답이다). 다음에 이 질의를 손볼 것
  → **의심이 맞았다.** v2 에서 질의 의도를 바꿔 18위 (아래 '평가셋 v2' 절)

**대가: 인덱싱 시간.** 청크가 1,683 → 4,364 개로 늘어(800자 상한) 임베딩이 **96분** 걸렸다
(전에는 같은 저장소가 22분). 백그라운드라 질문을 막지는 않지만 그동안은 코드 없이 답한다 —
소형 다국어 모델 검토가 그만큼 더 시급해졌다.

### 문자 상한 → 토큰 상한: 시도하고 되돌림 - 2026-08-18

**왜 해봤나.** 800자 상한은 한도(512토큰)를 문자 수로 지키려던 값인데, 문자/토큰 비율이
1.68 ~ 17.40 까지 10배 벌어져(한국어 주석 덩어리 vs 압축된 코드) **영어 코드까지 잘게
쪼개는 대가**를 치렀다. 상한을 2400 으로 올리고 한도는 토크나이저로만 지켜 봤다.

**결론: 상한은 800 으로 되돌렸다.** air 는 미세하게 좋아졌지만 marryday 는 한국어
Recall@8 이 0.80 → 0.60 으로 무너졌다(아래 측정). **토큰 재분할과 토크나이저 수정은 남긴다** —
상한과 무관하게 옳은 것이고, 800자로도 한도를 넘는 한국어 청크를 그것이 막는다.

- [x] `chunker._split_by_tokens()` — 토큰 한도 초과 청크만 실측 비율로 다시 자른다 **(유지)**
  - `chunk_files(count_tokens=..., token_limit=...)` 로 **주입**받는다. 청킹 모듈이
    임베딩 모델을 직접 부르면 청킹 테스트가 2GB 모델을 내려받아야 한다
- [x] **`embeddings.count_tokens()` 가 실제 토큰 수를 세도록 수정 (유지)** — 이게 없으면 위가 동작하지 않는다
  - 임베딩용 토크나이저는 truncation 이 걸려 있어 **한도를 넘는 텍스트도 512 로 보고**한다.
    "넘었다"는 알지만 "얼마나 넘었는지"를 모르니 축소율이 `500/512×0.9 = 0.879` 로 고정되어,
    3패스를 돌려도 0.68 배까지밖에 못 줄어 한도 안에 못 들어왔다
    (실측: 628토큰 청크가 2382자 → 1610자로만 줄고 여전히 512 도달)
  - `no_truncation()` 을 **사본에만** 건다. 원본을 끄면 한도 초과 입력이 그대로 모델에 들어간다
  - 이 값이 실제 수가 되면서 잘림 계측의 "도달(>=)로 세라"는 주의사항은 필요 없어졌지만,
    `>= limit` 은 그대로 둔다 — 딱 한도인 것도 잘린 것이 맞다
- [x] `tests/test_search_quality.py` — 소스 로컬 캐시(`Back/cache/eval_sources/`) **(유지)**
  - 청킹 규칙을 바꿔가며 재는데 매번 tarball 을 받을 이유가 없다(marryday 15초 + GitHub 요청).
    **측정끼리 같은 입력을 보장**하는 장치이기도 하다. 지우면 다음 실행에서 최신 소스로 다시 만든다

**결과 (air, 같은 모델·같은 평가셋)**

| 지표 | 2c (800자) | **토큰 상한 (2400자)** |
|---|---|---|
| 청크 수 | 236 | **203** (-14%) |
| 잘린 청크 | 0 | **0** |
| 한국어 Recall@8 | 0.67 | 0.67 |
| 한국어 MRR | 0.5028 | **0.5197** |
| 한국어 평균순위 | 11.25 | **9.33** |
| 식별자 Recall@8 · MRR | 1.00 · 0.9000 | 1.00 · 0.9000 |
| 전체 Recall@8 | 0.7647 | 0.7647 |
| 전체 MRR | 0.6196 | **0.6315** |
| 임베딩 시간 | 378s | **434s** |

**결과 (marryday, 같은 모델·같은 평가셋)**

| 지표 | 800자 | **토큰 상한 (2400자)** |
|---|---|---|
| 청크 수 | 4,364 | **3,033** (-30%) |
| 잘린 청크 | 0 | 0 |
| 한국어 Recall@8 | **0.80** | 0.60 |
| 한국어 MRR | **0.5399** | 0.3319 |
| 식별자 Recall@8 | 0.83 | 0.83 |
| 식별자 MRR | 0.4846 | **0.5987** |
| 전체 Recall@8 | **0.8125** | 0.69 |
| 전체 MRR | **0.5192** | 0.4319 |
| 임베딩 시간 | 5,748s (96분) | **2,345s (39분)** |

**저장소마다 방향이 갈렸다.** air 는 미세하게 좋아졌는데 marryday 는 한국어가 무너졌다
(나빠짐 7 · 좋아짐 5 · 동일 4). Recall@8 밖으로 나간 것은 `py_ko_01`(1→10)과
`py_ko_03`(2→14) 둘로, 정답이 더 큰 덩어리 안에 섞이면서 초점이 흐려진 것이다 —
"클래스를 통째로 두면 그 벡터가 모든 일의 평균이 된다"와 같은 현상이다.
식별자 질의는 반대로 좋아졌다(MRR 0.4846 → 0.5987): 이름만 맞히면 되는 질의는
문맥이 넓을수록 유리하다.

**임베딩 시간 측정은 노이즈가 크다.** air 는 378s → 434s 로 **느려졌는데**
marryday 는 5,748s → 2,345s 로 **2.45배 빨라졌다**. 청크당으로 보면 air 1.60s → 2.14s,
marryday 1.32s → 0.77s 로 방향이 정반대다. 같은 기기의 배경 부하가 섞여 있어
이 수치로 청킹 방식을 판단하면 안 된다 — 시간을 비교하려면 부하를 통제하고 다시 재야 한다.
**인덱싱 시간은 어차피 청킹으로 풀 문제가 아니다(소형 모델 쪽).** 이 시도의 판단 근거에서 뺐다.

- [x] `MAX_CHUNK_CHARS` 800 복귀 — 청킹만 재서 확인: air 236청크 / marryday 4,365청크,
      **양쪽 잘림 0** (최대 375·458토큰). 되돌리기 전 기록(236 / 4,364)과 사실상 일치
  - marryday 가 1개 늘어난 것은 소스 캐시를 오늘 다시 받았기 때문이다(저장소가 그새 갱신됐다).
    측정끼리 입력을 고정하려고 캐시를 둔 것인데, **캐시를 새로 만들면 그 고정이 풀린다** —
    이전 기록과 비교할 때는 캐시를 지우지 말 것
- [x] 검증: pytest **192 passed / 2 skipped**(DB 포함), 원본 토크나이저 truncation 유지 확인.
      LLM 실호출 없음 (임베딩은 로컬)

**남은 것:** 서비스 DB 의 기존 청크는 옛 규칙으로 만들어진 그대로다. 청킹 규칙을 바꿔도
새 스냅샷이 생겨야 다시 인덱싱된다 — 아래 '재인덱싱 트리거' 과제와 같은 문제다.

### CLAUDE.md §7 — 특정 저장소에 기대지 말 것 - 2026-08-18
평가 저장소 둘은 **테스트 대상일 뿐 언제든 교체된다.** 프로덕션 코드가 그 이름을 알면 안 된다.
- [x] 규칙 추가 — `app/` 에 저장소 이름 금지, 동작은 `snapshot_id`·`(owner, name)` 로,
      분기는 언어·크기 같은 **속성**으로. 이름은 `tests/` 와 plan.md 에만
- [x] 기존 주석 4곳 일반화 — 동작하는 하드코딩은 없었다(주석뿐)
  - `config.py` 아카이브 상한 근거, `chunker.py` 청크 상한·헤더 보존 근거,
    `indexer.py` 감점 근거·출력 예시. 근거는 남기고 이름만 성격으로 바꿨다
- [x] 검증: pytest 159 passed / 35 skipped(DB 정지 상태)

## Stage 4: 청킹 규칙 버전 - 2026-08-18

**문제.** 청킹을 여러 번 고쳤는데 **서비스 인덱스는 처음 만든 그대로였다.** 다시 인덱싱되는
것은 새 스냅샷이 생길 때뿐이라(저장소가 갱신돼 pushed_at 이 바뀔 때), 규칙만 바꾼 경우에는
개선이 사용자에게 닿지 않는다. 게다가 **아무도 그 사실을 알 수 없었다** — DB 를 직접 열기
전까지는 그 인덱스가 어떤 규칙으로 만들어졌는지 알 방법이 없었다.

발견 당시 상태: 스냅샷 #3(47파일)은 145청크로 Stage 3.5 시절 그대로 — 잘린 청크 15개가 남아
있고 2a 에서 살려낸 클래스 헤더가 없다. 지금 규칙이면 236청크다.

- [x] `app/core/chunk_rule.py` — `rule_version()` (16진수 8자)
  - **손으로 올리는 상수가 아니다.** 사람이 올리기를 잊으면 그 순간부터 거짓말이 되므로
    청킹 상수 + 노드 목록 + 임베딩 모델 + **청킹 함수 6개의 코드**에서 자동으로 뽑는다
  - 함수는 **AST 로 정규화**해서 넣는다 — 주석(`#`)은 AST 에 없고 docstring 은 지운다.
    이 저장소는 근거를 주석으로 길게 남기는 편이라, 그 편집마다 전 색인이 '재색인 필요'로
    뜨면 아무도 이 표시를 믿지 않게 된다. (실측 확인: 주석만 바꾸면 해시 유지)
  - 토큰 한도를 직접 읽지 않고 **모델 이름**을 넣는다 — `input_limit()` 은 모델을 올려야
    답하는데, 규칙 하나 확인하려고 2GB 를 로드할 수는 없다
  - 집합은 정렬해서 넣는다. 안 하면 실행마다 해시가 달라져 늘 '재색인 필요'가 된다
- [x] `snapshot_index_status.chunk_rule` 컬럼 (`DEFAULT 'legacy'`)
  - **`repo_snapshots` 가 아니다.** 청크는 테이블별로 따로 만들어지므로(code_chunks /
    code_chunks_1024) 규칙도 (스냅샷, 테이블) 단위다. 스냅샷에 한 칸만 두면 두 테이블 중
    한쪽 값은 반드시 거짓이 된다 — 실제로 #3 은 두 테이블 모두 completed 였다
  - **DEFAULT 가 곧 백필이다.** 규칙을 기록하기 전에 만든 색인은 무슨 규칙인지 알 수 없으니
    '모른다'(legacy)로 남기고 재색인 대상으로 본다
  - 기록은 `begin()` 이 아니라 `complete()` 에서 — 실패한 인덱싱에는 그 규칙으로 만든 청크가 없다
- [x] `index_status.list_all()` / `stale(current_rule)` + `/admin/api/snapshots`
      + `/admin/snapshots` 페이지 (네비게이션 6곳·홈 카드 추가)
  - **`chunks_actual` 은 청크 테이블을 실제로 센 값이다.** `chunks_total` 은 인덱싱이 기록한
    값이라 어긋난다 — 평가 하네스가 `replace_chunks()` 만 부르고 `complete()` 를 안 불러서,
    #17 은 기록 4,364 인데 실제 3,033 이었다. 화면에는 실제 값을 보여준다
  - `stale()` 은 **완료된 것만** 본다. 진행 중·실패한 색인은 애초에 쓸 수 없어 '낡았다'가 무의미하다
- [x] 기동 로그(`main._log_stale_indexes`) — `스냅샷 #3 owner/name [table]: rule legacy ≠ 현재 8e9937c1`
  - **자동 재색인은 하지 않는다.** 큰 저장소는 임베딩만 수십 분이라 서버를 올릴 때마다
    그게 시작되면 기동이 곧 장애가 된다. 무엇이 낡았는지만 알리고 시점은 사람이 정한다

**이 단계는 읽기 전용이다** — 청크를 다시 만들지 않았다. 확인용으로 `code_chunks_1024`
행 수(5,064)가 작업 전후 그대로임을 확인했다.

**현재 규칙 `8e9937c1` · 낡은 색인 6/6건** (전부 legacy)

| 스냅샷 | 저장소 | 테이블 | 실제 청크 | 규칙 |
|---|---|---|---|---|
| #3 | Air (서비스) | code_chunks / _1024 | 145 / 145 | legacy |
| #4 | Air (평가용) | code_chunks / _1024 | 145 / 203 | legacy |
| #12 | Marryday (서비스) | code_chunks_1024 | 1,683 | legacy |
| #17 | Marryday (평가용) | code_chunks_1024 | 3,033 | legacy |

- [x] 검증: pytest **204 passed / 2 skipped**(DB 기동, skip 2건은 `-m evaluation` 전용 측정),
      신규 12건(chunk_rule 7 · index_status 5). 7개 라우트 200, 템플릿 참조 필드 15개 누락 없음,
      기동 로그 6줄 실측. LLM 실호출 없음
  - 화면 렌더링은 미확인 (JS 참조 필드만 정적 확인)

### 재색인 경로 — 빌드와 포인터 - 2026-08-18

**문제.** 낡은 색인을 다시 만들 방법이 없었다. `indexer.start()` 는 색인이 있으면 건너뛰고,
`/admin/api/reindex` 는 이름과 달리 **요약만** 새로 만들며 LLM 을 호출해 과금됐다.

- [x] `index_builds` 테이블 — 인덱싱 한 번의 생애(상태·진행률·규칙·오류)
  - **제자리 교체를 없애려고 도입했다.** DELETE 후 INSERT 를 하면 큰 저장소 기준 40~96분
    동안 청크가 없어 챗봇이 코드 없이 답한다. 새 빌드를 따로 쌓고 완료된 순간에
    `snapshot_index_status.active_build_id` 만 옮긴다 → 그 시간 내내 옛 빌드로 답한다
  - 포인터를 되돌리면 그대로 롤백이다(청크가 아직 살아 있다)
  - **완료 표시와 포인터 교체가 한 트랜잭션.** 나뉘면 새 청크가 아무도 안 보는 채로 쌓이거나
    미완성 빌드를 검색하게 된다
  - `chunk_rule` 을 빌드로 옮겼다 — 규칙은 빌드의 속성이다(그게 재색인의 목적이다)
  - 백필: 기존 완료 색인을 '빌드 1'로 묶고 청크 5,354행에 `build_id` 를 채웠다(누락 0)
- [x] `chunks.search()` 가 **스냅샷이 아니라 빌드로** 찾는다
  - 재색인 중에는 같은 스냅샷에 옛 빌드와 새 빌드의 청크가 함께 있다. 스냅샷으로 찾으면
    절반만 임베딩된 새 청크가 섞여 들어온다
- [x] `index_status.get()` 은 **활성 빌드를 우선** 돌려준다
  - 재색인이 도는 중에 진행 중 빌드를 돌려주면 화면에 "코드를 처음 읽는 중" 배너가 떠서,
    멀쩡히 답하고 있는데도 준비가 안 된 것처럼 보인다
- [x] `services/index_queue.py` — 워커 **하나**가 순서대로 처리
  - 임베딩은 CPU 를 다 쓴다. 큰 저장소 하나가 40~96분인데 서너 개가 겹치면 어느 것도 안 끝난다
  - **첫 색인(lazy)도 같은 큐를 탄다.** 경로가 둘이면 서로 모른 채 동시에 돈다
  - 중복 판정은 DB 가 한다(`begin()` 이 한 문장으로 판정+삽입). 큐를 보고 판정하면 이미
    꺼내 처리 중인 작업을 놓친다
  - **자동 재색인은 없다.** 규칙이 바뀌면 전 저장소가 한꺼번에 낡는데 그때 자동 시작하면
    배포 직후가 곧 장애다. 기동 시 running 은 pending 으로 되돌리기만 하고 큐에 넣지 않는다
- [x] 이름 정리 — `/api/reindex` → **`/api/resummarize`**(LLM·과금·동기),
      신설 **`/api/rebuild-index`**(무과금·비동기 202)
  - `scope=` 로 합치지 않았다. 파라미터 하나로 과금이 생겼다 없어졌다 하면 사고가 난다
- [x] `/api/builds`(이력) · `/api/rollback-index`(포인터 되돌리기) · `/api/cleanup`
- [x] 보관 정책 `KEEP_BUILDS=1` — 활성 + 직전 하나. 새 빌드 활성화 직후 초과분 삭제
      (청크는 `ON DELETE CASCADE` 로 함께 사라진다). 진행 중인 빌드는 지우지 않는다
- [x] `services/cleanup.py` — **기본 dry-run**, `apply=true` 일 때만 삭제
  - 대화가 참조하는 스냅샷은 절대 지우지 않고, 그 저장소의 최신도 남긴다(요약 캐시로 쓴다)
  - 빈 세션은 **24시간이 지난 것만**. `/analyze` 는 분석마다 세션을 만들고 사용자는 요약을
    읽은 뒤 첫 질문을 하므로, 유예가 없으면 질문하는 순간 세션이 사라진다
- [x] 768 잔재를 **신호에서 제외** — `stale()` 은 지금 쓰는 청크 테이블만 본다
  - 차원이 다른 옛 테이블은 아무도 읽지 않는다. 고칠 이유가 없는 항목이 섞이면 진짜 대상이 묻힌다
  - 화면에는 '미사용'으로 남겨 둔다(있다는 사실 자체는 정보다)
- [x] 평가 하네스도 같은 경로로 — `insert_chunks` → `complete()` → `prune_builds()`
  - 전에는 `replace_chunks()` 만 부르고 완료 처리를 건너뛰어 기록이 실제와 어긋났다
- [x] `/admin/snapshots` 화면 — 재색인 버튼, 빌드 이력 펼치기, 롤백 버튼, 정리(미리보기/적용)

**승인받아 실제로 지운 것: 768 테이블 청크 290행뿐.** 빈 세션·참조 없는 스냅샷은
구현만 하고 실행하지 않았다. 삭제 후 확인: 메시지 18 · 세션 5 · 스냅샷 4 · 1024 청크 5,064 그대로.

**기동 로그가 6건 → 4건으로 줄었다** (768 잔재 2건이 빠졌다).

- [x] 검증: pytest **226 passed / 2 skipped**(DB 기동). 신규 22건
      (빌드 20 · 큐 3 · 정리 8 중 재작성분 포함), 5개 라우트 200,
      옛 `/api/reindex` 404 · 새 `/api/resummarize` 400 확인,
      템플릿 id 7개·필드 21개 정합성 확인. LLM 실호출 없음

### Phase 3 — 화면에서 판정 (완료) - 2026-08-18
지금까지의 청킹 작업이 **사용자에게 닿았는지**를 브라우저에서 확인했다. Chrome 확장 연결됨.

> **이 사슬의 결론: 순위 문제가 아니라 인덱스 부재였다.**
>
> `extends TextWebSocketHandler` 를 담은 청크가 **새 빌드 #19 에 1개, 옛 빌드 #3 에 0개**.
> Stage 3.5 부터 이 질의(id_04)를 "순위가 낮다"로 다뤄 왔지만 실제로는 **정답이 인덱스에
> 존재하지 않았다** — 클래스 헤더가 `MIN_CHUNK_CHARS` 에 못 미쳐 통째로 버려졌기 때문이다.
> 검색을 아무리 손봐도 없는 것은 찾을 수 없다. 청킹(2a) → 규칙 버전 → 재색인 경로까지
> 이어진 작업이 필요했던 이유가 이 한 줄이고, 그것이 화면의 답변으로 확인됐다.

- [x] `/admin/snapshots` 렌더링 — 규칙 `8e9937c1`, 재색인 필요 4건,
      768 테이블 2건은 회색 '미사용'에 재색인 버튼 없음(설계대로)
- [x] air(#3) 재색인 트리거 → **build #19 / 236청크**(예상과 일치)
- [x] **재색인 중 사용자 화면** — 이 단계에서만 볼 수 있는 것들
  - **색인 배너가 뜨지 않았다.** `index_status.get()` 이 활성 빌드를 우선하도록 고친 부분의 검증이다
  - 재색인이 도는 중에 질문 → **옛 청크(145)로 정상 답변**. `SecurityConfig.java` 35-42행의
    `BCryptPasswordEncoder` 실제 코드를 인용했다 → 제자리 교체를 없앤 이유가 화면에서 확인됐다
- [x] **인수 조건 통과** — "TextWebSocketHandler를 상속하는 클래스가 뭐야?"
  - 답: `ChatHandler` (`websocket/ChatHandler.java` **3-4행**), 오버라이드 메서드 3개까지 짚었다
  - DB 확인(위 결론의 근거): 그 문자열을 담은 청크가 **새 빌드 #19 에 1개 · 옛 빌드 #3 에 0개**
- [x] 완료 조건 — `chunk_rule=8e9937c1` · `chunks_actual=236` · `active_build_id=19`,
      옛 빌드 #3 은 롤백용으로 보관됨. 낡은 색인 4 → 3건
- [x] **Claude 실호출 end-to-end 첫 확인** (그동안 토큰 절약으로 계속 미뤘던 항목).
      `/analyze` 캐시 히트 → 세션 복원 → `/chat` 2회. 오늘 비용 $0.0217
- [x] 히트율 타일·오늘 사용량 미터 렌더링 확인 (`/admin/usage`)

**화면에서 찾은 버그 하나** — 출처별 표가 대화 11건을 '실험실'로 표시했다.
`admin_usage.html` 의 `sourceLabel()` 이 `analyze` 가 아니면 전부 '실험실'로 적는
2분기 코드였는데, 그 뒤 `chat`·`resummarize` 가 생기면서 어긋났다.
맵으로 바꾸고 모르는 값은 그대로 보여주게 했다 → **대화 11 / 프론트 9 / 실험실 3** 로 교정.

- [x] 검증: pytest **226 passed / 2 skipped**(변경 없음 확인)

### marryday 재색인 + 화면 확인 - 2026-08-18

- [x] `/admin/snapshots` 에서 #12·#17 트리거 → 큐가 순서대로 처리, **74분**에 두 건 완료
  - 두 번째 요청도 202 를 받고 큐에서 대기한다(워커 1개). 재색인 내내 옛 빌드가 활성이라
    검색은 멈추지 않았다

| 스냅샷 | 빌드 | 청크 | 규칙 |
|---|---|---|---|
| #12 marryday (서비스) | #24 | 1,683 → **4,365** | `8e9937c1` |
| #17 marryday (평가용) | #25 | 4,364 → **4,365** | `8e9937c1` |

**서비스 인덱스는 전부 `8e9937c1`** — air #3 236청크 · marryday #12 4,365청크.

- [x] **화면 확인 — 2400자 인덱스에서 Recall@8 밖으로 나갔던 두 질의**
      (`py_ko_01` 1→10위, `py_ko_03` 2→14위였던 것들)

| 질의 | 화면 답변 | 평가셋 정답 | DB 실제 위치 |
|---|---|---|---|
| 체형 분석은 어디서 처리해? | `routers/body_analysis.py` 의 `analyze_body` (332행) | `body_analysis.py` / `def analyze_body` | 332-354행 |
| 드레스 합성은 어디서 처리해? | `routers/composition.py` 의 `compose_dress` (30행~) | `composition.py` / `def compose_dress` | 30-55행 |

둘 다 파일·함수·행이 정확히 맞았다. 세션이 활성 빌드 #24 를 보고 있음도 확인했다.

- [x] **Stage 3.6 의 "코드 없이 답변" 해소 확인** — 같은 화면 위아래로 대비가 남아 있다.
      복원된 옛 대화: "body_analysis.py 안에 코드 보여줘" → *"실제 소스 코드 내용이 포함되어
      있지 않습니다"*. 방금 던진 질문: 같은 파일의 함수와 행 번호를 짚고 호출 흐름까지 설명
- [x] 배너·타일 — 색인 완료 상태라 **배너 없음**(정상). 오늘 사용량 미터·히트율 타일 정상,
      출처별 라벨도 대화 13 / 프론트 10 / 실험실 3 으로 교정된 상태 유지

**air 와 marryday 는 결함의 종류가 달랐다** — 기록해 둘 것:
- air `id_04`: 클래스 헤더가 버려져 **정답이 인덱스에 없었다**(옛 빌드 0개 → 새 빌드 1개)
- marryday `py_ko_01`·`py_ko_03`: **정답은 옛 빌드에도 있었다**(각 2개·1개). 순위가 밀렸을 뿐이라
  800자 청킹이 순위를 되돌린 경우다
- 즉 "인덱스 부재"와 "순위 저하"가 둘 다 실재했고, 같은 청킹 수정이 양쪽을 고쳤다

**낡은 색인 1건이 남는 것이 정상 상태다** — `#4` (air, `eval:fixed`).
평가 전용 스냅샷이라 대화가 참조하지 않고, **다음 `pytest -m evaluation` 실행 때 하네스가
새 빌드를 만들면서 자동으로 해소된다.** 그때까지 `/admin/snapshots` 의 '재색인 필요'가
1 로 표시되는 것은 이상이 아니다. (0 으로 만들고 싶으면 그 스냅샷도 재색인하면 되지만,
평가를 돌리면 어차피 다시 만들어지므로 임베딩 시간만 버리는 셈이다)

## 단가 만료 대비 - 2026-08-18

**문제.** `claude_client.PRICING` 에 sonnet-5 도입가($2/$10)가 상수로 박혀 있고 주석에
"2026-08-31 이후 $3/$15 로 수정할 것"만 적혀 있었다. **사람이 잊으면 그날부터 조용히
33% 적은 비용을 쌓는다** — 틀렸다는 신호가 어디에도 뜨지 않는다.

- [x] `pricing_for(model, at=None)` — 그 시점의 단가를 돌려준다. sonnet-5 만 날짜로 갈린다
  - 지금 바로 $3/$15 로 바꾸는 안은 반려했다. 도입가가 아직 13일 남아 그동안 과대 계산된다
  - `estimate_cost(..., at=None)` 도 날짜를 받는다(옛 기록 재계산용). 호출부는 그대로다
- [x] 지난 기록은 **소급되지 않는다** — `runs.jsonl` 의 `cost_usd` 는 호출 시점 단가로
      이미 계산돼 있고 `usage_stats` 는 그 값을 합산만 한다. 단가가 바뀌어도 과거 집계는 안 변한다
- [x] 검증: pytest **232 passed / 2 skipped**(신규 6). 경계 확인 —
      08-31 은 $2/$10, 09-01 은 $3/$15. 같은 토큰(76,839/12,924)이 $0.2829 → $0.4244

## 평가셋 v2 — 판정 조이기 - 2026-08-19

**문제.** 이상치 두 개(`py_id_03` 134위·`py_ko_05` 278위)를 보려다 **더 큰 것을 찾았다.**
v1 은 정답 판정이 헐거워 **청크 검색이 아니라 사실상 파일 검색을 재고 있었다.**

| 질의 | v1 정답비율 | 무엇이 문제였나 |
|---|---|---|
| `id_05` | **100%** (4/4) | `scheduleRepository` 가 클래스 헤더부터 전 메서드에 나옴 |
| `py_id_06` | **100%** (3/3) | 파일 청크 3개가 전부 정답 |
| `py_id_02` | 56% (10/18) | `boto3` 한 단어 |
| `py_id_01` | 29% (4/14) | `SegFormer` 한 단어 → **모듈 docstring + import 주석 청크도 정답** |

"그 파일 어딘가만 걸리면 통과"라 청크 단위 개선이 지표에 안 잡힌다.

### 질의-정답 정합성 오류 2건 (더 심각했다)

- **`py_id_06`** — "BaseModel 을 상속한 **요청** 스키마"인데 정답 `tryon_schema.py` 의 세 클래스는
  **전부 Response** 였다(`UnifiedTryonResponse`·`V4V5CompareResponse`·`V4V5CustomCompareResponse`).
  저장소 전체에서 이름에 `Request` 가 든 스키마는 셋뿐이고 `schemas/` 아래 있는 것은
  `ComposeV25Request` 하나라 그것으로 교체
- **`py_id_03`** — `genai.Client(api_key=...)` 한 줄이 8파일 12번 나오는데 정답을
  `body_service.py` 로 못 박았다. 그 파일이 특별할 이유가 없고(`tryon_service.py` 가 4회로 더 많다)
  질의에도 파일을 특정할 단서가 없었다. 키 로테이션을 관리하는 전용 클래스는
  `core/gemini_client.py` 하나뿐이라 **질의 의도를 그쪽으로 바꿨다**

### 수정

- [x] `answers: [{path_suffix, must_contain, must_not_contain?}]` — **정답 복수 표현**.
      한 곳으로 못 박을 수 없는 질의가 실재한다(같은 함수의 v3/v4)
- [x] 판정 조이기 4건 → 정답 비율 `id_05` 100→25% · `py_id_06` 100→50% ·
      `py_id_02` 56→6% · `py_id_01` 29→21%
  - `py_id_02` 는 `boto3.client(` 로 좁혀도 56% 그대로였다 — 그 파일은 **함수마다 클라이언트를
    새로 만들어** 같은 호출이 7번 나온다. 라이브러리 이름만으로는 청크 변별이 원리상 안 되므로
    질의에 동작을 결합했다("boto3 로 S3 에 파일 업로드")
- [x] `py_ko_05` 는 **남긴다** — `difficulty: "hard"` + `why_hard` 에 이유를 적었다.
      정답은 인덱스에 분명히 있다(청크 3개). 검색이 못 찾는 것이지 셋의 결함이 아니다
- [x] **접두 매칭은 유지**했다. 정확 매칭으로 바꾸면 `py_ko_05` 의 v3·v4 가 오답이 되는데
      셋 다 정당한 답이다. 대신 `answers` 에 3개를 **명시적으로 나열**해 의도를 드러냈다
      (우연히 걸리던 것을 의도된 것으로)
- [x] `EVAL_SET_VERSION = 2` + `search_eval_log` 키에 포함 + `/admin/search` 에 열·경고 문구
  - 키가 `(model, table, repo, set_version, note)` 가 됐다. 확인: air 의 v1·v2 가 둘 다 남는다

### 측정 (같은 청킹·같은 모델, 셋만 교체)

**air** — 한국어 12개 순위가 **전부 동일**(안 건드렸으니 당연). 바뀐 것은 `id_05` 2→1 하나.

| 지표 | v1 (2c 최종) | v2 |
|---|---|---|
| 한국어 R@8 · MRR · 평균 | 0.67 · 0.5028 · 11.25 | 동일 |
| 식별자 R@8 | 1.00 | 1.00 |
| **식별자 MRR** | 0.9000 | **1.0000** |
| 전체 MRR | 0.6196 | **0.6491** |

**marryday** — 한국어 10개도 **전부 동일**. 식별자만 움직였다.

| 질의 | v1 | v2 | |
|---|---|---|---|
| `py_id_03` | 134 | **18** | 질의 의도 수정 |
| `py_id_06` | 5 | **1** | 진짜 요청 스키마로 교체 |
| `py_id_01` | 5 | 5 | **import 줄 덕이 아니었다** |
| `py_id_02` | 1 | 2 | 질의가 바뀌었으니 다른 질의다 |
| `py_ko_05` | 278 | 278 | hard 로 표시됨 |

| 지표 | v1 | v2 |
|---|---|---|
| 한국어 R@8 · MRR · 평균 | 0.80 · 0.5399 · 30.8 | 동일 |
| 식별자 R@8 | 0.83 | 0.83 |
| **식별자 MRR · 평균순위** | 0.4846 · 24.67 | **0.5426 · 4.83** |
| 전체 MRR | 0.5192 | **0.5409** |

**수치가 떨어지지 않았다.** 조이면 낮아질 것으로 예상했는데 양쪽 다 같거나 좋아졌다 —
정답을 정확한 곳으로 좁히니 검색도 그곳을 정확히 맞췄다는 뜻이다.
그래도 **v1 과 v2 는 원칙적으로 비교 대상이 아니다**(정답 조건이 다르다).
버전이 기록·화면 양쪽에 남아 있으므로 나중에 섞이지 않는다.

**확인된 것 둘:**
- `py_id_01` 의 순위는 **import 줄 덕이 아니었다** — 5위 그대로다.
  (v1 에서 1위였던 측정은 2400자 인덱스였고, 800자에서는 원래 5위다)
- **2a 검증은 성립한다.** `py_id_06` 이 진짜 요청 스키마로 바꾼 뒤 **1위**다 —
  `class ComposeV25Request(BaseModel)` 헤더 청크가 인덱스에 있고 정확히 잡힌다.
  Stage 3.7 의 "2a 가 Python 에서도 듣는다"는 결론은 유지되며, 근거가 더 분명해졌다
  (전에는 응답 스키마를 5위로 맞춘 것이었다)

- [x] 검증: pytest **232 passed / 2 skipped**. 평가 2회(air 99초 · marryday 25분).
      LLM 실호출 없음 — 임베딩은 로컬이다

## 다음 과제 (2026-08-20 착수 예정)

**순서가 정해져 있다. 작은 저장소 우회가 먼저다** — 우회 분기가 생기면 소형 모델이
풀어야 할 범위가 먼저 확정되고, 74분짜리 측정도 없다.

### 1. 작은 저장소 RAG 우회
Stage 3 의 "작은 저장소는 RAG 없이 통째로 넣어도 된다" 항목.
분기는 **크기 속성**으로 한다 — 저장소 이름으로 분기 금지(CLAUDE.md §7).

**구현 전에 셋에 답하고 임계값 제안 → 승인.** 바로 구현하지 말 것:
- [x] 임계값을 무엇으로 잴 것인가 — **토큰 수로 재고 바이트 수를 사전 게이트로.** - 2026-08-19
  - 파일 수는 안 된다: air 47파일/111,857자 vs marryday 181파일/2,260,608자 —
    **파일은 3.9배인데 문자는 20배다**
  - 문자 수도 결정 변수로는 못 쓴다. 실측 로그에서 지금 `context`(한국어 README+경로목록)가
    9,964자 → 약 5,000토큰(**2.0자/토큰**)인데 소스 코드는 3자/토큰대다
  - **"tarball 비용"이라는 전제가 성립하지 않는다** — RAG 경로도 `run_build()` 에서
    `fetch_source_files()` 로 어차피 받는다. 우회 판정은 그 직후 메모리 위의 텍스트로 하면
    되고 GitHub 요청은 0회 추가다
  - 1단계(사전): `/git/trees?recursive=1` 의 blob `size` 합 (이미 부르는 호출).
    `truncated: true` 면 무조건 RAG. 2단계(확정): tarball 직후 `count_tokens`(무과금) 1회,
    스냅샷에 기록해 질문마다 판정이 흔들리지 않게
- [x] 질문 1회당 비용 — **캐시 구조는 그대로 쓸 수 있다. 단 "1/10" 은 틀렸다.** - 2026-08-19
  - `build_chat_messages()` 구조(스냅샷 원문 = 첫 사용자 메시지 + `cache_control`)를 전체 주입에
    그대로 쓸 수 있다. 소스 본문은 스냅샷마다 고정이라 캐시 접두사로 알맞다
  - **0.1배는 읽기 단가일 뿐이다.** 쓰기가 1.25배(5분 TTL)라 세션 N회의 실효 배율은
    `(1.25 + 0.1(N−1))/N` — N=5 면 **0.33배지 0.1배가 아니다**. 1/10 가정으로 임계값을
    잡으면 3배 헐거워진다
  - 정가 환산 질문당: RAG $0.015~0.020 / 전체주입 S=35K $0.042(2.8배) / S=100K $0.086(5.5배)
  - **최대 위험은 캐시 미스** — 5분 TTL 이 깨지면 그 질문 하나가 S×1.25 다(S=40K → $0.15, 10배).
    실측 로그의 질문 간격은 최대 2분41초라 안 깨졌지만 표본이 세션 3개뿐 → 미스율을 먼저 계측
  - **소스는 `context` 에 합치면 안 된다** — `run_summary()` 가 같은 문자열을 써서 요약 비용까지
    같이 커진다. 별도 컬럼에 두고 채팅에서만 이어 붙일 것
- [x] 품질 판정 방법 — **평가셋 v2 를 그대로는 못 쓴다.** (아래 6단계에서 측정 완료)
  - Recall@8·MRR 은 순위 지표인데 전체 주입에는 검색이 없다. 형식상 Recall@∞=1.0 이 되어
    자동 만점이다 — 이걸 "전체 주입이 이겼다"로 읽으면 안 된다
  - (a) 무료 상한선: 전체 주입이 이길 수 있는 폭은 `1 − Recall@8` 뿐이다 →
    **air 17개 중 4개(23.5%)**, marryday 16개 중 3개(19%)
  - (b) 인용 정확도(권장): `answers[].path_suffix` 를 순위가 아니라 **답변 텍스트**에 적용.
    문자열 매칭이라 LLM 심판이 필요 없고 두 경로를 같은 자로 잰다.
    비용 약 $0.7 (air 17질의 × 2경로, 1시간 TTL 로 접두사 1회 쓰기) — **사용자 승인 완료**
  - (c) 판정 기준을 먼저 고정: 인용 정확도가 **떨어지면 우회를 접는다**, 동률이면 RAG 유지,
    올라야만 켠다. plan.md 에 이미 "큰 덩어리에 섞이면 초점이 흐려진다"(`py_ko_01` 1→10위)가
    기록돼 있어 전체 주입이 지는 결과가 실제로 가능하다

### 1단계: 번들 조립 + 토큰 실측 — **임계값 재산정이 필요하다** - 2026-08-19

- [x] `context_builder.build_source_bundle()` — 경로 정렬 + 줄 번호 + 언어 태그
  - **경로 순 정렬은 캐시 때문이다.** 이 문자열이 `cache_control` 접두사가 되는데
    tarball 순서에 맡기면 실행마다 바이트가 달라져 매 질문이 캐시를 새로 쓴다
  - 줄 번호를 붙인다 — `CHAT_SYSTEM_PROMPT` 가 "몇 행인지 밝히라"고 요구하고,
    번호가 없으면 모델이 세어서 지어낸다
  - 표기는 `12|코드`. 자리맞춤(`   12| `)은 **읽는 쪽이 모델이라 값이 없고 토큰만 든다** —
    실측 +26.0% vs +15.8%, 5,531토큰 차이
- [x] `claude_client.count_input_tokens()` — 무과금(추론 없음). 실패 시 None →
      `context_builder.estimate_tokens()`(2.0자/토큰)로 대체
  - `core.embeddings.count_tokens` 와 이름을 구분했다. 그쪽은 임베딩 토크나이저다
- [x] `config.FULL_INJECTION_MAX_TOKENS` / `FULL_INJECTION_MAX_SOURCE_BYTES`

**실측 (로컬 소스 캐시, GitHub·DB·과금 없음)**

| 저장소 | 파일 | 소스 | 바이트 | 번들 토큰 | 자/토큰 |
|---|---:|---:|---:|---:|---:|
| Java, 47파일 | 47 | 111,857자 | 119KB | **62,380** | 2.05 |
| Python/JS, 181파일 | 181 | 2,260,438자 | 2,391KB | **1,057,764** | 2.41 |

**추정이 1.8배 빗나갔다.** 앞 절에서 Java 저장소를 ~35,000토큰으로 잡았는데 실제는 62,380 이다.
일반적인 코드 비율(3.2자/토큰)을 썼지만 이 저장소들의 실측은 **2.05~2.41자/토큰** 이다
(한국어 주석 + 줄번호 접두사). **번들 래퍼(경로 헤더·펜스·줄번호)를 안 센 것도 겹쳤다.**

그리고 앞 절의 "4배 → 40,000 토큰"은 **산식이 어긋나 있었다.** 40,000 은 실제로 약 2.9배다.
아래에서 추측값을 전부 실측으로 갈아치우고 다시 뽑았다.

### 임계값 재산정 — 추측을 전부 실측으로 - 2026-08-19

앞선 산정에는 추측이 셋 섞여 있었다: RAG 기준선($0.017), 세션당 질문 수(5회), 스니펫 몫.
셋 다 로그에서 뽑았다.

**(1) 세션당 질문 수** — `runs.jsonl` 의 `chat` 기록 13건을 세션으로 복원했다.
경계 규칙: `cache_read == 0` 이면 새 세션의 첫 질문이다(첫 턴은 접두사를 쓰기만 한다).
세션 간 간격이 106분~1일이라 캐시 미스와 혼동될 여지가 없음을 확인했다.

| 세션 | 저장소 | 질문 | 접두사 |
|---|---|---:|---:|
| 08-16 | Java | 3 | 5,831 |
| 08-17 | Python/JS | 6 | 7,211 |
| 08-18 | Java | 2 | 6,057 |
| 08-18 | Python/JS | 2 | 7,211 |

**분포 [3,6,2,2] · 평균 3.25 · 중앙값 2.5.** 5회로 잡았던 것이 틀렸다.

**(2) RAG 기준선** — 수정된 `estimate_cost` 로 다시 계산 (정가 환산):

| 세션 | 질문당 | 옛 기록 |
|---|---:|---:|
| Java 3회 | $0.0150 | $0.0132 |
| Python/JS 6회 | $0.0195 | $0.0529 |
| Java 2회 | $0.0286 | $0.0217 |
| Python/JS 2회 | $0.0445 | $0.0399 |
| **전체 13질문** | **$0.0237** | |

**질문이 적은 세션이 질문당으로는 훨씬 비싸다** — 쓰기 1.25배를 나눠 질 상대가 없다.

**(3) 스니펫 몫** — 청킹해서 상위 8개(`TOP_K`)를 `format_snippets` 로 조립해 실측:
Java 2,056 / Python·JS 2,201 → **평균 2,128 토큰/질문**.

**단일 산식 (꼬리 포함)**

`C_rag` 가 실측 로그에서 나왔으므로 요약·이력·스니펫이라는 꼬리가 이미 그 안에 들어 있다.
전체 주입은 꼬리에서 스니펫만 빠지고 접두사에 `S` 가 더해진다:

> **S_max = (3·C_rag/p_in + snip) / w̄**  ,  w̄ = Σ(1.25 + 0.1(N−1)) / ΣN

`= (3×0.0237/3.00e-06 + 2,128) / 0.4538` = **56,991 토큰** → `FULL_INJECTION_MAX_TOKENS = 57000`

- [x] `w̄ = 0.4538` — 0.33 으로 잡았던 것이 27% 낙관이었다. **이 값이 임계값을 지배한다.**
      실측 세션이 짧아서(평균 3.25회) 쓰기 1.25배가 잘 나눠지지 않는다.
      질문이 전부 6회면 w̄ 0.29 → 임계값 약 88,000 이 된다
- [x] **표본이 4세션 13질문뿐이다.** 개발 중 테스트 기록이지 실사용 분포가 아니다.
      실사용이 쌓이면 같은 산식으로 다시 뽑을 것 (`config.py` 주석에 산식을 남겼다)

**결과: Java 저장소(62,380)는 57,000 을 9% 초과해 탈락한다.** 우회했다면 질문당 $0.1023 —
`C_rag` 의 **4.31배**로 예산을 넘는다. 지금 가진 저장소 둘 다 우회 대상이 아니다.

### 2단계: 크기 분포 — 우회 구간은 실재하는가 - 2026-08-19

임계값을 넘는 저장소만 있으면 이 기능은 대상이 없다. GitHub 에서 120개를 조사했다
(트리 API 의 blob size 합, 수집 필터는 `fetch_source_files` 와 동일. tarball 안 받음).

표본을 두 층으로 나눴다 — **이 서비스의 입력 분포를 모르므로 하나로 뭉뚱그리지 않는다.**

| 층 | 질의 | n | 중앙 소스 | 임계값 이하 |
|---|---|---:|---:|---:|
| A 인기 | `stars:>1000` | 59 | 4,265KB | **15%** |
| B 소규모 | `stars:5..200 size:<5000` | 60 | 78KB | **62%** |

**구간은 실재하고, 어느 층이냐가 전부를 가른다.** 남의 유명 프로젝트를 넣으면 거의 다
RAG 로 가고, 개인·팀 규모 프로젝트를 넣으면 3분의 2가 우회 대상이다.
분포는 양봉이다 — 100KB 이하 42건 / 800KB 초과 43건, 그 사이가 얇다.

**바이트/토큰 환산율 실측 (12개 저장소를 실제로 받아 번들 조립 후 count_tokens)**
최소 1.39 · **중앙 2.04** · 최대 2.26. 한국어 저장소 둘(1.95·2.32)과 사실상 같다 —
코드는 언어를 불문하고 번들 형태에서 약 2바이트/토큰이다.

**그래도 바이트로 판정하면 안 된다.** 후보 실측에서 Go 저장소 둘이 추정보다
**24~32% 높게** 나왔다(`a8m/mark` 46,688→61,651, `shaovie/goev` 53,159→65,789). 둘 다
추정으로는 통과, 실측으로는 탈락이다. **바이트는 사전 게이트로만 쓰고 판정은 토큰으로 한다**는
설계가 여기서 실증됐다.

### 3단계: 검수 저장소 선정 규칙 - 2026-08-19

평가 저장소는 언제든 교체되므로(CLAUDE.md §7) **고르는 기준을 남긴다.** 이름이 아니라 이 규칙이 자산이다.

| # | 조건 | 근거 |
|---|---|---|
| 1 | 번들 토큰 ≤ `FULL_INJECTION_MAX_TOKENS` | 우회 경로를 실제로 타야 비교가 성립한다 |
| 2 | **`TOP_K` / 청크 수 ≤ 5%** | 검색이 실제로 골라야 한다. 이 몫이 크면 RAG 가 사실상 전체를 보게 되어 두 경로가 같아진다 (기준점: Java 저장소 3.4%) |
| 3 | 소스 파일 ≥ 20개 | 질의를 서로 다른 곳으로 흩을 수 있어야 한다 |
| 4 | 실제 코드일 것 | 조사에서 awesome-list·교재 저장소가 `language:Python` 으로 잡혔다. 스크립트 몇 개뿐이라 검색 평가에 못 쓴다 |
| 5 | 갱신이 뜸할 것 | 소스가 흔들리면 측정끼리 입력이 달라진다 (소스 캐시가 있지만 첫 수집이 어긋난다) |
| 6 | (우대) 기존 검수 저장소와 성격이 다를 것 | 결론이 한 종류에만 맞춘 것은 아닌지 본다 |

**규칙 2가 실질적으로 구간을 좁힌다.** 1·3만 보면 7개가 통과하는데 2를 걸면 3개만 남는다 —
우회할 만큼 작으면서 검색 비교가 성립할 만큼 큰 구간은 대략 **150~250청크 / 30,000~50,000토큰**이다.

**실측 (전부 받아서 잼)**

| 저장소 | 언어 | 파일 | 번들토큰 | 여유 | 청크 | TOP8몫 | 저정보 | 판정 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| teaey/apns4j | Java | 32 | 34,467 | +65% | 168 | 4.8% | 24% | **적합** |
| gary23ai/ARPL | Python | 21 | 45,203 | +26% | 213 | 3.8% | 5% | 적합 |
| chenyongci/Android-Week-Calendar | Java | 26 | 44,383 | +28% | 197 | 4.1% | 9% | 적합 |
| GitJournal/git-auto-sync | Go | 25 | 24,473 | +133% | 91 | 8.8% | 13% | 규칙2 탈락 |
| mesqueeb/is-what | TS | 51 | 21,631 | +164% | 128 | 6.2% | 34% | 규칙2 탈락 |
| ajtowf/ng2_play | TS | 44 | 13,028 | +338% | 64 | 12.5% | 41% | 규칙2 탈락 |
| a8m/mark · shaovie/goev · JNKKKK/pianochord.io 외 | | | 61,651~221,176 | 초과 | | | | 규칙1 탈락 |

**Go·TypeScript 후보는 하나도 남지 않았다** — 그 구간의 저장소는 우회 임계값을 넘거나
청크가 너무 적었다. 언어 다양성(규칙 6)은 이번에 포기한다.

- [x] **선정: `teaey/apns4j`** (승인됨) — 여유 65%로 경계에 걸치지 않고, `network`/`keystore`/
      `protocol` 로 층이 갈려 질의를 흩기 좋다. 오래된 라이브러리라 소스가 안 흔들린다.
      Java 지만 웹앱이 아니라 라이브러리라 기존 Java 저장소와 성격이 다르다

### 4단계: apns4j 평가셋 - 2026-08-19

- [x] `EVAL_SETS["apns4j"]` — 질의 **16개** (한국어 10 + 식별자 6). 소스 32파일을 전부 읽고
      **정답이 실재하는 것만** 채택했다
- [x] 검증(청킹만, 무과금): **정답 부재 0건 · 판정 헐거움 0건**.
      정답 비율 0.6~1.2% 로 v1 이 걸렸던 "사실상 파일 검색" 함정(최대 100%)에서 멀다

**앞의 둘과 다른 점 — 이게 이 저장소를 고른 값이다**
- **한국어 주석이 없다.** air·marryday 는 한국어 주석이 한국어 질의를 도왔고(그 부작용이
  CSS 노이즈였다), 여기는 한국어 질의가 영문 식별자·구조와 맞아야 한다.
  **임의의 저장소를 받는 서비스에서는 이쪽이 일반적인 조건이다**
- 웹앱이 아니라 라이브러리다 (층이 갈려 질의를 흩기 좋다)

**정답을 복수로 둔 질의 셋** — 하나로 못 박으면 나머지를 찾아도 오답이 되는 경우다:
- `ap_ko_05` 재시도 루프 / 기본 횟수 상수
- `ap_ko_07` JSON 직렬화 본체(`append`) / 진입점(`toJsonString`)
- `ap_id_02` `PayloadSender` 구현이 **동기 채널과 비동기 서비스 둘**이다

`ap_id_03`(Payload 상속)은 air `id_04` 와 같은 종류로 **2a 회귀 감시**용이고,
`ap_id_05` 는 원본 오타(`resolove`)를 그대로 써서 철자가 흔들리는 식별자를 보는 질의다.

- [x] `EVAL_SET_VERSION` 은 2 유지 — 새 셋을 **추가**했을 뿐 기존 판정 조건을 바꾸지 않았다
      (로그 키에 repo 가 들어 있어 셋끼리 겹치지 않는다)
- [x] 검증: pytest **183 passed / 62 skipped**(DB 정지). LLM 실호출 없음

### 5단계: 우회 분기 구현 - 2026-08-19

- [x] `repo_snapshots.source_bundle` / `source_tokens` 열
  - **`context` 에 합치지 않는다** — `run_summary()` 가 같은 문자열을 받으므로 합치면
    요약 비용까지 커진다. 대화에서만 이어 붙인다
  - `source_bundle IS NOT NULL` 이 곧 "이 스냅샷은 우회 경로다"
- [x] `indexer._try_full_injection()` — 수집 직후 판정. 바이트 사전 게이트 → 토큰 확정
  - 빌드를 **청크 0개로 완료 처리**한다. `is_ready()` 가 True 가 되어 "색인 중" 배너 없이
    바로 답하고, 검색은 빈 목록을 준다 — 근거는 스냅샷의 번들에서 온다.
    기존 빌드 생애·롤백·관리자 화면을 그대로 재사용한다
- [x] `build_chat_messages(source_bundle=...)` — 번들을 **캐시 접두사 안**에 넣는다
  - 스니펫과 정반대다. 스니펫은 질문마다 달라지니 캐시 뒤, 번들은 스냅샷마다 고정이니 캐시 앞
  - 브레이크포인트는 그대로 1개. RAG 경로의 스냅샷 블록은 **한 바이트도 안 바뀐다**(테스트로 고정)
- [x] `chat.py` — 번들이 있으면 검색하지 않는다. 소스가 이미 다 들어가 있어 검색해 봐야
      그 일부를 두 번 보내는 셈이고, 스니펫은 캐시 뒤라 매 질문 정가다
- [x] `CHAT_SYSTEM_PROMPT` — 코드가 오는 두 형태를 설명. "검색된 범위에는 없습니다"는
      **검색 경로에서만** 쓰도록 제한했다 (전체 소스가 왔는데 그 말을 하면 거짓이다)
- [x] `conftest` 에 `billed` 마커 — 과금되는 측정이 실수로 도는 일이 없어야 한다
- [x] 검증: pytest **249 passed / 3 skipped**(DB 기동). 신규 11건
      (우회 분기 4 · 번들 조립 3 · 캐시 배치 3 · 추정 대체 1)

### 6단계: 인용 정확도 측정 — 전체 주입이 이겼다 - 2026-08-19

`tests/test_citation_quality.py` (`-m billed`). 답변이 정답 파일을 짚었는지를 문자열
매칭으로 센다 — LLM 심판 없이 결정적이고, **두 경로를 같은 자로 잰다.**
판정 기준은 측정 전에 고정했다: 올라야만 켠다, 동률·하락이면 RAG 유지.

| 지표 | RAG | 전체 주입 |
|---|---:|---:|
| **인용 정확도** | 0.75 | **1.00** |
| 한국어 | 0.60 | **1.00** |
| 식별자 | 1.00 | 1.00 |

**차이는 전부 한국어 질의에서 났다.** 뒤집힌 4개(`ap_ko_01`·`06`·`07`·`10`)는 모두
한국어이고, 식별자 6개는 RAG 도 이미 만점이었다. 이 저장소에 **한국어 주석이 없어서**
한국어 질의가 영문 식별자로 건너가야 하는데, 검색이 거기서 실패하고 전체 주입은 그 다리가
필요 없다. air·marryday 는 한국어 주석이 그 다리를 대신 놔 주고 있었다.

**비용 — 측정치를 그대로 읽으면 안 된다**

| | 비캐시입력 | 캐시쓰기 | 캐시읽기 | 출력 | 합계 |
|---|---:|---:|---:|---:|---:|
| RAG | 41,542 | 0 | 0 | 6,012 | $0.1432 |
| 전체 주입 | 916 | 35,275 | 529,125 | 7,322 | $0.2691 |

**측정은 16질의를 연달아 물어 w̄ = 0.17 이다.** 실사용 세션은 2~6질의(w̄ = 0.4538)라
이 비율(1.88배)은 운영 비용이 아니다. 실측 배율로 환산하면:

> RAG $0.0237/질문 → 전체 주입 **$0.0642/질문 = 2.71배** (예산 4배 이내)

- [x] 총 과금 **$0.4123** (승인 $0.9 이내)

**측정의 한계 둘 (기록해 둔다)**
- 이 측정의 `context` 는 최소 문자열이라 **실서비스의 파일 목록(최대 200개)이 빠져 있다.**
  두 경로에 똑같이 빠졌으니 비교는 공정하지만, RAG 의 절대 수치(0.75)는 실서비스보다
  낮게 나왔을 수 있다 — 파일 목록만 보고도 파일을 짚을 수 있기 때문이다
- 그 탓에 RAG 쪽 접두사가 캐시 최소 길이(1,024토큰) 미달이라 **캐시가 아예 안 걸렸다**
  (쓰기·읽기 0). 실서비스 RAG 는 접두사가 ~5,800토큰이라 캐시가 걸린다

### 7단계: 화면에서 판정 - 2026-08-19

`/analyze` 로 apns4j 를 실제로 넣어 우회 경로가 도는지 확인했다 (Chrome 확장 연결됨).

- [x] **색인이 즉시 완료** — `status=completed · chunks 0`. 임베딩이 아예 돌지 않는다
- [x] DB: 스냅샷 #23 `source_tokens=34,467` · `source_bundle` 80,895자 · 활성 빌드 청크 0
- [x] **사용자 화면에 색인 배너가 뜨지 않는다** — 분석 직후 바로 질문할 수 있다.
      큰 저장소에서 "코드를 처음 읽는 중"이 뜨던 자리다
- [x] 답변이 파일·행을 짚는다 (아래 정확도 참고)

**캐시가 설계대로 동작한다** (실서비스 `runs.jsonl`)

| 턴 | 비캐시입력 | 캐시쓰기 | 캐시읽기 | 비용 |
|---|---:|---:|---:|---:|
| 1 | 559 | **37,674** | 0 | $0.1004 |
| 2 | 1,098 | 0 | **37,674** | $0.0161 |

번들이 캐시 접두사에 들어가 2턴부터 0.1배로 읽힌다. 첫 턴이 비싼 것이 이 방식의 성질이고,
`w̄` 가 세션 길이에 지배되는 이유가 이 표에 그대로 보인다.

**화면에서 찾은 것 둘**

- [x] **`/admin/snapshots` 가 우회를 구분하지 못했다** — 청크 0 으로만 보여 소스가 없는
      저장소·깨진 색인과 똑같아 보였다. `list_all()` 에 `full_injection`·`source_tokens` 를
      실어 **"전체 주입 34,467토큰"** 으로 표시하도록 고쳤다
- [x] **행 번호가 항상 정확하지는 않다 — 번들이 아니라 모델 쪽이다.**
      `this.size = (executorSize > processors) ? ...` 를 **35행**이라 했으나 실제는 **48행**이다
      (35행은 같은 이름의 필드 선언 `private final int size;`). 파일과 인용한 코드는 맞다

**무료 검증 — 코드 버그인지 모델 오류인지 (2026-08-19)**

번들이 틀린 번호를 실었을 가능성을 먼저 봤다. 의심 지점 둘을 다 확인했다:

| 검사 | 결과 |
|---|---|
| `splitlines()` 가 편집기보다 더 끊는 파일 (`\v` `\f` `\x1c` `\x85` `` 등) | **0건** |
| 번들의 `N\|` 을 원문 N 번째 줄과 직접 대조 | **2,340줄 중 불일치 0건** |
| 문제의 35행·48행이 번들에 그 번호로 실려 있는가 | **둘 다 그대로 실려 있다** |

**번들은 정확하다. 모델이 옳은 번호를 받고도 틀린 줄을 짚었다** — 같은 이름(`size`)의
필드 선언 줄에 앵커가 걸린 것으로 보인다. `build_source_bundle()` 은 고칠 것이 없다.

- [x] 줄 번호를 넣은 판단은 유지한다 — 관찰 3건 중 2건은 행 범위가 소스와 정확히 일치했고
      (`KeyStoreGetter` 41~100·102~124, `JsonParser` 64~73·75~108), 번호를 아예 안 주면
      모델이 **전부** 지어내게 된다. +15.8% 토큰의 값은 남아 있다
- [x] 줄 번호 정확도를 별도 지표로 쟀다 — `tests/test_line_accuracy.py` - 2026-08-19
      (아래 '행 번호 정확도' 절. **무과금** — 저장된 답변을 다시 읽었다)

### 판정 — 사전 고정 기준 대조 - 2026-08-19

> **측정 전에 고정한 기준** (`test_citation_quality.py` docstring):
> 전체 주입이 **떨어지면 우회를 접는다. 동률이면 RAG 유지**(비용·지연이 낮다).
> **올라야만** 우회를 켠다.

| 지표 | RAG | 전체 주입 | 차이 | 기준 대조 |
|---|---:|---:|---:|---|
| **인용 정확도** | 12/16 = 0.75 | **16/16 = 1.00** | **+0.25** | 올랐다 → **켠다** |
| 한국어 | 6/10 = 0.60 | 10/10 = 1.00 | +0.40 | |
| 식별자 | 6/6 = 1.00 | 6/6 = 1.00 | ±0 | |
| 질문당 비용(실사용 환산) | $0.0237 | $0.0642 | 2.71배 | 예산 4배 이내 |

**결론: 작은 저장소 RAG 우회를 켠다.** 품질이 올랐고 비용이 예산 안이다.

**이 판정의 범위** — 넘겨짚지 않도록 적어 둔다:
- 저장소 **1개 · 질의 16개**의 결과다. 임계값 이하의 모든 저장소로 일반화한 것이 아니다
- 이긴 이유가 특정돼 있다: **한국어 주석이 없는 저장소에서 한국어 질의**가 전부 뒤집혔고,
  식별자 질의는 RAG 도 이미 만점이었다. 한국어 주석이 있는 저장소라면 격차가 줄 수 있다
- RAG 쪽 절대 수치(0.75)는 측정용 `context` 에 파일 목록이 빠져 실서비스보다 낮을 수 있다.
  **다만 그 한계는 격차를 줄이는 방향이지 늘리는 방향이 아니다** — 결론은 뒤집히지 않는다

## 1번 과제 완료 — 작은 저장소 RAG 우회 - 2026-08-19

임계값 57,000토큰(4배 예산에서 역산) · `teaey/apns4j` 로 검수 · 인용 정확도 0.75 → 1.00.
총 과금 약 $0.55 (측정 $0.4123 + 화면 확인 약 $0.14).

**평가셋 공수** — 하네스는 이미 `EVAL_SETS` + `parametrize` 구조라 **코드 작업은 없다.**

| 항목 | 공수 | 비고 |
|---|---|---|
| 소스 읽기 (32파일 34,467토큰) | 판단 작업 | 무과금 |
| 질의 초안 20개 → 16개 채택 (한국어 10 + 식별자 6) | 판단 작업 | 기존 셋과 같은 구성 |
| **정답 실재 확인 + `answers` 인코딩** | 판단 작업 | **여기서 두 번 틀렸다** (`py_id_06` 요청/응답 뒤바뀜, `py_id_03` 정답 못박기) — 청킹만 돌려 검증 가능, 무과금 |
| 첫 인덱싱 | 약 4.5분 | 168청크 (236청크가 378초였다) |
| 평가 1회 | 약 90초 | 17질의가 99초였다 |
| **인용 정확도 측정 (두 경로)** | **약 $0.9** | 승인분 $0.7 보다 조금 높다. 전체주입 $0.59 + RAG $0.33 |

- [x] 사전 게이트 500KB 검증: Java 저장소 119KB 통과 / Python·JS 저장소 2,391KB 탈락 (설계대로)
- [x] 대체 추정값 2.0 검증: 실측 2.05·2.41 보다 낮다 → 토큰을 **많게** 잡아 우회를 덜 켠다 (안전 방향)
- [x] 검증: pytest **183 passed / 61 skipped**(DB 정지). 신규 6건. LLM 실호출 없음 —
      `count_tokens` 는 추론을 돌리지 않아 무과금이다

### plan.md ↔ 코드 대조 - 2026-08-19
과제를 끝낸 뒤 문서와 실제 코드를 맞춰 봤다. 완료로 적힌 것은 전부 실재했고 **불일치 3건**만 나왔다.
- [x] Stage 3 '남은 문제'의 RAG 우회 항목이 `[ ] 아직 분기가 없다` 로 남아 있었다 → 체크 + 참조 추가
  - 같이 고친 것: 그 줄의 "air 11만 자 ≈ 30k 토큰"은 실측 62,380 과 어긋난 추정이었다
- [x] `.env.example` 에 `FULL_INJECTION_MAX_TOKENS`·`FULL_INJECTION_MAX_SOURCE_BYTES` 가 없었다
  - 우회 전용 블록으로 추가. **임계값을 임의로 올리면 비용이 는다**는 경고를 값 옆에 적었다
  - 검증: `config.py` 의 `os.environ.get` 키와 예시 파일 키가 **21개 모두 일치**
    (`.env.example` 작성 시점의 9개에서 늘어난 뒤로 대조가 없었다)
- [x] 테스트 수 갱신 — 현재 **253개 수집**. 실측 `186 passed / 67 skipped`(DB 정지)
  - 문서의 마지막 수치는 244(183+61)·252(249+3)로, 6·7단계 이후 갱신이 빠져 있었다
  - skip 이 67 인 것은 DB 정지 + `evaluation`·`billed` 마커 제외분이다. **실패 0**

**임계값 — 확정: 57,000 토큰** (4배 규칙, 실측 역산). 사전 게이트 500KB, TTL 5분 유지 + 미스율 계측.

숫자를 직접 고르지 않고 규칙에서 뽑은 이유는 CLAUDE.md §7 이다 — 특정 저장소가 통과하도록
맞춘 값이면 다른 저장소에서 틀린다. **그 결과 지금 가진 저장소 둘 다 탈락했고, 그대로 둔다.**

검수 기준(코드는 이 이름을 모른다): Java 저장소 62,380토큰(9% 초과·탈락) /
Python·JS 저장소 1,057,764토큰(18배 초과·탈락).

### 선행: 비용 계산이 캐시를 빼먹고 있었다 - 2026-08-19

**문제.** `estimate_cost()` 가 `usage.input_tokens` 만 셌는데 그 값은 **캐시에 안 걸린 나머지만**
센 것이다. `cache_creation_input_tokens` 는 받지도 않았고 `cache_read_tokens` 는 기록만 하고
가격에 안 들어갔다. 우회를 켠 뒤 두 경로를 비교해도 그 수치로는 판단할 수 없다.

- [x] `estimate_cost(..., cache_write_tokens=, cache_read_tokens=)` + `CACHE_WRITE_MULTIPLIER`
      1.25 / `CACHE_READ_MULTIPLIER` 0.10. `_call()` 이 `cache_creation_input_tokens` 를 받아 넘긴다
  - 배율 상수를 따로 뺀 이유: `ttl="1h"` 로 바꾸면 쓰기가 2.0배가 된다. 전체 주입에서 검토 대상이다
- [x] `billable_tokens()` — 일일 상한도 같은 누락이 있었다. `record_tokens()` 호출부(analyze·chat)를
      교체. **캐시 몫을 빼고 세면 전체 주입에서는 상한이 사실상 꺼진 것과 같아진다**
- [x] `run_log` · `usage_stats.TOKEN_FIELDS` · `RunResult` · 관리자 화면 3곳에 캐시 쓰기 추가
  - 옛 기록은 **소급하지 않는다**(단가 정책과 동일). `cache_write_tokens` 가 없어 0 으로 집계되고
    그 시절 `cost_usd` 는 과소 추정으로 남는다

**실측 세션(marryday 6턴, 2026-08-17)으로 검산**

| | 값 |
|---|---:|
| 고치기 전 (로그에 남은 값) | $0.0529 |
| 고친 뒤 (실제 청구 추정) | **$0.0782** |
| 누락분 | $0.0252 (**32.3%**) |
| 일일 상한이 세야 할 토큰 | **58,628** (전에는 15,362 — 3.8배 과소) |

- [x] 검증: pytest **177 passed / 61 skipped**(DB 정지 상태). 신규 4건(캐시 단가 3 · 상한 1).
      LLM 실호출 없음 — 순수 계산이다

## 2번 과제: 소형 다국어 모델 - 2026-08-19 착수

목적: 인덱싱 시간과 모델 크기를 줄인다. 지금 모델(e5-large 2,132MB·24층)이 큰 저장소에서
임베딩만 40~96분을 쓴다. **품질을 지키면서** 작은 모델로 내려갈 수 있는지 본다.

### 조사 — 후보가 fastembed 목록 밖에 있다
- [x] fastembed 0.8.0 의 **다국어 모델은 5개뿐**이고 검색용은 지금 쓰는 e5-large 하나다
  - `paraphrase-multilingual-*` 둘은 STS 모델(STEP 1 에서 이미 제외), `jina-v2-base-de/code`
    는 한국어가 아니다. **목록 안에는 소형 다국어 검색 모델이 없다**
- [x] `TextEmbedding.add_custom_model()` 이 있다 → 목록 밖 모델도 등록해서 쓸 수 있다
- [x] e5 계열은 ONNX 를 직접 배포한다 (HF 파일 목록 조회, 내려받지 않음)

| 모델 | ONNX(fp32) | 차원 | 층 | 현재 대비 |
|---|---:|---:|---:|---|
| multilingual-e5-small | **448MB** | 384 | 12 | **4.8배 작음** |
| multilingual-e5-base | 1,059MB | 768 | 12 | 2.2배 작음 |
| multilingual-e5-large (현재) | 2,132MB | 1024 | 24 | — |

**같은 계열이라 접두어 규약(`query: `/`passage: `)이 같다** → 코드 변경은 모델 등록과
테이블 추가뿐이다. `bge-m3` 도 ONNX 가 있지만 large 급이라 소형화 목표에 안 맞는다.

### 측정 환경 고정 (선행 조건 — 승인됨)
지난 실패 원인은 **A 를 전부 → B 를 전부** 순서로 1회씩, 그것도 전체 인덱싱(74~96분)을
잰 것이다. 시간대별 배경 부하가 통째로 한쪽에 실렸다.
- 전체 인덱싱을 재지 않는다 — 소스 캐시의 **고정 청크 200개**만 잰다
- **인터리브 A→B→A→B→A→B** (지난 실패의 직접적 수정). 부하가 양쪽에 균등히 섞인다
- **중앙값**으로 보고 **워밍업 1배치는 버린다**(첫 배치에 ONNX 그래프 최적화가 섞인다)
- 폐기 기준을 측정 전에 고정: `process_time/perf_counter` 로 CPU 점유를 함께 기록,
  시행 간 편차 ±15% 초과면 그 라운드 폐기. 앞뒤 카나리가 10% 넘게 다르면 회차 폐기
- **시간은 2차 지표다.** 채택 여부는 품질로 가르고 시간은 "몇 배"만 본다

### 승인된 범위 (측정 전에 고정)
- 후보: **e5-small 먼저** (448MB·384차원). 무너지면 base 로 올린다
- 측정: **air + apns4j 먼저** (33질의, 236·168청크라 빠르다). 통과하면 marryday 추가
- **채택 기준: 한국어 Recall@8 이 e5-large 와 동률 이상.** 떨어지면 기각
- `py_ko_05`(278위, hard)는 marryday 질의라 이번 범위 밖. 3단계로 넘어가면 함께 본다

### 단계
- [x] 1. e5-small 등록 (`embeddings._register_if_custom`) - 2026-08-19
  - fastembed 목록에 없으면 등록하고, 있으면 아무것도 하지 않는다
  - `pooling=MEAN`·`normalization=True` 는 짐작이 아니라 모델 저장소에서 확인한 값
    (`1_Pooling/config.json` 의 `pooling_mode_mean_tokens: true`)
  - 검증: 차원 384 · 토큰 한도 512 · 접두어 적용 · **L2 노름 1.000000**(정규화 확인)
- [x] 2. `code_chunks_384` (+ 뒤에 `code_chunks_768_e5`) 테이블 - 2026-08-19
  - **차원이 아니라 모델이 테이블을 가른다** — 맨 위 `code_chunks` 도 768 이지만 jina 벡터다.
    같은 테이블에 넣으면 타입 오류 없이 **조용히 섞여** 거리 계산이 무의미해진다
  - `build_id` 는 인라인이 아니라 아래 ALTER 로 붙인다. `index_builds` 가 파일 뒤에 있어
    인라인 참조는 기동 시 실패한다 (넣었다가 고쳤다)
  - 검증: `vector(384)` · 인덱스 4개 · 기존 청크 15,766행과 대화 데이터(메시지 32·세션 9) 무변경
- [x] 3. 시간 측정 하네스 `tests/test_embed_speed.py` (인터리브+카나리) - 2026-08-19
  - **작성만 하고 실행하지 않았다** — 품질로 먼저 갈렸고, 시간은 2차 지표라 순서를 바꿨다.
    품질에서 기각되면 시간을 잴 이유가 없다
- [x] 4. 평가 실행 (air + apns4j) - 2026-08-19
  - **기준값이 과거 기록과 정확히 일치**했다 (air 한국어 R@8 0.67 · MRR 0.5028 · 평균 11.25).
    하네스가 재현된다는 확인이라 이후 비교를 믿을 수 있다
  - apns4j 의 e5-large 기준값은 없었다(4단계에서 청킹만 검증했다) → 이번에 새로 쟀다
- [x] 5. 판정 — **e5-small·e5-base 둘 다 기각, e5-large 유지** (아래 '판정' 절)

### 측정 결과 - 2026-08-19

**한국어 Recall@8 (채택 기준 지표)**

| 모델 | air (12질의) | apns4j (10질의) | 합산 (22질의) |
|---|---|---|---|
| e5-large (현재) | **0.67** (8/12) | 0.50 (5/10) | **0.591** (13/22) |
| e5-base | 0.58 (7/12) | 0.60 (6/10) | **0.591** (13/22) |
| e5-small | 0.42 (5/12) | **0.70** (7/10) | 0.545 (12/22) |

**부가 지표**

| 모델 | air 한국어 MRR | air 평균순위 | apns4j 한국어 MRR | apns4j 평균순위 | 식별자 R@8 |
|---|---|---|---|---|---|
| large | 0.5028 | **11.25** | **0.4411** | **9.0** | 1.00 / 1.00 |
| base | **0.5061** | 23.75 | 0.4310 | 12.0 | 1.00 / 1.00 |
| small | 0.2496 | 49.67 | 0.4411 | 16.7 | **0.80** / 1.00 |

**임베딩 시간** (단일 측정 — 인터리브를 안 거쳤으므로 **배율만** 읽을 것)

| 모델 | air 236청크 | apns4j 168청크 | 모델 크기 |
|---|---|---|---|
| large | 97.0s | 56.3s | 2,132MB |
| base | 29.9s | 16.2s | 1,059MB (약 3.2배 빠름) |
| small | 11.3s | 5.1s | 448MB (약 8.6~11배 빠름) |

**e5-small: 기각.** 어느 해석으로도 하락한다 — 합산 0.545 < 0.591, air 는 0.67 → 0.42,
식별자까지 1.00 → 0.80 으로 떨어졌고 평균순위가 11.25 → 49.67 로 4.4배 악화됐다.
apns4j 에서만 오른 것(0.50 → 0.70)은 10질의 중 2개 차이라 노이즈로 본다.

**e5-base: 판정 보류 — 내가 정한 기준에 빈틈이 있었다.**
합산은 13/22 로 **정확히 동률**인데 저장소별로는 **방향이 반대**다(air 하락 · apns4j 상승).
"한국어 Recall@8 동률 이상"이라고만 정하고 **집계 단위(저장소별/합산)를 명시하지 않아서**,
합산으로 읽으면 채택이고 저장소별로 읽으면 기각이다. 유리한 쪽을 고르면 기준을 measured
후에 바꾸는 셈이라 그렇게 하지 않는다.
- 덧붙여 base 는 **평균순위가 양쪽 다 악화**됐다(11.25→23.75, 9.0→12.0). R@8 이 같아도
  순위 분포는 나빠졌다는 뜻이라 변별력이 낮다는 신호로 읽힌다
- **저장소별로 방향이 반대인 것 자체가 표본 부족의 전형적 신호다** (22질의)

**한국어 주석 유무로 갈리는 것처럼 보인다** — air 는 한국어 주석이 있어 큰 모델이 유리하고,
apns4j 는 없어서 작은 모델이 오히려 나았다. 다만 이건 저장소 2개의 관찰이라 가설일 뿐이다.

### 집계 단위 확정 - 2026-08-19
- [x] **저장소별로 모두 동률 이상**이어야 채택한다 (합산이 아니다)
  - 임의의 저장소를 받는 서비스라 특정 유형에서 무너지면 **그 사용자에게만 피해가 간다.**
    합산 평균은 그 손해를 다른 저장소의 이득으로 가려 버린다
  - 이 기준으로 **e5-base 도 기각** — air 0.58 < 0.67. 합산으로는 동률(13/22)이었지만
    그 해석을 쓰지 않기로 확정했다
- [x] 기준을 **측정 후에 정한 것이 이번의 흠이다.** 다음 모델 비교부터는 집계 단위까지
      포함해 측정 전에 못 박는다. (1번 과제 때는 "올라야만 켠다"를 미리 정해 두고 지켰다)

### marryday 추가 — 판정이 아니라 가설 검증 - 2026-08-19
저장소별 기준을 택한 시점에서 두 모델 다 이미 기각이다. **marryday 측정은 채택 판정을
바꾸지 못한다.** 그래도 재는 이유는 위 가설("한국어 주석이 있으면 큰 모델이 유리하다")
때문이다 — marryday 는 한국어 주석이 많은 저장소라, 가설이 맞다면 여기서도 작은 모델이
떨어져야 한다. 다음에 다른 모델을 볼 때 쓸 지식이라 남긴다.
- e5-large 기준값은 **재측정하지 않고 기존 기록(한국어 R@8 0.80)을 쓴다.** air 에서
  과거 기록이 정확히 재현되는 것을 확인했고, 같은 청킹 규칙·같은 셋 v2 다. 96분을 아꼈다

**한국어 Recall@8 — 저장소 3개 전부**

| 모델 | air (한국어 주석 있음) | marryday (한국어 주석 많음) | apns4j (한국어 주석 없음) |
|---|---|---|---|
| **e5-large (현재)** | **0.67** | **0.80** | 0.50 |
| e5-base | 0.58 | **0.80** (동률) | **0.60** |
| e5-small | 0.42 | 0.40 | **0.70** |

**가설이 지지됐다 — 3개 저장소 모두 방향이 일치한다.**
한국어 주석이 있는 저장소(air·marryday)에서는 작은 모델이 무너지고
(0.67→0.42, **0.80→0.40**), 없는 저장소(apns4j)에서는 오히려 올랐다(0.50→0.70).
한국어 주석은 한국어 질의와 직접 맞아떨어지는 다리인데, **그 다리를 읽어내는 능력이
모델 크기에 달려 있다.** 주석이 없으면 어차피 영문 식별자로 건너가야 해서 큰 모델의
이점이 줄고, 작은 모델의 거친 매칭이 우연히 유리해지기도 한다.

**평균순위는 작은 모델이 일관되게 나쁘다** — R@8 이 같아도 순위 분포가 무너진다.
marryday 에서 base 는 R@8 이 동률(0.80)인데 평균순위는 30.8 → 49.3 으로 악화됐다.

### 판정 — 둘 다 기각, e5-large 유지 - 2026-08-19

> **확정된 기준: 한국어 Recall@8 이 저장소별로 모두 동률 이상.**

| 모델 | air | marryday | apns4j | 판정 |
|---|---|---|---|---|
| e5-base | **0.58 < 0.67** | 0.80 (동률) | 0.60 (상승) | **기각** — 3개 중 1개에서 하락 |
| e5-small | **0.42 < 0.67** | **0.40 < 0.80** | 0.70 (상승) | **기각** — 2개에서 크게 하락 |

- [x] **`.env` 는 손대지 않았다.** 측정은 프로세스 환경변수로만 했고 서비스는 계속
      e5-large·`code_chunks_1024` 를 쓴다. 재색인도 일어나지 않았다
- [x] 검증: pytest **249 passed / 5 skipped**(DB 기동). 신규 1건은 시간 측정 하네스다

**얻은 것 — 기각이지만 빈손이 아니다**
- `add_custom_model` 경로가 열렸다. fastembed 목록 밖 모델을 이제 등록해서 잴 수 있다
- 차원별 테이블이 셋(384·768_e5·1024)이 되어 다음 후보는 `CHUNK_TABLE` 만 바꾸면 잰다
- **모델 크기를 줄이는 방향은 이 평가셋에서 막혔다.** 다음에 인덱싱 시간을 줄이려면
  모델이 아니라 다른 축(양자화 ONNX, 청크 수 줄이기, GPU)을 봐야 한다
- 시간 측정 하네스(`test_embed_speed.py`)는 **실행하지 않았다** — 품질에서 먼저 갈렸다.
  다음 후보를 잴 때 그대로 쓴다

**정리 — 승인받아 실행 - 2026-08-19**
- [x] 기각된 두 모델의 평가 청크 **9,538행 삭제** (384: 4,769 · 768_e5: 4,769)
  - 청크를 직접 DELETE 하지 않고 **`index_builds` 를 지웠다** — 청크가 `build_id` 에
    `ON DELETE CASCADE` 로 매여 함께 사라진다. 빌드만 남기면 '완료됐는데 청크 0개'가 되어
    **전체 주입(우회) 스냅샷과 구분이 안 된다**
  - 함께 지운 것: 두 테이블의 `snapshot_index_status` 6행 · `index_builds` 6행
  - **테이블은 남긴다** — 다음 모델 비교에서 `CHUNK_TABLE` 만 바꿔 재사용한다
  - 삭제 전 미리보기로 대상을 먼저 확인했고, `WHERE table_name = ANY(...)` 로 두 테이블에
    매인 것만 대상으로 삼았다
- [x] 검증: 삭제 후 `code_chunks_1024` **15,967행 그대로**, 메시지 32 · 세션 9 ·
      스냅샷 6 무변경. 남은 색인상태는 `code_chunks_1024` 6행 + `code_chunks` 2행뿐
      (후자는 앞서 '미사용'으로 남겨 둔 768 잔재로, 이번 작업과 무관하다)

## 조용한 오염 막기 — 라이브러리 버전과 문서 - 2026-08-19

소형 모델 측정 중에 드러난 것들. 셋 다 **오류를 내지 않고 조용히 틀려지는** 종류다.

### fastembed 가 pooling 을 바꾸면 인덱스가 무효가 된다
측정 중 라이브러리가 직접 경고했다 — *"e5-large **now uses mean pooling instead of
CLS embedding**. consider pinning fastembed version to 0.5.1"*. **0.5.1 이후 이미 한 번
바꿨다는 뜻이다.** 그런데 `requirements.txt` 는 `fastembed>=0.8` 로 상한이 없었고,
`rule_version()` 의 재료는 모델 **이름**뿐이라 라이브러리가 바뀌어도 해시가 그대로다.
→ 같은 코드·같은 모델인데 벡터가 달라지고, **'재색인 필요'가 뜨지 않은 채**
옛 인덱스와 새 질의가 섞인다. Stage 4 가 막은 구멍이 라이브러리 축에 남아 있었다.

- [x] `fastembed>=0.8,<0.9` 상한 + 근거 주석
- [x] `test_fastembed_version_is_within_verified_range` — 범위를 벗어나면 실패한다
- [x] **`rule_version()` 에는 넣지 않았다.** 넣으면 임베딩과 무관한 패치 업데이트마다
      모든 인덱스가 '재색인 필요'로 떠서, 그 표시를 아무도 안 믿게 된다
      (주석 편집에 반응하지 않게 AST 정규화를 넣은 것과 같은 판단).
      재색인을 강제하지 않고 **사람이 알아차리게만** 한다

### `.env.example` 이 조용히 낡는다
손으로 갱신하는 문서라 실제로 낡아 있었다(`FULL_INJECTION_*` 둘 누락).
- [x] `tests/test_config.py` — config.py 가 읽는 키와 예시 파일 키가 **양방향으로** 같은지
  - 빠진 설정(문서에 없음)과 유령 키(코드가 안 읽음)를 각각 잡는다
  - 정규식이 아무것도 못 잡아도 통과하는 **허위 통과**를 막는 테스트를 함께 뒀다
- [x] 검증: 세 테스트 모두 **일부러 깨뜨려 실제로 잡는 것을 확인**했다
      (키 제거 → 감지 / 유령 키 → 감지 / 버전 0.9.0 → 감지). 현재 양쪽 21개 일치

### 시간 측정 하네스 실행 검증 - 2026-08-19
만들어만 두고 한 번도 돌리지 않은 코드였다. 돌려 보니 **설계 결함이 하나 나왔다.**

| 모델 | 중앙값 | ms/청크 | 라운드 편차 | CPU |
|---|---:|---:|---:|---:|
| e5-large | 82.6s | 413.0 | 3.5% | 6.9x |
| e5-small | **8.9s** | **44.5** | 2.1% | 7.1x |

- [x] **카나리를 가장 작은 모델로 재고 있었다** — 20청크가 0.8초라 0.1초 노이즈가
      12% 편차로 잡혔다. 본 측정이 3% 로 안정적인데도 회차가 폐기되는 오탐이다.
      가장 느린 모델로 재도록 고쳐 분해능을 10배 올렸다
- [x] **고친 뒤에도 카나리는 10.9% 로 초과했다 — 이건 오탐이 아니라 진짜 신호다.**
      두 회차 모두 **뒤가 느렸다**(0.8→0.9, 8.5→9.4). CPU 를 7배로 5분 돌리는 동안
      기기가 완만히 느려진다는 뜻으로, 발열로 클럭이 내려간 것으로 보인다
- [x] **기준을 완화하지 않았다.** 측정 후에 기준을 바꾸면 기준이 아니게 된다.
      대신 판정 문구를 사실대로 고쳤다 — 카나리 초과는 "회차 폐기"가 아니라
      **"절대 시간은 못 믿음, 배율만 읽을 것"** 이다
- [x] **인터리브가 제 일을 했다는 증거** — 카나리가 11~12% 흔들린 두 회차에서
      라운드 편차는 2~4%, 배율은 **9.42배 / 9.27배**로 재현됐다.
      A→B→A→B 로 재면 느려짐이 양쪽에 균등히 실려 비율에서 상쇄된다.
      **지난번 실패(A 전부 → B 전부)가 왜 정반대 결과를 냈는지가 이걸로 설명된다**

이 배율은 **채택 판정과 무관하다** (e5-small 은 품질에서 이미 기각됐다).
하네스가 동작한다는 것과, 다음 후보를 잴 준비가 됐다는 것이 이 절의 결론이다.

- [x] 검증: pytest **190 passed / 68 skipped**(DB 정지, 258 수집). 신규 4건
      (설정 문서 정합성 3 · fastembed 버전 1). LLM 실호출 없음

## 미뤄 둔 과제 정리 - 2026-08-19

### 빈 `chat_sessions` 누적 — 원인을 없앴다
**전에는 "서버가 먼저 알 방법이 없다"로 닫아 뒀다.** `/analyze` 는 분석마다 세션을 만드는데
프론트가 localStorage 의 옛 세션을 복원하면 방금 만든 세션이 메시지 없이 남았고,
복원 가능 여부는 브라우저에만 있는 정보였다. **서버가 모르면 클라이언트가 알려주면 된다.**

- [x] `AnalyzeRequest.session_id` (선택) — 프론트가 갖고 있는 세션을 함께 보낸다
- [x] `_start_session(snapshot, existing)` — **재사용 조건은 '같은 스냅샷인가' 하나다.**
      스냅샷이 다르면 그 세션은 옛 코드를 보고 있어 이어 쓰면 안 된다
- [x] UUID 형식이 아니면 **DB 를 조회하지 않고 새로 만든다.** `/chat` 은 같은 상황에서
      400 을 내지만 여기서는 무시한다 — 이 값은 거들 뿐이라 분석이 그것 때문에 실패하면 안 된다
- [x] 프론트 — **요청 시점에는 정식 표기를 모른다**(응답에 있다). 입력 URL 에서 추정한 키로
      localStorage 를 찾는다. 표기가 정식과 다르면(저장소 이전) 못 찾을 뿐 전과 같이 동작한다 —
      **개선은 되고 나빠지지는 않는다**
- [x] 검증: pytest `test_analyze_api.py` **10 passed**(신규 5: 재사용·다른 스냅샷·없는 세션·
      잘못된 형식·캐시 미스 경로). `tsc --noEmit` 통과
  - 캐시 미스 경로에도 테스트를 뒀다 — 히트에서만 고치면 절반만 고친 것이다

### 행 번호 정확도 — 빈도를 알게 됐다
화면 확인 때 3건만 보고 "항상 정확하지는 않다"로 남겨 뒀던 것. `citation_evals.jsonl` 에
답변 전문이 남아 있어 **다시 부르지 않고** 셌다.

| 경로 | 판정 | 정확 | 판정불가 |
|---|---:|---:|---:|
| RAG | 8건 | 5 (62%) | 5 |
| 전체 주입 | 22건 | 10 (45%) | 4 |
| **합계** | **30건** | **15 (50.0%)** | 9 |

**전체 주입이 더 자주 틀린다.** RAG 는 스니펫에 행 번호가 붙어 오고 범위가 좁은데,
전체 주입은 8만 자 번들에서 모델이 위치를 스스로 추적해야 한다. 앞서 "번들은 정확하다,
모델이 옳은 번호를 받고도 틀린 줄을 짚었다"고 결론냈던 것의 정량화이고,
**어느 경로에서 더 심한지**는 이번에 처음 안 것이다.

- [x] **만들고 돌려 보니 판정 로직이 틀렸다** — 처음엔 55.4% 가 나왔는데, '틀림' 25건 중
      대부분이 `String`·`ApnsChannel`·`IOException` 같은 **이름 언급**이었다.
      "이 범위가 이런 일을 한다"는 서술을 "그 줄에 이 문자열이 있다"는 주장으로 읽은 것이라,
      모델이 아니라 **파서의 오탐**을 재고 있었다.
      코드를 그대로 인용한 것만 판정하도록 좁혔다(`CODE_LIKE`)
- [x] 한계를 문서에 적었다 — 의역은 판정하지 않고(모수에서 뺀다), 같은 조각이 여러 곳이면
      관대하게 본다. **정확도의 하한이 아니라 대략적 빈도**다. 표본도 저장소 1개·인용 30건이다

**이 수치로 무엇을 할 것인가는 별도 과제다.** 프롬프트에서 행 번호 요구 방식을 바꾸거나
검증 단계를 넣는 안이 있는데, 어느 쪽이든 과금 측정이 필요하다.

### 검증
- [x] **실제 DB 로 세션 재사용 확인**(대역이 아니라 진짜 `chats`) — 같은 스냅샷 재사용 /
      다른 스냅샷 새로 생성 / 잘못된 형식 / 없는 세션 네 경우 모두 의도대로.
      세션이 9 → 13(+4)로, 재사용이 없었다면 +5 였다. 검증용 4개는 지워 9개로 되돌렸다
- [x] pytest **258 passed / 6 skipped**(DB 기동). 신규 5건. LLM 실호출 없음

## `rate_limit.json`·`runs.jsonl` 의 DB 이전 - 2026-08-19

**보류를 권했으나 사용자가 진행을 지시했다.** 우려는 "DB 에 의존하면 `DATABASE_URL` 이 없을 때
상한이 통째로 꺼진다"였는데, **그 우려는 설계로 없앤다** — DB 가 있으면 DB, 없으면 지금의
파일 경로로 폴백한다. 그러면 다중 워커에서는 정확히 공유되고 DB 없는 환경도 그대로 돈다.

**핵심은 원자성이다.** 파일 구현은 프로세스 안 `threading.Lock` 으로 read-modify-write 를
직렬화하는데, 워커가 여럿이면 Lock 이 워커마다 따로라 카운트가 샌다. DB 경로는 Lock 이 아니라
**SQL 한 문장의 원자성**으로 푼다.

### 단계
- [x] 1. 스키마 — `runs` / `rate_limit_daily` / `rate_limit_hits`
  - `day` 는 앱이 넘긴 **로컬 날짜**다. `CURRENT_DATE`(서버 타임존)를 쓰면 집계와 경계가 어긋난다
  - IP 는 합계가 아니라 **개별 시각**을 저장한다 — 윈도우가 슬라이딩이라 count 로는 안 된다
- [x] 2. `run_log` DB 백엔드(`db/runs.py`) + 파일 폴백
  - **DB 가 켜져 있는데 쓰기가 실패해도 파일로 떨어뜨리지 않는다.** 두 곳에 나뉘면 집계가
    갈리고 어느 쪽이 진실인지 알 수 없게 된다. 읽기는 반대로 폴백한다(빈 표보다 낫다)
  - `ts` 를 **ISO 문자열로** 돌려준다 — `usage_stats` 가 `fromisoformat()` 으로 파싱하므로
    datetime 객체를 주면 집계가 통째로 깨진다. 테스트로 고정했다
- [x] 3. `rate_limit` DB 백엔드(`db/rate_limits.py`) + 파일 폴백
  - 일일 카운터는 `INSERT … ON CONFLICT DO UPDATE … RETURNING` **한 문장**으로 증가+확인
  - IP 윈도우는 한 문장으로 안 되므로 `pg_advisory_xact_lock` 으로 **그 IP 만** 직렬화
  - 상한 초과는 예외로 트랜잭션을 되돌린다 — 거절된 요청이 카운터를 올려놓고 가면 안 된다
  - **DB 장애 시에는 막지 않고 통과시킨다.** 상한은 비용을 지키는 장치이지 서비스의 관문이
    아니다. 장애 때 모든 분석이 429 가 되면 장애가 두 배가 된다
- [x] 4. 마이그레이션 `scripts/migrate_runs_to_db.py` — **31건 이관, 합계 일치**
  - 옛 기록에 `source`·`cached` 가 없어 NOT NULL 에 걸렸다. 화면이 지금까지 해석해 온 것과
    **같은 값**("lab", False)으로 채워 그 해석을 데이터에 고정했다
  - 두 번 돌려도 중복 없음(ts 로 건너뜀), 원본 파일은 지우지 않는다
- [x] 5. **다중 워커 실측 — 이 과제의 정당성이 여기서 확인됐다**

| 경로 | 프로세스 5개 × 10회 | 결과 |
|---|---:|---|
| 파일 (기존) | **3 / 50** | 47회 유실 |
| DB (신규) | **50 / 50** | 정확 |

**파일 경로는 "느슨해지는" 정도가 아니라 사실상 동작하지 않는다.** 동시 쓰기로 JSON 이
깨져 읽기 실패가 22번 났고, `_read_state()` 가 깨진 파일을 `{}` 로 처리하므로 그때마다
카운터가 0 으로 리셋됐다. 전에 적어 둔 "상한이 워커 수만큼 느슨해진다"는 **과소평가였다** —
워커 5개면 5배가 아니라 거의 무제한이 된다.

- [x] 검증: pytest **275 passed / 6 skipped**. 신규 17건
      (DB 기록 6 · DB 상한 11, 동시성 2건 포함). LLM 실호출 없음
  - 기존 파일 경로 테스트 22건이 DB 를 타면서 깨졌다 → 격리 fixture 4곳에서 DB 를 명시적으로
    끈다. **파일 경로도 계속 검증한다** — DB 없이 도는 것이 그 경로의 존재 이유다
  - `conftest` 의 `db` fixture 가 새 테이블 셋을 함께 비운다. `repos` CASCADE 로는 안 지워져
    앞선 테스트의 카운터가 남는다

**사고: 격리를 고치기 전에 테스트를 돌려 개발 DB 를 오염시켰다.**
파일 경로를 `tmp_path` 로 격리하던 fixture 들이 **DB 경로는 막지 못한다.** 그 상태로 전체
테스트를 한 번 돌렸더니:
- `runs` 에 테스트 기록 19행 (`facebook/react`, `psf/requests`, model `m`)
- 오늘 카운터가 **호출 27 · 토큰 10,035,399** — 상한(5,000,000)의 2배.
  **그대로 뒀다면 실제 서비스가 429 를 냈다**

되돌릴 수 있었던 것은 원본 파일이 그대로 남아 있었기 때문이다(`logs/runs.jsonl` 31건,
`cache/rate_limit.json` 호출 4 · 토큰 120,530). 마이그레이션이 파일을 지우지 않은 판단이
여기서 값을 했다.
- [x] 복구: 원본 ts 에 없는 `runs` 19행 삭제, 카운터를 파일의 진짜 값으로 덮어씀,
      IP 기록은 윈도우(1시간) 밖이라 비움
- [x] 재발 확인: 격리를 고친 뒤 전체 테스트를 다시 돌려도 **DB 31행·카운터 4/120,530 그대로**

**교훈: 저장소를 바꾸면 테스트 격리도 함께 바뀐다.** 파일 경로만 격리하는 fixture 는
저장소가 DB 로 옮겨간 순간 아무것도 막지 못하는데, 그 사실이 테스트 실패가 아니라
**조용한 오염**으로 나타난다(테스트는 통과할 수도 있다).

### 남은 것
- **`scripts/` 는 CLAUDE.md §6 에 없는 종류다.** 일회성 운영 스크립트를 둘 곳이 규칙에
  없어서 `Back/scripts/` 를 새로 만들었다 (`app/db/` 를 신설할 때와 같은 상황).
  다른 위치가 낫다면 옮길 것
- `cache/rate_limit.json` 과 `logs/runs.jsonl` 은 **지우지 않았다.** DATABASE_URL 을 비우면
  코드가 그 파일로 돌아가고, 이번 복구도 그 파일 덕에 가능했다
- 다중 워커로 실제 기동해 보지는 않았다 — 프로세스 5개로 카운터를 직접 두드려 같은 조건을
  만들었다. 상한이 걸린 엔드포인트가 전부 과금 경로(GitHub + LLM)라 HTTP 로는 무과금 검증이 안 된다

## 과제 A: 행 번호 정확도 - 2026-08-19 착수

답변이 짚는 행이 절반만 맞는다(30건 중 15건). 사용자가 그 줄을 열어 보면 다른 코드가 있다.

### 진단 — 두 경로의 원인이 다르다 (무과금)
저장된 답변 32건에서 (주장 행, 실제 행) 쌍을 모아 오프셋 분포를 봤다.

| 경로 | 정확도 | 틀린 것의 오프셋 | 해석 |
|---|---:|---|---|
| RAG | 62% | **+3 · +4 · +22** (전부 양수, 작다) | 줄 번호가 없어 모델이 **직접 센다** → 체계적 오차 |
| 전체 주입 | 45% | **-110 ~ +112** (양방향, 크다) | 8만 자에서 **위치 추적 실패**(같은 이름의 다른 위치) |

- **`format_snippets` 는 각 줄에 번호를 붙이지 않는다.** 헤더에 `(42-58행)` 범위만 적고
  본문은 원본 그대로다. 그런데 `CHAT_SYSTEM_PROMPT` 는 **두 형태 모두** "줄 번호(`12|코드`)가
  붙어 있다"고 말한다 — **RAG 경로에서는 사실이 아니다.** 모델은 없는 번호를 참조하려 한다
- **단일 행을 콕 집을 때 더 자주 틀린다** — 틀린 인용의 주장 범위 폭 중앙값 0행,
  맞은 것 2행. 범위로 말하면 맞을 확률이 높다

### A1 — 붙였다가 되돌렸다. **전제가 틀렸다**
스니펫에 `12|코드` 를 붙이려면 청크 content 가 원본의 `start_line~end_line` 과 1:1 이어야
하는데, 대조해 보니 **그렇지 않았다.**

| 청크 상태 | 비율 |
|---|---:|
| **줄 수 불일치 (번호가 밀린다)** | **48.8%** |
| 첫 줄 들여쓰기만 잘림 (번호는 맞다) | 29.2% |
| 완전 일치 | 21.4% |

`_merge_small` 이 떨어진 조각 둘을 이어붙이면서 **사이 줄이 빠진다** (10줄 범위인데
content 는 11줄). 그 상태로 번호를 매기면 절반이 틀린 번호가 되고, **모델이 세는 것보다
나빠진다** — 세면 조금 어긋나지만, 틀린 번호는 그대로 믿기 때문이다.
- [x] `format_snippets` 원복 (헤더 범위만). 되돌린 이유를 함수 docstring 에 남겼다
- [x] `context_builder.number_lines()` 는 **남긴다** — 번들이 쓰는 공통 헬퍼이고,
      나중에 청크를 고치면 그대로 재사용한다

### A2 — 프롬프트를 사실에 맞게 고쳤다 (되돌리지 않음)
원래 프롬프트는 **두 형태 모두** "줄 번호(`12|코드`)가 붙어 있다"고 말했다. RAG 경로에서는
거짓이었고, 모델이 없는 번호를 참조하려던 것이 오차의 원인으로 보인다.
- [x] 형태별로 정확히 설명 — 번들은 줄 번호가 붙고, 검색 조각은 **머리글에 범위만** 있다
- [x] "조각 안에서 특정 줄을 세어 짚지 마세요 — 조각은 원본과 줄이 정확히 맞지 않습니다"
- [x] 단일 행보다 **범위 인용** 유도 (틀린 인용의 범위 폭 중앙값 0행 · 맞은 것 2행)
- [x] "확실하지 않으면 행 번호 없이 이름으로. **틀린 행 번호는 없는 것보다 나쁩니다**"

### 남은 선택 — 청크를 "원본의 연속된 줄"로 재정의할 것인가
**A3 결과를 보고 보류를 권한다.**

그렇게 하면 A1 이 가능해지고 첫 줄 들여쓰기 손실도 사라진다. 대신 청크 경계가 바뀌어
`rule_version` 이 달라지고 전체 재색인 + 재평가가 따라오며, 검색 품질도 달라질 수 있다.

보류를 권하는 이유는 **RAG 에 남은 오류가 "세다가 어긋남"이 아니기 때문**이다.
A3 이후 남은 RAG 오답 4건을 보면 오프셋이 크다:

| 질의 | 주장 | 실제 |
|---|---|---|
| ap_ko_03 | 37~54행 | **120행** |
| ap_ko_04 | 37~52행 · 100~112행 | **67행** |
| ap_ko_05 | 115~130행 | **155행** |

이건 **한 조각의 범위를 다른 조각의 코드에 붙인 것**이다. 줄 번호를 붙인다고 반드시
풀리지는 않는다. 더 값싼 후보를 먼저 볼 것:
- 프롬프트에 "각 조각의 범위는 **그 조각 안의 코드에만** 적용됩니다"를 명시
- 스니펫 머리글을 더 뚜렷하게 구분(조각 사이 경계가 흐려 섞이는 것일 수 있다)

### A3 측정 — **50% → 75%** - 2026-08-20
답변을 새로 받아(`-m "evaluation and billed"`, 과금 **$0.394**) `test_line_accuracy` 로 재판정.

| 경로 | 이전 (옛 프롬프트·fp32) | 이후 (A2·int8) |
|---|---|---|
| RAG | 5/8 = 62% | 9/13 = **69%** |
| **전체 주입** | 10/22 = **45%** | 12/15 = **80%** |
| 합계 | 15/30 = **50%** | 21/28 = **75%** |

**틀린 인용이 15건 → 7건으로 줄었다** (전체 주입은 12건 → 3건).

- **전체 주입 수치가 프롬프트 효과의 순수한 증거다** — 그 경로는 인덱스를 쓰지 않으므로
  int8 전환과 무관하다. 45% → 80%
- RAG 는 두 변수(프롬프트·인덱스)가 섞여 있어 62% → 69% 를 프롬프트 덕으로만 볼 수 없다
- **분모가 줄어든 것(30 → 28)도 함께 봐야 한다.** "확실하지 않으면 행 번호 없이"를 넣었으니
  위험한 인용을 덜 하게 된 효과가 섞인다. 다만 **정확한 건수 자체가 15 → 21 로 늘었으므로**
  "덜 말해서 정확해진 것"만은 아니다

인용 정확도(파일을 짚었는가)도 함께 올랐다: RAG 0.75 → **0.8125**, 전체 주입 1.00 → 1.00.

- [x] A3 완료. **A1(스니펫 줄 번호)이 무산됐는데도 프롬프트만으로 목표를 상당 부분 달성했다**

## 과제 B: 인덱싱 시간 단축 - 2026-08-19 착수

소형 모델은 품질에서 기각됐다. 다음 축은 **같은 모델의 양자화**다.

### 후보 확인 (무과금)
`intfloat/multilingual-e5-large` 저장소에 `onnx/model_qint8_avx512_vnni.onnx` 가 있다.

| 항목 | fp32 | int8 |
|---|---:|---:|
| ONNX 크기 | 2,132MB | **536MB** (1/4) |
| 차원 | 1024 | 1024 (같다 → 접두어·테이블 규약 그대로) |
| fp32 벡터와의 코사인 | — | **0.993 ~ 0.995** |
| 질의↔정답 격차 | +0.1100 | +0.0970 |

- `add_custom_model(model_file="onnx/model_qint8_avx512_vnni.onnx")` 로 등록된다
- **모델 이름을 다르게 준다**(`...-large-int8`) → `rule_version()` 이 달라져 재색인 대상으로 뜬다.
  이름이 같으면 파일만 바뀌어도 규칙 해시가 그대로라 옛 인덱스와 조용히 섞인다
- 곁가지로 알게 된 것: **fastembed 내장 e5-large 는 정규화를 하지 않는다**(노름 29.4).
  검색이 코사인 거리라 순위에는 영향이 없어 지금까지의 측정은 유효하다

### 단계
- [x] B1. `EMBEDDING_SOURCE_REPO` / `EMBEDDING_MODEL_FILE` 설정
  - `EMBEDDING_MODEL` 은 **우리가 붙이는 이름**, 이 둘이 가중치 출처를 정한다.
    이름을 나눈 이유는 같은 저장소의 다른 파일을 쓸 때 이름까지 같으면 `rule_version()` 이
    그대로라 **옛 인덱스와 조용히 섞이기** 때문이다
  - `code_chunks_1024_int8` 테이블 — **차원이 같아도 모델이 다르면 나눈다.**
    벡터가 fp32 와 0.993~0.995 로 비슷하지만 같지 않아, 섞이면 오류 없이 거리만 틀어진다
- [x] B2. 속도 (인터리브 3라운드, **카나리 1.2% 통과**)

| 모델 | 중앙값 | ms/청크 | 라운드 편차 |
|---|---:|---:|---:|
| e5-large fp32 | 81.9s | 409.3 | 3.2% |
| **e5-large int8** | **32.5s** | **162.3** | 3.7% |

**2.52배 빠르다.** 카나리가 통과한 회차라 이 수치는 앞선 측정들보다 신뢰도가 높다.

- [x] B3. 품질 — 평가셋 v2, 저장소 3개 전부

| 저장소 | 한국어 R@8 fp32 → int8 | 식별자 R@8 | 전체 R@8 |
|---|---|---|---|
| air | 0.67 → **0.75** | 1.00 → 1.00 | 0.76 → 0.82 |
| marryday | 0.80 → **0.80** | 0.83 → 0.83 | 0.81 → 0.81 |
| apns4j | 0.50 → **0.60** | 1.00 → 1.00 | 0.69 → 0.75 |

- [x] B4. **판정: 채택.** 기준(저장소별 한국어 R@8 동률 이상)을 세 저장소 모두 충족

**"올랐다"보다 "떨어지지 않았다"로 읽는 것이 정직하다.** 개별 순위는 요동쳤고
(ko_10 15→3, ko_03 30→39) 질의 38개 표본에서 경계에 있던 것이 우연히 유리하게 뒤집혔을
수 있다. 양자화가 검색을 **좋게** 만들 이유는 없다. 실질 이득은 **속도 2.52배와 크기 1/4**이고,
품질이 그 대가로 깎이지 않았다는 것이 이 측정의 결론이다.

### 서비스 전환 - 2026-08-19
- [x] `.env` 전환 (`.env.bak-before-int8` 로 백업). 규칙이 `8e9937c1` → **`822bb217`** 로
      바뀌었다 — 모델 이름을 다르게 준 설계가 의도대로 동작해 재색인 대상으로 잡혔다
- [x] 서비스 스냅샷 재색인 — **air 236청크 40초 · marryday 4,365청크 635초(10.6분)**
      (fp32 기록은 39~96분). apns4j 는 전체 주입이라 0청크 1초
- [x] **롤백 경로 유지** — fp32 인덱스 15,967행이 `code_chunks_1024` 에 그대로 있다.
      `.env` 의 다섯 줄만 되돌리면 즉시 옛 인덱스로 돌아간다
- [x] 검색 실동작 확인(무과금): 비밀번호→`SecurityConfig.java` 35-42행,
      TextWebSocketHandler→`ChatHandler.java`, 체형 분석→`body_analysis.py` 332-354행

### 화면 확인 - 2026-08-20
`/admin/snapshots` 에서 **규칙 `822bb217` · 테이블 `code_chunks_1024_int8` · 재색인 필요 0**.
옛 테이블(`code_chunks`, `code_chunks_1024`)은 '(미사용)' 회색으로 남아 롤백 경로가 보인다.

**화면에서 버그를 하나 잡았다 — 모든 int8 색인이 "청크 0개"로 보였다.**
`index_status.list_all()` 의 CTE 에 테이블 이름 **둘만 박혀 있었다**(`code_chunks`,
`code_chunks_1024`). 함수 주석에 "차원을 또 늘리면 여기도 함께 고쳐야 한다"고 적혀 있었는데,
테이블 셋을 추가하면서 이 곳을 놓쳤다. 청크가 실제로는 9,370행 있고 검색도 정상이었으므로
**오류 없이 화면만 거짓말을 했다** — 색인 없음·전체 주입·깨진 색인이 전부 같은 모양이 된다.
- [x] `index_status.CHUNK_TABLES` 상수 + `psycopg.sql` 로 SQL 조립 → 목록 한 곳만 고치면 된다
- [x] **`schema.sql` 과 대조하는 테스트**로 고정 — 손으로 맞추는 목록은 또 어긋난다
- [x] 수정 후 확인: 236 / 4,365 / 168청크가 제대로 나오고, 전체 주입 스냅샷(#23)은
      `full_injection=True` 로 구분된다

**사용자 대화 화면은 따로 띄우지 않았다** — A3 측정이 같은 int8 인덱스로 RAG 경로 16질의를
실제 호출해 답변까지 받았으므로, 대화 경로는 그것으로 검증됐다.

## `플로우.md` 갱신 — 문서가 코드보다 두 세대 뒤였다 - 2026-08-20

문서가 **"첫 질문에서 동기 인덱싱, 약 75초"** 로 남아 있었다. 실제로는 그 뒤에
백그라운드 색인·큐·전체 주입·int8 이 차례로 들어갔는데 문서는 한 번도 따라오지 않았다.

- [x] 코드 대조 후 재작성 — verify: `analyze.py:45` / `chat.py:84-98` / `indexer.py` /
      `index_queue.py` / `Chat.tsx` / `App.tsx` / `schema.sql` / `.env` 를 직접 읽고 맞춤
- 고친 것: ① 색인 시점(첫 질문 → `/analyze` 응답 직전, 캐시 히트에도) ② 큐 워커 절 신설
  ③ `/chat` 의 세 갈래(전체 주입 / 색인 완료 / 미완) ④ 프롬프트에서 `source_bundle` 은
  캐시 지점, `snippets` 는 마지막 메시지 ⑤ 프론트의 `GET /chat/{id}/index` 폴링 배너
  ⑥ `runs`·남용 제한이 DB(파일 폴백) ⑦ 청크 테이블은 `CHUNK_TABLE` 설정값
- 시간 수치는 fp32 시절 "약 75초" 대신 int8 실측(236청크 40초 · 4,365청크 10.6분 ·
  전체 주입 1초)으로 교체. **저장소 이름 대신 성격으로 적었다**(CLAUDE.md §7)
- 배운 것: 이 문서는 "동작이 바뀔 때" 갱신하기로 돼 있는데, 바뀐 쪽(색인 시점)이
  **다른 과제의 부수 효과**라 아무도 문서를 떠올리지 않았다. 큰 흐름을 건드리는 과제는
  체크리스트에 `플로우.md` 한 줄을 넣을 것

## 배치 크기 재측정 — 1 로 내렸다가 **되돌렸다** - 2026-08-20

**결론부터: `EMBED_BATCH_SIZE` 는 32 그대로다.** 마이크로벤치는 1 이 2.2배 빠르다고 했는데
실제 재색인이 4배 느려졌고, 원인을 좇아 보니 **최적 배치가 가용 코어 수에 따라 뒤집힌다.**
아래는 그 경위 전체다.


`EMBED_BATCH_SIZE = 32` 는 **fp32 시절, 평균 982자 표본**에서 정한 값이다. int8 로 바꾼 뒤
다시 재지 않았고, 지금 청킹 규칙에서는 그런 길이의 청크가 나오지도 않는다
(세 평가 저장소 모두 청크 평균 362~513자).

- [x] `tests/test_embed_batch_size.py` 신설 — 모델 하나를 **배치 크기별로** 잰다
      (`test_embed_speed.py` 는 모델 둘을 고정 배치로 재는 반대 도구)
  - 표본을 **일정 간격으로 훑어** 뽑는다. 앞 200개만 쓰면 저장소 분포가 아니라 첫 몇 파일의
    분포를 잰다 — 한 저장소는 앞 200개 평균 401자인데 전체 중앙값이 744자였다
  - 현재 값을 후보에 자동으로 끼워 넣는다(`_candidates()`) — 구간을 옮겨도 지금 값과의
    차이를 그 회차 안에서 읽을 수 있어야 한다
- [x] 측정 — verify: 라운드 편차 ≤15% · 카나리 ≤10% (사전 고정)

**깨끗한 회차** (편차 ≤4.2%, 카나리 3.1%, 표본 495자):

| 배치 | 4 | 8 | 16 | 32(당시 값) | 64 | 128 |
|---|---:|---:|---:|---:|---:|---:|
| ms/청크 | **108.2** | 124.9 | 142.1 | 161.6 | 187.3 | 202.2 |

**단조 감소다 — 배치가 클수록 계속 느려진다.** fp32 측정(8:2461 · 16:1616 · **32:1032** ·
64:1173)과 방향이 정반대다. CPU 점유가 모든 후보에서 7.4~7.8x 로 같으므로,
onnxruntime 이 배치 1개짜리 입력에도 이미 8코어를 다 쓰고 있어 **배치로 얻을 병렬성이 없고
패딩 낭비만 남는** 상태로 읽힌다.

아래로 더 열었더니 **배치 1 이 가장 빨랐다** — 모든 라운드에서 `1 < 2 < 4 < 8 < 16 < 32`.
다만 그 두 회차는 폐기 기준에 걸렸다(아래).

- [x] **확정 측정 — 기기를 10분 쉬게 한 뒤 1회** (직전 CPU 부하 4%)

| 배치 | 1 | 2 | 4 | 32(옛 값) |
|---|---:|---:|---:|---:|
| ms/청크 | **73.0** | 87.4 | 105.8 | 160.6 |
| 라운드 편차 | 2.9% | 4.2% | 5.0% | 6.2% |

네 후보 모두 통과했고 절대 시간도 전 회차 통틀어 가장 빠르다(식은 효과).
1↔2 차이도 19.7% 로 노이즈보다 훨씬 크다. → **`EMBED_BATCH_SIZE = 1`, 32 대비 54.6%.**

- [x] **진행률 보고를 배치에서 떼어냈다** — `PROGRESS_EVERY = 32` 신설.
      보고 한 번이 DB 쓰기 한 번이라(`indexer._report` → `index_status.advance`)
      묶어 두면 배치를 줄이는 순간 쓰기가 같은 비율로 는다(136회 → 4,365회가 될 뻔했다).
      **주기는 전과 같은 32 라 DB 부하는 그대로다**
- [x] 회귀 방지 테스트 — `test_progress_cadence_is_not_tied_to_batch_size`.
      오류 없이 부하만 느는 종류라 주석으로는 못 막는다(반복 실패 방식 4번)
- [x] 검증: **196 passed / 88 skipped**. 신규 1건. LLM 실호출 없음
  - skip 88건은 Docker 가 안 떠 있어 DB 테스트가 통째로 빠진 것이다.
    이번 변경은 DB 쓰기 **주기를 그대로 두는** 것이 요지라 그 경로의 동작은 바뀌지 않는다

**카나리가 오탐을 냈다(14.4%).** 카나리를 배치 1 로 재게 바꾸면서 20청크가 1.7초에 끝나
0.2초 노이즈가 14% 로 잡혔다 — `test_embed_speed.py` 가 겪고 주석에 남겨 둔 함정을
그대로 밟았다. 본 측정 편차(2.9~6.2%)가 판단 근거이고, 우리 기준도 카나리 초과는
"배율만 읽을 것"이지 폐기가 아니다. → `CANARY_CHUNKS` 20 → **60**.

### 실제 재색인이 뒤집었다 — 4배 느려졌다

스냅샷 17(4,365청크)을 관리자 경로 그대로(`index_queue.submit` → 워커 → `run_build`) 재색인:

| | 배치 32 (08-19 기록) | 배치 1 (08-20) |
|---|---:|---:|
| 전체 | 635초 (10.6분) | **2,557초 (42.6분)** |
| 청크당 | 145ms | 579ms |

- [x] **즉시 32 로 되돌렸다.** 실제 경로에서 나온 유일한 증거가 4배 악화를 가리켰다

**마이크로벤치와 대조하니 비대칭이 보였다** — 배치 32 는 벤치(160ms)와 실측(145ms)이
거의 맞는데 배치 1 만 벤치(73ms)와 실측(579ms)이 8배 어긋났다. 기기 노이즈라면
양쪽이 같이 어긋나야 한다.

### 진짜 원인: **최적 배치가 가용 코어 수에 따라 뒤집힌다**

같은 표본·같은 하네스를 기기가 지친 상태에서 다시 돌렸더니 **순서가 뒤집혔다.**

| 회차 | CPU 점유 | 배치 1 | 배치 32 | 승자 |
|---|---:|---:|---:|---|
| 식은 기기 | **7.8x** | 73.0ms | 160.6ms | **1** (2.2배) |
| 지친 기기 | **3.4x** | 643.6ms | 525.3ms | **32** (1.2배) |

코어가 적으면 **호출당 고정 비용이 상대적으로 커져** 배치가 그것을 분산시키는 쪽이 이긴다.
코어가 많으면 그 비용이 묻히고 패딩 낭비만 남아 배치 1 이 이긴다.

그리고 이것이 42.6분을 설명한다 — 실측 579ms/청크는 지친 상태 벤치의 배치 1 값
**643.6ms 와 거의 같다.** 벤치마크는 틀리지 않았다. **조건이 달랐을 뿐이다.**

- 코어는 8개 그대로이고 다른 CPU 소비 프로세스도 없다(부하 8%). 2시간 가까이 임베딩을
  돌린 뒤 전력·발열 예산이 줄어 코어가 파킹된 것으로 보인다
  (P코어 4 + LP E코어 4 구성이라 예산이 줄면 느린 쪽으로 몰린다)

**~~그래서 32 를 유지한다. 40분짜리 색인 작업은 스스로 기기를 지친 상태로 만든다.~~**
**↑ 이 추론은 틀렸다 (아래 '되돌리기 확인' 에서 반증됨).**

- [x] 하네스가 스스로 경고하게 했다 — CPU 점유가 코어의 80% 미만이면
      "다른 회차와 배율을 견주지 말 것" 을 찍는다. 모든 걸 무효로 만든 변수인데
      표에 숫자로만 있었다
- [x] 하네스 머리말에 **"이 답을 그대로 믿고 상수를 바꾸지 말 것 — 실제 재색인으로 확인"**
### 되돌리기 확인 — 재현됐다. 그리고 위 추론이 반증됐다

기기를 30분 식힌 뒤 같은 스냅샷을 **배치 32** 로 재색인(빌드 #100):

```
전체 591.6초 (9.9분) · 청크당 135.5ms
수집 14.5s · 임베딩 565.0s · 전체 589.1s   (임베딩이 96%)
CPU 점유: 처음 7.7x → 끝까지 7.7x (중앙값 7.7x / 코어 8개)
```

- [x] **08-19 기록 635초가 재현됐다(591.6초).** 되돌리기는 성공이다
- [x] **"색인이 스스로 기기를 지치게 한다"는 틀렸다** — 10분 내내 7.7x 를 유지했다.
      코어 파킹은 색인 부하 때문이 아니라 **그날 두 시간 가까이 벤치를 연달아 돌린**
      누적 때문이었다

**그래서 배치 1 문제는 아직 열려 있다.** 그 재색인(2,557초) 때는 **CPU 점유를 재지 않았다** —
지금 와서 그 회차가 7.8x 였는지 3.4x 였는지 알 방법이 없다. 두 가능성의 뜻이 정반대다:

| 그때 CPU 가 | 뜻 |
|---|---|
| ~3.4x 였다면 | 기기가 지쳐 있었던 것. **배치 1 은 아직 유효한 후보**이고, 7.8x 에서 다시 재야 한다 |
| ~7.8x 였다면 | 배치 1 이 **규모에서 무너진다**는 뜻(200청크에서 73ms, 4,365청크에서 579ms). 마이크로벤치가 구조적으로 못 잡는 것이 있다 |

### ~~답 — 배치 1 은 규모에서 무너진다~~ → **이 결론도 틀렸다 (아래 '세 번째 반전')**

식은 기기에서 배치 1 로 재색인(빌드 #101, 소스 상수는 32 그대로 두고 이 실행만 override):

```
전체 1,105.7초 (18.4분) · 임베딩 1,076초 = 246.5ms/청크
CPU 점유: 처음 3.8x → 중앙값 6.7x (코어 8개)   ← 기기는 정상이었다
```

| 배치 | 실제 재색인 | 임베딩 ms/청크 | CPU 점유 |
|---|---:|---:|---:|
| **32** | **591.6초 (9.9분)** | **129.4** | **7.7x** |
| 1 | 1,105.7초 (18.4분) | 246.5 | 6.7x |

- [x] **배치 32 확정.** 기기가 지치지 않은 상태에서도 배치 1 이 1.9배 느리다
- **원인은 CPU 점유에 있다** — 배치 1 은 6.7x 밖에 못 썼다. 청크 하나짜리 호출로는
  8코어를 다 먹이지 못하고, 호출 4,365번의 스레드 동기화 비용이 배치 32 의 패딩 낭비보다 크다
- 앞선 2,557초(배치 1, 지친 기기)는 **두 효과가 겹친 것**이었다 — 배치 1 자체가 1.9배 느리고,
  거기에 코어 파킹이 2.3배를 더했다

**마이크로벤치는 작은 배치를 체계적으로 과대평가한다:**

| 배치 | 하네스(200청크) | 실제(4,365청크) | 어긋남 |
|---|---:|---:|---:|
| 32 | 160.6ms | 129.4ms | 1.2배 (실제가 빠름) |
| 1 | 73.0ms | **246.5ms** | **3.4배 (실제가 느림)** |

- [x] 이 대조표를 하네스 머리말에 박아 넣었다 — 다음 사람이 같은 함정에 빠지지 않게

### 덤으로 밝혀진 것 — **배치를 바꾸면 벡터도 달라진다**

"패딩은 어텐션 마스크로 가려지니 배치를 바꿔도 벡터는 같다, 그러니 재색인이 필요 없다"고
두 번 적었는데 **틀렸다.** 빌드 #100(배치 32)과 #101(배치 1)의 같은 청크 4,365개를 짝지어 보니:

```
코사인  최소 0.977473  평균 0.993086
```

**int8 ↔ fp32 차이(0.993~0.995)와 같은 크기다.** 그때는 테이블을 나누고 R@8 을 다시 잰
차이다. 배치 모양에 따라 다른 커널이 선택되고 int8 양자화가 그 차이를 키우는 것으로 보인다.

- [x] 하네스 주석의 틀린 서술을 고쳤다 — **배치를 바꾸면 재색인 + 품질 재측정이 따라온다**
- [x] 활성 색인을 배치 32 로 다시 만들었다(빌드 #102). 실험 산물(배치 1 빌드)을 서비스가
      계속 보게 두면 **저장한 것과 읽는 것의 전제가 어긋난다**(반복 실패 방식 3번)

### 세 번째 반전 — 배치 효과가 아니라 **전부 CPU 효과였다**

그 재생성(#102, 배치 32)이 배치 1 과 거의 같은 시간이 나왔다.

| 빌드 | 배치 | CPU 점유 | 전체 | 임베딩 ms/청크 |
|---|---:|---:|---:|---:|
| #100 | 32 | **7.7x** | 591.6초 | **129.4** |
| #101 | 1 | 6.7x | 1,105.7초 | 246.5 |
| #102 | 32 | 6.6x | 1,071.0초 | 237.9 |

- **같은 배치 32 인데 CPU 7.7x → 6.6x 로 14% 떨어지자 시간이 1.84배가 됐다.**
  선형이 아니다 — CPU 점유는 **P코어를 쓰고 있는지**의 대리 지표이고, 예산이 줄어
  LP E코어로 몰리면 점유율은 조금 떨어지는데 처리량은 무너진다
- **같은 CPU 수준(6.6~6.7x)에서 배치 32 와 1 의 차이는 3.5% 뿐이다** — 노이즈 수준
- 따라서 "배치 1 이 1.9배 느리다"는 앞 절의 결론은 **6.7x 와 7.7x 를 비교한 것**이었다

**이 기기로는 이 질문에 답할 수 없다.** 재려는 효과(배치)보다 통제 못 하는 변수(CPU 상태)의
영향이 훨씬 크다 — 14% 의 CPU 차이가 84% 의 시간 차이를 만드는데, 배치 차이는 그보다 작다.
30분 냉각으로도 7.7x 가 재현되지 않았다(#102 는 냉각 없이 이어 돌렸다는 점은 감안할 것).

- [x] **`EMBED_BATCH_SIZE = 32` 유지.** 결론이 아니라 **기존 값을 지키는 판단**이다 —
      08-19 실측(635초)과 #100(591.6초)으로 검증된 값이고, 바꿀 근거가 확보되지 않았다
- [ ] 다시 시도한다면: CPU 친화도·전원 계획을 고정하거나, 애초에 **배포 기기**에서 잰다.
      노트북에서 배치 상수를 실측으로 정하는 것은 이번처럼 세 번 뒤집힌다

**이 과제에서 실제로 건진 것:**
1. 배치를 바꾸면 **벡터가 달라진다**(코사인 0.993) — 재색인·품질 재측정이 따라온다
2. `PROGRESS_EVERY` 분리 (보고 한 번 = DB 쓰기 한 번) + 회귀 테스트
3. 측정에 **조건(CPU 점유)을 함께 남기는** 습관. 이게 없었으면 세 번째 반전도 못 봤다
- **교훈: 실측에 조건을 함께 기록하지 않으면 그 측정은 나중에 못 쓴다.**
  시간만 남기고 CPU 점유를 안 남긴 탓에 42.6분짜리 측정 하나가 통째로 해석 불가가 됐다

### 남긴 것

- `PROGRESS_EVERY = 32` **분리는 유지한다.** 배치와 무관하게 맞는 변경이고
  (보고 한 번 = DB 쓰기 한 번), 회귀 테스트도 함께 남겼다
- 측정 스크립트가 `index_status.get()` 으로 진행을 폴링해 **5초 만에 끝났다고 오판**했다.
  그 함수는 **활성 빌드를 우선** 돌려주도록 설계돼 있다(재색인 중에도 화면에 '읽는 중'
  배너를 띄우지 않으려고) → 진행 조회는 **build_id 로** 해야 한다.
  그때 죽은 빌드 #98 은 `failed` 로 사유를 적어 정리했다(청크 삽입 전이라 활성 색인은 무사)

### 측정이 오염된 방식 두 가지

**1. 카나리를 둔감한 조건으로 쟀다.** 배치 32 로 재던 회차에서 기기가 느려졌는데 카나리는
4.7% 만 움직여 통과했다. 그 느려짐이 호출 오버헤드 쪽이라 **작은 배치를 훨씬 세게 때렸기**
때문이다(배치 1 이 13% 느려질 때 배치 32 는 3.8%). → 카나리를 **가장 작은 후보**로 재게 고쳤다.
다음 회차에서 22.5% 로 제대로 잡아냈다.

**2. 벤치마크를 연달아 돌렸다.** 7분짜리를 네 번 이어 돌리자 회차 전체가 느려졌다
(모바일 CPU, 8스레드 지속 부하). 절대 시간이 회차 간에 비교되지 않는다.
→ **연속 측정 사이에 기기를 쉬게 할 것.** 배율은 인터리브가 지키지만 절대값은 못 지킨다.

### 사고: 한글 파일을 PowerShell 로 치환해 깨뜨렸다

상수 한 줄 바꾸려고 `Get-Content -Raw | ... | Set-Content -Encoding utf8` 를 썼더니
**한글이 전부 깨지고 줄 구조까지 뭉개져** pytest 수집이 실패했다(exit 2). git 저장소가 아니라
되돌릴 수 없어 파일을 다시 썼다. → `TROUBLESHOOTING.md` 에 한 줄. **한글이 든 파일은
PowerShell 로 치환하지 말 것.**

## 증분 색인 — **보류** (설계는 확정, 착수 조건 미충족) - 2026-08-20 등재 · 2026-08-21 판정

**재색인에서 안 바뀐 파일의 벡터를 재사용한다.** 지금은 `pushed_at` 이 바뀌어 새 스냅샷이
생기면 4,365청크를 **전부 다시 임베딩한다** — 커밋 하나만 바뀌어도 그렇다.

- **왜 안전한가**: 청킹이 파일 단위로 독립적이다(`chunk_files` 가 `chunk_file(path, content)`
  를 파일마다 따로 부르고, `_merge_small` 병합도 파일 안에서만 일어난다). 파일 내용이 같으면
  그 파일이 만드는 청크도 벡터도 같다. 옆 파일이 바뀌어도 영향받지 않는다
- **효과 범위**: 첫 색인은 **0% 개선**(재사용할 이전 벡터가 없다). 재색인만 줄어든다.
  청킹 규칙(`rule_version`)이나 모델이 바뀌면 전부 무효라 그때도 0%
- **품질 영향 없음** — 같은 코드에 같은 벡터를 재사용할 뿐이다. 측정 조건에 휘둘리지도
  않는다(계산을 안 하는 것이라 배치 크기 같은 축과 성격이 다르다)

**전제**: 색인은 백그라운드라 사용자를 막지 않는다. 이 과제의 이득은 대기 시간이 아니라
**CPU 시간과 전력**이고, 사용자에게 보이는 것은 "요약만으로 답하는 창"이 짧아지는 것뿐이다.

### 착수 전 세 질문 — 답 - 2026-08-21

- [x] **값어치가 있는가 — 절감 폭은 크지만 발생 빈도가 0이다.**

  DB 를 열어 보니 **저장소 갱신으로 생긴 스냅샷이 하나도 없었다.** 스냅샷 6개는
  `key_source` 가 `pushed_at` 3개 · `eval` 3개로, 저장소마다 **실제 스냅샷 하나 +
  평가용 픽스처 하나**(`version='fixed'`)씩이다.
  `/analyze` 재호출 13건(marryday 7 · air 4 · apns4j 2)은 전부 같은 `pushed_at` 이라
  **캐시 히트로 끝났다 — 재색인 자체가 일어나지 않았다.**

  정작 반복된 것은 스냅샷이 아니라 **같은 스냅샷의 재빌드 19건**이었고, 사유는 전부
  모델 교체(1024 → 1024_int8)와 청킹 규칙 변경이다. **그 조건에서 증분은 정의상 0%** 다
  (위 '효과 범위' 참고). 즉 **관측된 재색인 중 증분이 도왔을 건수는 0이다.**

  반대로 **재색인이 일어나기만 하면 절감 폭은 크다.** GitHub 에서 변경 파일 비율을 실측
  (무과금, 요청 24회):

  | 저장소 | 소스 | 1일 | 7일 | 30일 |
  |---|---:|---:|---:|---:|
  | fastapi | 1,197 | 99.8% | 99.6% | 97.4% |
  | flask | 116 | 99.1% | 92.2% | 69.8% |
  | requests | 51 | 98.0% | 98.0% | 86.3% |
  | apns4j (정지된 저장소) | 32 | 100% | 100% | 100% |
  | marryday | 181 | 45.9% | 45.9% | — |

  (재사용 가능 비율 = `1 −` 변경 소스 비율. marryday 는 커밋 **하나가 98파일**을 바꾼
  대량 커밋이 걸린 경우로, 학생 프로젝트에서 흔한 모양이다)

  → **지금은 값어치가 없다.** 착수 조건은 명확하다: **다른 `pushed_at` 으로 같은 저장소가
  다시 색인되는 일이 실제로 생길 때.** 그 전까지는 구현해도 한 번도 실행되지 않는 경로다.

- [x] **재사용 키 — `(chunk_rule, path, 파일 내용 해시)`. 청크는 새 빌드로 복사한다.**

  가리키는 방식은 **지금 구조의 불변식을 깬다.** 검색이 `WHERE build_id = %s` 로 한 빌드
  안에서만 찾고(재색인 중 절반짜리 청크가 섞이지 않게 한 장치), `prune_builds` 는 옛 빌드를
  지우면 청크가 `ON DELETE CASCADE` 로 함께 사라지는 것을 전제한다. 가리키게 하면 검색이
  여러 빌드를 봐야 하고, prune 이 "참조 중인 옛 빌드"를 알아야 하며, 포인터 롤백의 의미도
  흐려진다. **복사면 셋 다 그대로다.**

  복사는 파이썬을 거치지 않는다 — `INSERT INTO … SELECT %s, path, …, embedding FROM …
  WHERE build_id = %s AND path = ANY(%s)` 로 **DB 안에서 벡터가 옮겨간다.**
  비용은 디스크뿐이고(1024차원 float4 = 청크당 약 4KB, 4,365청크 ≈ 17MB/빌드),
  `KEEP_BUILDS` 만큼만 쌓인다.

  **키에 `chunk_rule` 이 들어가야 한다** — 청크는 파일 내용뿐 아니라 청킹 규칙의 함수다.
  그리고 **파일 해시를 담을 곳이 지금 없다.** 청크 content 를 이어붙여도 원본 파일이 되지
  않는다(`_merge_small` 이 사이 줄을 빼서 **48.8%가 줄 수부터 어긋난다** — 과제 A 기록).
  → 새 테이블 `build_files(build_id, path, file_hash)` 가 필요하다. 청크 열에 붙이지 않는
  이유는 **청크 0개인 파일**(빈 파일·파싱 실패)도 "처리했고 청크가 없다"로 남아야
  재사용 판정이 정확하기 때문이다. 청크에만 두면 그 사실이 사라져 매번 다시 처리한다.

- [x] **부분 실패 — 새로 만들 것이 없다. 지금 구조가 이미 막고 있다.**

  복사분과 신규 임베딩분이 다 들어간 뒤에 `complete()` 를 부르기만 하면 된다.
  중간에 죽으면 새 빌드는 미완성으로 남지만 **포인터가 안 옮겨갔으므로 아무도 안 본다**
  (지금 재색인 실패와 완전히 같은 상태이고, `prune_builds` 가 나중에 치운다).

  진짜로 새로 생기는 위험은 하나다: **복사 원본이 다른 스냅샷의 빌드**라는 것.
  `_prune` 은 같은 스냅샷의 빌드만 지우므로 지금까지는 문제가 없었지만, 증분은 남의
  스냅샷 빌드를 읽는다 → 복사 도중 그 빌드가 사라질 수 있다. `INSERT … SELECT` 한 문장이면
  원자적이라 안전하고, 원본이 없으면 0행이 복사되어 **그 파일이 신규 임베딩 대상으로
  자연히 내려간다**(느려질 뿐 결과는 같다).

### 판정 — 보류 (사용자 결정) - 2026-08-21

**착수 조건: 다른 `pushed_at` 으로 같은 저장소가 다시 색인되는 일이 실제로 생길 것.**
그 전까지는 만들어도 한 번도 타지 않는 경로다. 조건이 충족됐는지는 이 쿼리로 본다 —
같은 `repo_id` 에 `key_source='pushed_at'` 스냅샷이 둘 이상이면 그때다:

```sql
SELECT repo_id, count(*) FROM repo_snapshots
 WHERE key_source = 'pushed_at' GROUP BY repo_id HAVING count(*) > 1;
```

착수하게 되면 위 세 답이 그대로 설계다. 새로 정할 것은 없다.

**하마터면 근거로 쓸 뻔했다.** 등재 당시 "저장소 3개에 스냅샷이 2개씩 쌓여 있다"를
재분석의 약한 근거로 적어 뒀는데, 열어 보니 **저장소마다 실제 스냅샷 하나 + 평가용
픽스처 하나**였다(`key_source='eval'`). 개수만 세면 재분석처럼 보이고 `key_source` 를
봐야 갈린다. 값어치를 재는 자리에서는 **행 수가 아니라 그 행이 어떻게 생겼는지**를 본다.

## Stage 5: 정적분석 결합 - 2026-08-20 착수

### 원안을 바꿨다 — ESLint/Pylint 는 **임의 코드 실행**이다

이 서비스는 임의의 GitHub 저장소를 받는다. 그런데 ESLint 는 `eslint.config.js` 를 **읽어
실행**하고(설정 파일 자체가 JS 다), 의미 있는 결과를 내려면 `npm install`(= `postinstall`
스크립트 실행)이 필요하다. Pylint 도 `astroid` 가 추론 과정에서 모듈을 import 한다.
**남의 코드를 우리 서버에서 실행하는 경로**라 격리 컨테이너 없이는 쓸 수 없다.

→ **설정·의존성 없이 AST 만 보는 린터**로 바꾼다. 1단계는 `ruff`(Rust 단일 바이너리).
사용자 승인 완료. JS/TS 는 같은 성격의 도구(oxlint 등)를 검증해 2단계에서 붙인다.

### 정해 둔 것 (승인됨)

| 결정 | 값 | 근거 |
|---|---|---|
| 도구 | `ruff --isolated --no-cache` | 저장소 설정을 안 읽고 import 도 안 한다 |
| 규칙 | **`E9,F` 로 고정** | 아래 |
| 넣을 것 | **집계만** (건수·상위 규칙·밀집 파일) | 스냅샷마다 고정 → 캐시 접두사에 들어간다 |
| 넣을 곳 | `build_context()` → 요약·대화가 함께 쓰는 `context` | |
| 실행 시점 | **`/analyze`** (tarball 을 여기서 받는다) | 요약이 "이 코드베이스의 상태"를 말하려면 요약 전에 있어야 한다 |

**규칙을 명시적으로 고정하는 이유**: 기본값에 맡기면 ruff 버전이 오를 때 요약 내용이
조용히 바뀐다(fastembed pooling 과 같은 함정). 실측 비교(Python 86파일 저장소):

| 세트 | 건수 | 판단 |
|---|---:|---|
| 기본(미지정) | 1,125 | 스타일 잡음 위주(`UP006`·`RUF010`) — 결함이 아니다 |
| **`E9,F`** | **232** | 전부 정합성. `F821` 정의되지 않은 이름 4건이 특히 값지다 |
| `+B` | 331 | **`B008` 90건이 FastAPI 오탐** — `Depends()`/`File()` 기본값은 그 프레임워크의 정석 |
| `+BLE` | 576 | 맨손 `except` 245건. 신호이긴 하나 의도적으로 그리 쓰는 코드도 많다 |

`B` 를 넣으면 오탐 90건을 "결함"이라고 요약에 적게 된다 — **조용히 틀리는** 쪽이다.

### 알면서 받아들이는 비용

- **tarball 을 두 번 받는다** (`/analyze` 1회 + 색인 1회). 아카이브 다운로드는 core 와
  **별개 제한**이라 429 가 날 수 있다(TROUBLESHOOTING 참고). 새 스냅샷당 2회로 한정되고
  캐시 히트에는 0회다. 줄이려면 `/analyze` 가 받은 파일을 큐에 넘겨야 하는데
  큐 계약과 메모리가 함께 커져서 **1단계에서는 하지 않는다**
- `/analyze` 대기 +1~15초 (tarball). ruff 자체는 0.03~0.4초로 무시할 수준
- **Python 저장소에만 결과가 나온다.** 평가 저장소 3개 중 1개뿐이다 — 2단계 전까지는 반쪽

### 단계

- [x] 1. `app/services/static_analysis.py` — `analyze(files) -> list[dict]` (테스트 10건)
  - **`shutil.which("ruff")` 가 None 을 돌려줬다.** `pip install` 은 venv 의 Scripts 에 넣는데
    `.venv/Scripts/python.exe -m uvicorn` 처럼 인터프리터를 직접 부르면 그 디렉터리가
    PATH 에 없다 → `find_tool()` 이 **인터프리터 옆을 먼저** 본다
  - **"재지 않았다"와 "재 봤더니 0건"을 구분한다.** 파이썬이 없는 저장소는 빈 목록이고,
    깨끗한 저장소는 `total: 0` 이다. 섞으면 화면이 근거 없는 말을 하게 된다
- [x] 2. `build_context(ctx, analysis)` + `build_analysis_section()` (테스트 3건)
  - 실측 **270토큰**(경고 232건짜리 저장소). 잰 것이 없으면 섹션이 통째로 빠진다
  - 블록에 **검사한 언어와 규칙을 적는다** — 안 적으면 모델이 검사 범위 밖까지 단정한다
- [x] 3. `/analyze` 결합 (테스트 3건: 프롬프트 도달 · 실패해도 요약 정상 · 히트는 tarball 0회)
- [x] 4. `requirements.txt` 에 `ruff>=0.16` — 없어도 서비스는 돈다(섹션만 빠진다)
- [x] 5. 검증: **293 passed / 7 skipped** (신규 16건). LLM 실호출 없음
- [x] `플로우.md` 갱신 (1단계 6.5, 비용표 4~6회→5~7회·10~40초→11~55초, 실패표, 저장 위치)

**사고: 테스트가 실제로 GitHub 을 때리고 있었다.** `/analyze` 가 tarball 을 받게 되면서
`test_analyze_api.py` 의 캐시 미스 테스트들이 진짜 요청을 보냈다 — 전체 실행이
**14초 → 25초**로 늘어 알아챘다. `fetch_source_files` 를 fixture 에서 막아 14초로 복귀.
**엔드포인트에 외부 호출을 추가하면 그 엔드포인트의 테스트 격리도 함께 바뀐다**
(저장소를 DB 로 옮겼을 때 격리가 깨진 것과 같은 종류다).

### 실동작 (무과금, 캐시된 평가 소스)

```
## 정적분석
- ruff(python, 규칙 E9,F): 86개 파일 검사 · 경고 232건
  - F401 86건 — imported but unused
  - F541 77건 — f-string without any placeholders
  - F841 63건 — Local variable `start_key` is assigned to but never used
  - F821 4건 — Undefined name `np`          ← 실제 버그 신호
  - F811 2건 — Redefinition of unused `asyncio`
  - 경고가 몰린 파일: services/tryon_service.py 30건 · core/gemini_client.py 15건 ...
- 검사하지 않은 언어의 코드에 대해서는 아무것도 알 수 없습니다.
```

나머지 두 저장소(Java·JS)는 섹션이 통째로 빠진다 — **3개 중 1개만 결과가 나온다.**

### 2단계: JS/TS — `oxlint` 추가 - 2026-08-21

**먼저 언어 분포를 쟀다.** 평가 저장소 260파일: python 86 · **java 72** · javascript 41 ·
css 39 · html 21. JS 41개는 전부 marryday(이미 ruff 로 섹션이 나온다)이고,
**java 72개가 air·apns4j 에 있어 그 둘이 비어 있다** — 우리 평가셋만 보면 Java 가 먼저다.

그럼에도 **JS/TS 를 먼저 한다.** 평가셋 3개가 Java 에 치우쳤을 뿐이고 실제 GitHub 분포는
JS/TS 가 훨씬 많다. 평가셋에 맞춰 설계하지 말라는 것이 CLAUDE.md §7 의 취지다.

- [x] **보안 검증 — oxlint 가 저장소 설정을 실행하는가** (`.oxlintrc.js`·`.oxlintrc.cjs`·
      `oxlint.config.js` 를 심고 부작용으로 파일 생성을 관찰) → **셋 다 실행 안 됨.**
      자동으로 읽는 것은 `.oxlintrc.json` 뿐이고 그건 JSON 이라 코드가 아니다
- [x] **그런데 그 JSON 하나로 검사를 통째로 끌 수 있다** — 실측 **122건 → 0건**.
      코드 실행은 아니지만 **검사 대상이 검사 결과를 조종**하면 리뷰가 성립하지 않는다.
      두 겹으로 막았다: `_write_sources` 가 설정 파일을 아예 안 쓰고, `--config` 로 우리 규칙을 못박는다
      (`--config` 만으로도 122건이 복구되는 것을 확인)
- [x] 규칙은 `correctness` 로 고정 — ruff 의 `E9,F` 와 같은 성격
- [x] `Back/package.json` + `oxlint` 고정 버전 (사용자 승인). `.gitignore` 에 `node_modules/`
  - 설치 절차가 하나 늘었다: `pip install -r requirements.txt && npm install`
  - `find_tool()` 이 **인터프리터 옆 → `node_modules/.bin` → PATH** 순으로 찾는다.
    둘 다 PATH 에 없는 곳이라 `shutil.which()` 만으로는 못 찾는다
- [x] 테스트 14건 (JS 분석 · 혼합 저장소 · **저장소가 린터를 침묵시키지 못함** · 설정파일 판별)
- [x] 검증: **297 passed / 7 skipped**

실측 (marryday 181파일):

```
- ruff(python, 규칙 E9,F): 86개 파일 검사 · 경고 232건
- oxlint(javascript/typescript, 규칙 correctness): 41개 파일 검사 · 경고 122건
  - eslint(no-unused-vars) 105건 · no-useless-escape 16건 · unicorn(no-new-array) 1건
  - 경고가 몰린 파일: static/model-comparison.js 24건 · static/admin.js 19건 ...
```

블록이 270토큰 → **510토큰**이 됐다. 스냅샷마다 고정이라 캐시 접두사에 들어간다.

### 3단계: Java — PMD 추가 - 2026-08-21

**도구 선정**: SpotBugs 류는 **바이트코드**를 보므로 저장소를 빌드해야 한다 → 빌드가 곧
임의 코드 실행이라 탈락. Checkstyle 은 단일 jar 이지만 스타일 위주라 결함 신호가 약하다.
**PMD 는 소스만 보고 `errorprone` 룰셋이 ruff 의 `F` 와 같은 성격**이라 이걸 골랐다.

- [x] 룰셋을 **의견성 규칙 제외**로 고정 — ruff 에서 `UP*`·`B` 를 뺀 것과 같은 기준

| 룰셋 | air | apns4j | 판단 |
|---|---:|---:|---|
| `errorprone` 그대로 | 43건 | 40건 | `AvoidDuplicateLiterals` 25건·`ReplaceJavaUtilDate` 등 의견이 섞인다 |
| `bestpractices` | 40건 | 32건 | `SystemPrintln`·`LooseCoupling` — 관행이지 결함이 아니다 |
| `multithreading` | 10건 | 17건 | `DoNotUseThreads`("J2EE 웹앱은 스레드를 쓰지 말 것") — 의견 |
| **`errorprone` − 의견 5종** | **15건** | **28건** | 채택. `EmptyCatchBlock`·`AssignmentInOperand`·`SimpleDateFormatNeedsLocale` 등 |

- [x] 설치는 `scripts/install_pmd.py` — **pip·npm 에 없다.** 70MB zip + JVM 필요.
      받는 곳은 `cache/tools/` (임베딩 모델 `cache/models/` 와 같은 성격, 이미 gitignore 대상)
- [x] 버전 고정(7.26.0) — 최신을 따라가면 룰셋 내용이 바뀌어 요약이 조용히 달라진다
- [x] 룰셋 XML 을 **파일이 아니라 코드 상수로** 둔다 — 코드와 함께 버전 관리되고,
      저장소가 심어 둔 룰셋을 집어 갈 여지도 없다(oxlint 설정과 같은 이유)
- [x] 테스트 3건 추가. **PMD 실행은 한 건만** — JVM 기동이 2.4초라 전체 시간이 늘어난다
- [x] 검증: **300 passed / 7 skipped**

**목표 달성 — 평가 저장소 3개가 전부 섹션을 갖는다.**

```
air      pmd(java): 41개 파일 · 15건   AvoidCatchingGenericException 13 · SimpleDateFormatNeedsLocale 2
marryday ruff(python): 86개 파일 · 232건  +  oxlint(js/ts): 41개 파일 · 122건
apns4j   pmd(java): 31개 파일 · 28건   MissingSerialVersionUID 6 · AssignmentInOperand 4 · EmptyCatchBlock 4
```

**기존 테스트가 하나 깨졌고, 그게 옳았다.** `test_no_python_files_returns_nothing` 이
"분석 대상이 아닌 언어"를 **Java 로** 표현하고 있었는데 Java 가 대상이 됐다.
픽스처를 CSS·HTML 로 바꾸고 이름도 `test_unchecked_languages_return_nothing` 으로 고쳤다.

### 4단계: tarball 2회 → 1회 - 2026-08-21

`/analyze` 가 정적분석용으로 받은 소스를 **버리지 않고 색인 큐로 넘긴다.**
아카이브 다운로드는 core 와 별개 제한을 받아 두 번 받는 것이 공짜가 아니었다.

- [x] `indexer.start(..., files=)` → `index_queue.submit(..., files=)` → `run_build(..., files)`
      배관. 없으면(캐시 히트·정적분석 실패) 전과 같이 스스로 받는다
- [x] **크기 상한 `MAX_HANDOFF_CHARS = 20MB`** — 수집 상한이 파일 3,000개 × 200KB 라
      **이론상 600MB** 까지 가능하다. tarball 한 번을 아끼자고 워커가 처리할 때까지
      그만한 메모리를 붙들 이유는 없다. 넘으면 넘기지 않고 색인이 받는다
      (실측: 소스 2.26MB 짜리 저장소가 181파일이라 이 값에 걸리는 저장소는 드물다)
- [x] 워커가 처리 후 참조를 놓는다 — 큐 항목이 들고 있으면 다음 항목이 올 때까지 남는다
- [x] 부수 효과: 색인이 보는 소스가 요약·정적분석과 **같은 시점**이 된다.
      스냅샷은 `pushed_at` 으로 고정돼 있으므로 같은 시점을 보는 쪽이 오히려 맞다
- [x] 테스트 5건 — 넘기면 안 받는다 · 안 넘기면 받는다 · 상한 초과는 안 넘긴다 ·
      `/analyze` 가 실제로 넘긴다 · 캐시 히트는 넘길 것이 없다
- [x] **허위 통과 확인**: 상한 검사를 `if False:` 로 무력화하니 해당 테스트가 깨졌다.
      원복 후 파일 해시가 일치하는 것까지 확인했다
- [x] 검증: **305 passed / 7 skipped**

**테스트 하나를 잘못 쓸 뻔했다.** 처음엔 `sys.modules` 를 치환해 큐를 대역으로 바꿨는데,
`from app.services import index_queue` 는 **패키지 속성을 먼저 보므로** 그 방식은 안 먹는다.
모듈 객체의 `submit` 을 직접 갈아끼우는 방식으로 고쳤다.

### 5단계: 린터 병렬 실행 - 2026-08-21

셋 다 subprocess 를 기다리는 일이라(GIL 을 놓는다) `ThreadPoolExecutor` 로 충분하다.

- [x] 실측 (python 86 · js 41 · java 31 을 합친 213파일, 3라운드 인터리브)

| | 중앙값 |
|---|---:|
| 순차 | 2.77초 |
| **병렬** | **2.27초** |

**0.50초 단축(18%).** 예상대로 PMD 의 JVM 기동 2.4초가 병렬 시간을 지배한다 —
병렬화로 없앨 수 있는 것은 나머지 둘(ruff 0.03 + oxlint 0.4)뿐이다.
`/analyze` 전체가 11~55초이므로 **사용자 체감으로는 1~4%** 다. 작지만 공짜에 가깝다.

- [x] **결과 순서를 `_RUNNERS` 순서로 고정**했다. 이 집계는 `context` 에 들어가고
      그것이 `cache_control` 이 걸린 캐시 접두사다 — 끝난 순서대로 담으면 같은 저장소도
      실행마다 바이트가 달라져 **매 질문이 캐시를 새로 쓴다**
      (`build_source_bundle` 이 경로 순으로 정렬하는 것과 같은 이유)
- [x] 테스트 2건 — 순서 고정(느린 러너를 먼저 제출해 확인) · 하나가 터져도 나머지는 남는다
- [x] 검증: **307 passed / 7 skipped**

**변이 테스트를 한 번 헛돌렸다.** 순서 고정을 확인하려고 `sorted(key=-len(이름))` 으로
바꿔 봤는데 러너 이름이 `slow`·`fast` 로 **길이가 같아** 순서가 안 바뀌었고, 테스트가
그대로 통과했다. `reversed(futures)` 로 다시 하니 제대로 깨졌다 —
**변이가 실제로 동작을 바꿨는지부터 확인해야 한다.**

### 6단계: CSS·HTML — **CSS 만 붙이고 HTML 은 접었다** - 2026-08-21

"값어치를 먼저 따진다"가 이 절의 과제였다. 평가 저장소 60파일(css 39 · html 21)에
후보 도구를 실제로 돌려 **건수가 아니라 내용**을 봤다.

| 도구 | 총 건수 | 그중 결함성 | 안전한가 |
|---|---:|---:|---|
| **stylelint** (css) | 192 | **37** | **예** — `--config` 를 주면 저장소 설정을 읽지도 실행하지도 않는다 |
| html-validate (html) | 325 | ~65 | **아니오** — 아래 |
| htmlhint (html) | 5 | 5 | 안전성 이전에 신호가 없다 |

- [x] **HTML 탈락 — html-validate 는 임의 코드 실행이다.** `.htmlvalidate.js`·`.cjs` 를 심고
      부작용(파일 생성)을 관찰했더니 **우리가 `--config` 로 규칙을 못박아도 실행됐고**,
      검사까지 침묵당했다(2건 → 0건). oxlint 는 `--config` 로 122건이 복구됐던 것과 정반대다.
      ESLint·Pylint 를 뺀 것과 같은 이유로 **원안 단계에서 이미 탈락 사유였다**
- [x] **CSS 는 선별이 값어치를 갈랐다.** recommended 상당 192건 중 **155건(81%)이
      `no-descending-specificity` 하나**였다 — 특이도 순서 관례지 결함이 아니다.
      그걸 빼면 37건이고 내용도 실수 쪽이었다: `style.css:92·105` shorthand `margin` 이
      앞의 `margin-bottom` 을 덮음, `arch.css` 가 `.tc` 를 18행과 178행에 두 번
- [x] `_run_stylelint` + `STYLELINT_RULES` 14종을 **코드 상수로** (PMD 룰셋과 같은 이유).
      `Back/package.json` 에 `stylelint 17.14.1` 고정 — 설치가 10.3MB 늘어 15.5 → 25.8MB
- [x] **`.css` 만 본다.** `.scss` 는 기본 파서가 `//` 주석 등을 못 읽어 파싱 오류만 쌓이고,
      읽히게 하려면 커스텀 syntax 의존성이 하나 더 붙는다
- [x] 테스트 6건 추가 (CSS 분석 · stderr 경로 · scss 제외 · 설정 침묵 불가 · `--config` 고정 ·
      관례 규칙 제외 고정). **변이로 셋 다 확인**: stderr 폴백 제거 → 2건 실패,
      `--config` 제거 → 4건 실패, 설정 파일 필터 제거 → 2건 실패
- [x] 검증: **313 passed / 7 skipped**. LLM 실호출 없음(토큰 계산은 무과금 엔드포인트)

**함정: stylelint 는 경고를 찾으면 결과 JSON 을 stderr 로 낸다** (그때 stdout 은 빈다).
ruff·oxlint·PMD 와 반대라, 처음엔 39개 파일 192건이 **조용히 0건**으로 읽혔다.

**테스트 하나가 우연히 통과하고 있었다.** `test_repo_cannot_silence_stylelint` 가
`results[0]` 을 집었는데, 심어 둔 `stylelint.config.js` 는 확장자가 `.js` 라 필터를 빼면
**oxlint 대상이 되어 결과 순서까지 밀린다**. 도구 이름으로 고르도록 고쳤다.
겸사겸사 확인된 사실: stylelint 의 침묵 방지는 `--config` 가 담당하고, 파일명 필터는
`.css` 확장자 필터가 이미 하는 일이라 **다른 러너가 그 설정을 검사하지 않게 하는** 몫이다.

실측 (병렬이라 PMD 가 있는 저장소는 시간 변화가 없다):

```
air      pmd(java) 41파일 15건  +  stylelint(css) 6파일 5건      279 → 501 토큰
marryday ruff 86파일 232건 · oxlint 41파일 122건
                              +  stylelint(css) 33파일 32건     644 → 938 토큰
apns4j   pmd(java) 31파일 28건                                   446 토큰 (CSS 없음)
```

### 남은 것

- HTML 은 **격리 컨테이너가 생기기 전에는 붙이지 않는다.** 도구를 더 찾는 것이 아니라
  실행 격리가 선행 조건이다

### 요약 반영 확인 — **과금 $0.0341** (사용자 승인) - 2026-08-21

**측정 전에 프롬프트를 먼저 고쳤다.** `SYSTEM_PROMPT` 는 입력을 "README, 매니페스트,
파일 목록" 셋으로 명시하고 `<output_format>` 에 섹션 셋을 고정해 놨다 — **정적분석이
들어갈 자리가 없었다.** 그대로 호출하면 무시되는 것이 당연하므로, 확인에 돈을 쓸 이유가 없다.

- [x] 프롬프트 수정 — 입력 목록에 정적분석 추가 + `## 코드 상태` 섹션 신설
  - **"블록이 주어졌을 때만 쓰라"를 명시**했다. 없는데 "문제 없음"이라고 쓰면 거짓이다 —
    린터를 안 돌린 것과 코드가 깨끗한 것은 다르다
  - **버그로 이어지는 것을 앞에 두라**고 순서를 지정(정의되지 않은 이름 > 미사용 변수 > 미사용 import)
  - 집계에 없는 수치를 지어내지 말 것

| 회차 | 조건 | 비용 | 결과 |
|---|---|---:|---|
| 1 | 정적분석 블록만 (컨텍스트 0자) | $0.0113 | 반영됨 |
| 2 | **실제 컨텍스트 14,132자 + 블록** | $0.0228 | **반영됨. 묻히지 않는다** |

2회차 출력의 해당 절:

```
## 코드 상태
- 검사 범위: Python 86개 파일 (ruff, E9/F 규칙)
- F821 4건 — `np` 정의되지 않음, 런타임 오류 가능성 있음
- F811 2건 — `asyncio` 재정의, 로직 혼선 우려
- F401/F841 다수 — 미사용 import·변수 (86건/63건)로 정리 필요
- 경고 집중 파일: services/tryon_service.py(30건), core/gemini_client.py(15건)
```

지시한 우선순위대로 **F821 을 맨 앞에** 놨고, README·매니페스트 기반의 기술 스택 요약도
평소대로 나왔다. 판정용 대조에서 "총 경고 수 232"만 안 나왔는데 **결함이 아니다** —
모델이 총계 대신 규칙별 건수를 적었고 그쪽이 더 쓸모 있다. 판정 문자열이 과했다.

- [x] 1회차는 **의도한 조건이 아니었다.** 스냅샷 17 의 context 가 0자였다 —
      `key_source='eval'` 인 **평가용 픽스처 스냅샷**이라 요약·컨텍스트가 애초에 없다
      (세션·메시지도 0). 실제 대화는 전부 `pushed_at` 스냅샷에 물려 있다. 버그 아님
- [x] 검증: **293 passed / 7 skipped**
      (이 절은 4~6단계보다 **앞선 시점**이라 건수가 작다. 최신은 6단계의 313 passed)
