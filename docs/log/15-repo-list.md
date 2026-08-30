# 15 · 로그인한 사용자의 공개 저장소 목록

2026-08-30 ~ · [plan.md](../../plan.md) 로 돌아가기

포함된 절:
- 로그인한 사용자의 공개 저장소 목록 (조사 · 구현 · 검증) - 2026-08-30

**14 에 붙이지 않았다.** 그 파일은 허용 목록의 역할 변경이고 이것은 화면 기능이다.

<!-- BODY -->

## 로그인한 사용자의 공개 저장소 목록 (2026-08-30)

**로컬 전용이다. 배포는 로그인이 꺼져 있어 이 화면이 안 뜬다.** LLM 을 한 번도 부르지 않았다.

첫 화면은 GitHub URL 입력창 하나였고, 로그인은 신원 확인만 해서 로그인해도 달라지는
것이 로그인 버튼 자리뿐이었다. 로그인한 사람에게 **자기 공개 저장소 목록을 보여주고
눌러서 분석을 시작하게** 했다. 지킨 선은 STATUS §2.1 의 둘이다 — 사용자 토큰을
저장하지 않는다, 비공개 저장소는 범위 밖이다.

### 조사 — scope 를 바꾸지 않는다

GitHub OAuth 문서 원문을 셋 비교했다.

| scope | 원문 | 뜻 |
|---|---|---|
| (없음) | "read-only access to public information (including user profile info, repository info, and gists)" | 지금 상태. 공개 저장소 정보 읽기가 이미 포함 |
| `public_repo` | "read/write access to code, commit statuses, … for public repositories" | **쓰기 포함** |

읽기만 주는 저장소 scope 는 클래식 OAuth 에 없다 — scope 없음이 곧 그것이다.
scope 를 추가하면 이미 승인한 사용자도 인가 화면을 다시 봐야 하는데, 우리 세션은
쿠키 + `logins` 행(14일)이라 재로그인 전까지 인가 화면에 갈 일이 없다. 즉 "로그인은
돼 있는데 목록만 안 보이는 사용자"가 최대 14일 생긴다. 게다가 인가 화면 문구가
"Public data only" 에서 "Read and write access to code" 로 바뀐다 — 읽기만 하는
서비스가 쓰기 승인을 요구하는 모양이 된다.

### 조사 — 토큰을 저장하지 않고 목록을 준다

`GET /users/{login}/repos` 는 **인증이 필요 없는 공개 엔드포인트이고 공개 저장소만
준다.** `login` 은 이미 있다 — `oauth.fetch_user()` 가 받아 `users.login` 에 저장하고
로그인할 때마다 최신값으로 덮는다. 그래서 목록은 **서버 `GITHUB_TOKEN` 으로 요청이
올 때마다 새로** 부른다.

- 세션 캐시가 없으니 갱신 문제가 없다(저장소를 새로 만들면 다음 화면 로드에 보인다)
- 사용자 토큰이 없으니 토큰 미저장이 한 줄도 안 깨진다
- 비공개가 섞일 길이 **구조적으로** 없어 걸러내는 코드가 없다.
  `/user/repos` 였다면 걸러야 했고, 빠뜨리면 눌렀을 때 404 가 났다

못 얻는 것: **조직(org) 소유 저장소**, 협업자로 참여한 남의 저장소. 그건 입력창으로 간다.
그래서 **입력창을 목록으로 대체하지 않았다.**

### 청크 상한은 예고하지 않고, 크기 판정은 한다 — 둘을 다르게 다루는 이유

- **`MAX_INDEX_CHUNKS`(300)는 예고 불가.** 바이트로 청크 수를 추정하면 언어별
  문자/청크가 431~708 로 1.64배 벌어져 경계에서 틀린다(STATUS §2.2). 그래서 판정을
  청킹 완료 후 실제 청크 수로 하도록 만든 것이다. **틀린 예고는 없는 것보다 나쁘다** —
  "될 겁니다" 라고 해 놓고 skipped 가 나면 그다음부터 안내를 안 믿는다.
- **`MAX_REPO_SIZE_KB` 는 예고 가능.** `check_repo_access` 가 413 을 낼 때 쓰는 것과
  **같은 `size` 필드를 같은 식으로** 비교한 확정 판정이다. 추정이 아니다.

둘이 갈리면(목록은 통과인데 누르면 413) 안 된다. 그래서 비교식을 `_too_large()` 하나로
뽑아 `check_repo_access` 와 `list_public_repos` 가 **같은 함수를 부르게** 했다.
빈 저장소(`size == 0`)도 같은 이유로 목록에서 뺐다 — `check_repo_access` 가 400 으로
막으므로 두면 눌러야 오류가 난다.

### 구현

- `github_client.py` — `_too_large()` 추출, `list_public_repos(login)`.
  `GET /users/{login}` 으로 정식 표기와 `public_repos` 총 개수, `GET /users/{login}/repos?per_page=100&sort=pushed&direction=desc&type=owner`.
  `follow_redirects=True` — 계정을 개명하면 `users.login` 이 낡는데 GitHub 이 301 로
  알려준다. 오류 매핑은 `check_repo_access` 와 같다(403/429→429, 404→404, 그 외→502).
  포크·아카이브는 거르지 않고 플래그만 싣는다. `html_url` 을 서버가 준다 — 프런트가
  주소를 조립하지 않는다.
- `schemas.py` — `RepoListItem`·`RepoList`.
- `api/auth.py` — `GET /auth/repos`. **`/auth` 아래에 둔 이유**: 새 최상위 경로면
  `vite.config.ts` 의 `BACKEND_PATHS` 와 `nginx.conf` 를 둘 다 고쳐야 하고, 갈리면
  배포에서 404 가 SPA 폴백에 먹혀 200 으로 보인다(`11-login.md`). 꺼짐이면 404
  (기존 관용구), 로그인 안 함이면 401.
- 프런트 — `AuthBar` 가 혼자 부르던 `/auth/me` 를 `App` 으로 올렸다(`fetchAuthStatus`).
  목록도 같은 값을 봐야 해서다. 덤으로 랜딩↔상단바 전환 때 `AuthBar` 가 언마운트되며
  `/auth/me` 를 다시 부르던 것이 없어졌다. `handleSubmit` 본문을 `startAnalyze(url)` 로
  뽑아 입력창과 목록이 같은 길로 분석을 시작한다. `Repos.tsx` 신규 — 랜딩에만,
  `status.enabled && status.user` 일 때만 그린다. `too_large` 는 불리언만 본다 —
  임계값 숫자는 프런트에 없다.

안 한 것: 검색·정렬·필터·즐겨찾기·페이지 넘김·목록 캐시·"이미 색인됨" 표시·청크 수 예고·
org 저장소·협업자 저장소·비공개·scope 변경·`/user/repos`.
`vite.config.ts`·`nginx.conf`·`config.py`·`schema.sql`·`oauth.py` 는 안 움직였다.

### 검증

- `pytest -m "not evaluation"` → **448 passed / 139 skipped** (Docker 가 꺼져 있어 DB
  테스트가 skip. 572 + 15 = 587 = 448 + 139 로 새 조합 15개만 늘었다)
- `test_github_client.py` 9조합: 빈 저장소 거르기(size 0 하나 + size>0 둘 — 거르기를
  지우면 2→3), **`too_large` 경계 양쪽**(`MAX_REPO_SIZE_KB=1000` 에 1000→False,
  1001→True — 한쪽만 두면 `>`→`>=` 변이가 통과한다), 기본값 0 이면 둘 다 False,
  요청 파라미터 직접 검사(정렬을 지우면 응답 대역으로는 안 잡힌다), 오류 매핑 4 + 목록
  호출 쪽 오류 1
- `test_auth_api.py` 6조합: 꺼짐 전수 검사에 `/auth/repos` 추가, 쿠키 없음 401, 남의/
  깨진 쿠키 401(GitHub 을 안 불렀는지까지), 로그인 200 + `users.login` 으로 불렀는지,
  `RepoAccessError` 상태 코드 통과
- `test_status_doc.py`·`test_config.py` 는 안 움직였다 — 새 환경변수·모듈 상수가 없다
- `ruff check --select E9,F` 0건 · `npm run build`(tsc + vite) 통과
- **실제 GitHub 으로 1회 호출**(LLM 아님): `list_public_repos("jjunyuongv")` →
  `total 12 / shown 11`. 빈 저장소 하나가 걸러졌고, 100개 미만이라도 머리글이
  "전체 N개 중" 으로 갈리는 경우가 실재한다 — 그래서 머리글 조건을 "100개 초과"가
  아니라 `total > repos.length` 로 잡았다

**함정 (테스트 작성 중):** `MAX_REPO_SIZE_KB` 는 `from app.config import` 로 들어온
모듈 상수라 import 시점에 굳는다. monkeypatch 는 `app.services.github_client.MAX_REPO_SIZE_KB`
를 직접 패치해야 한다. `app.config` 쪽을 패치하면 안 먹는다. 기존
`test_size_limit_rejects_when_configured` 가 이미 그렇게 하고 있어 따랐다.

### 수동 확인 (2026-08-31, 브라우저)

프런트에는 테스트 인프라가 없어 로컬에서 로그인해 직접 봤다. **정상**:
목록이 뜬다 · 머리글("공개 저장소 11개 (전체 12개 중 최근 push 순)") · 항목을 눌러
분석이 시작된다 · 입력창이 그대로 남아 있다 · 로그아웃하면 목록이 사라진다.

**포크·보관됨 배지는 화면으로 확인하지 못했다** — 확인에 쓴 계정에 포크·아카이브
저장소가 없다. 그 둘은 `test_github_client.py` 의
`test_list_skips_empty_repos_and_carries_flags` 가 플래그 값으로만 고정한다.
화면에 배지가 실제로 그려지는지는 **테스트로만 검증된 상태**다.
