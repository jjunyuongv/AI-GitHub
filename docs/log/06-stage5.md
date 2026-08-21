# 06 · Stage 5

2026-08-20 착수 · [plan.md](../../plan.md) 로 돌아가기

포함된 절:
- Stage 5: 정적분석 결합 - 2026-08-20 착수
- 정적분석
- 코드 상태

<!-- BODY -->

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
