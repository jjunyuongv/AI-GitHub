# STATUS — 지금 이 코드가 어떤 상태인가

**이 문서를 먼저 읽어라.** `docs/log/` 는 시간순 작업 로그라 **폐기된 결정이 그대로 남아 있다**
(같은 파일 안에서 결론이 뒤집힌 곳도 있다). 로그는 "왜 그렇게 됐는가"를 볼 때만 열고,
"지금 값이 무엇인가"는 여기서 본다. 충돌하면 **코드가 정답이고 이 문서가 그 다음**이다.

---

## 1. 상수 — 자동 검증됨

`Back/tests/test_status_doc.py` 가 아래 표를 코드와 대조한다. 어긋나면 테스트가 깨진다.

**적는 것은 기본값뿐이다.** `env 키` 가 있는 항목은 `Back/.env` 가 덮을 수 있고,
그 실행값은 환경마다 다르므로 **여기 적지 않는다** — 적으면 배포 환경마다 문서가 틀린다.
지금 무엇으로 돌고 있는지는 `Back/.env` 를 직접 보거나 `/admin/api/search-evals` 의
`current` 를 볼 것.

표기 규칙:

| 표기 | 뜻 | 대조 방법 |
|---|---|---|
| `'문자열'` · `800` · `(2.0, 10.0)` | 파이썬 리터럴 | `app.config` 은 AST 로 뽑은 `os.environ.get` 의 기본값, 나머지는 import 해서 얻은 값의 `repr` |
| `str(500 * 1024)` | 리터럴이 아닌 기본값 표현식 | AST 를 그대로 문자열화해서 대조 |
| `N개` | 집합·목록·딕셔너리 | 원소 수만 대조 (내용은 대조하지 않는다) |
| `(계산값)` | 코드에서 계산되는 값 | 대조하지 않는다 |
| `—` | env 로 덮을 수 없음 | — |

### 1.1 환경변수

`출처` 가 `app.config` 인 행은 **AST 로** 읽는다. 모듈을 import 하지 않으므로 `.env` 가
있든 없든 결과가 같다.

| 항목 | 기본값 | 출처 | env 키 |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | `''` | `app.config` | `ANTHROPIC_API_KEY` |
| `GITHUB_TOKEN` | `''` | `app.config` | `GITHUB_TOKEN` |
| `DATABASE_URL` | `''` | `app.config` | `DATABASE_URL` |
| `FRONTEND_ORIGIN` | `'http://localhost:5173'` | `app.config` | `FRONTEND_ORIGIN` |
| `MAX_REPO_SIZE_KB` | `'0'` | `app.config` | `MAX_REPO_SIZE_KB` |
| `EMBEDDING_MODEL` | `'jinaai/jina-embeddings-v2-base-code'` | `app.config` | `EMBEDDING_MODEL` |
| `EMBEDDING_DIM` | `'768'` | `app.config` | `EMBEDDING_DIM` |
| `EMBEDDING_SOURCE_REPO` | `''` | `app.config` | `EMBEDDING_SOURCE_REPO` |
| `EMBEDDING_MODEL_FILE` | `'onnx/model.onnx'` | `app.config` | `EMBEDDING_MODEL_FILE` |
| `EMBEDDING_CACHE_DIR` | `(계산값)` | `app.config` | `EMBEDDING_CACHE_DIR` |
| `EMBEDDING_QUERY_PREFIX` | `''` | `app.config` | `EMBEDDING_QUERY_PREFIX` |
| `EMBEDDING_PASSAGE_PREFIX` | `''` | `app.config` | `EMBEDDING_PASSAGE_PREFIX` |
| `CHUNK_TABLE` | `'code_chunks'` | `app.config` | `CHUNK_TABLE` |
| `MAX_ARCHIVE_BYTES` | `str(500 * 1024 * 1024)` | `app.config` | `MAX_ARCHIVE_BYTES` |
| `MAX_SOURCE_FILE_BYTES` | `str(200 * 1024)` | `app.config` | `MAX_SOURCE_FILE_BYTES` |
| `MAX_SOURCE_FILES` | `'3000'` | `app.config` | `MAX_SOURCE_FILES` |
| `MAX_STORED_SOURCE_BYTES` | `str(20 * 1024 * 1024)` | `app.config` | `MAX_STORED_SOURCE_BYTES` |
| `FULL_INJECTION_MAX_TOKENS` | `'57000'` | `app.config` | `FULL_INJECTION_MAX_TOKENS` |
| `FULL_INJECTION_MAX_SOURCE_BYTES` | `str(500 * 1024)` | `app.config` | `FULL_INJECTION_MAX_SOURCE_BYTES` |
| `DAILY_LLM_CALL_LIMIT` | `'500'` | `app.config` | `DAILY_LLM_CALL_LIMIT` |
| `DAILY_TOKEN_LIMIT` | `'5000000'` | `app.config` | `DAILY_TOKEN_LIMIT` |
| `IP_RATE_LIMIT` | `'20'` | `app.config` | `IP_RATE_LIMIT` |
| `IP_RATE_WINDOW_SECONDS` | `'3600'` | `app.config` | `IP_RATE_WINDOW_SECONDS` |
| `TRUST_PROXY_HEADERS` | `'0'` | `app.config` | `TRUST_PROXY_HEADERS` |

기본값이 표현식인 것의 실제 크기 — `MAX_ARCHIVE_BYTES` 500MB ·
`MAX_SOURCE_FILE_BYTES` 200KB · `FULL_INJECTION_MAX_SOURCE_BYTES` 500KB ·
`MAX_STORED_SOURCE_BYTES` 20MB.
`EMBEDDING_SOURCE_REPO` 는 비면 `EMBEDDING_MODEL` 로 폴백하고,
`EMBEDDING_CACHE_DIR` 은 `Back/cache/models` 로 계산된다.

**임베딩 설정은 기본값으로 돌고 있지 않다.** `EMBEDDING_MODEL`·`EMBEDDING_DIM`·
`CHUNK_TABLE`·접두어 2종·`EMBEDDING_SOURCE_REPO`·`EMBEDDING_MODEL_FILE` 일곱 개를
`.env` 가 덮어 e5-large 계열로 돌린다. 기본값(jina-code 768)만 보고 판단하면 틀린다.

### 1.2 청킹

| 항목 | 기본값 | 출처 | env 키 |
|---|---|---|---|
| `MAX_CHUNK_CHARS` | `800` | `app.core.chunker` | — |
| `MIN_CHUNK_CHARS` | `200` | `app.core.chunker` | — |
| `OVERLAP_LINES` | `3` | `app.core.chunker` | — |
| `TOKEN_LIMIT_MARGIN` | `12` | `app.core.chunker` | — |
| `MAX_SPLIT_PASSES` | `3` | `app.core.chunker` | — |
| `IMPORT_NODES` | `8개` | `app.core.chunker` | — |
| `CONTAINER_NODES` | `18개` | `app.core.chunker` | — |
| `DEFINITION_NODES` | `20개` | `app.core.chunker` | — |
| `EXTENSION_TO_LANGUAGE` | `39개` | `app.core.languages` | — |
| `LEGACY` | `'legacy'` | `app.core.chunk_rule` | — |
| `_RULE_FUNCTIONS` | `6개` | `app.core.chunk_rule` | — |

`chunk_rule.rule_version()` 은 **손으로 관리하는 값이 아니다.** 위 상수와 청킹 함수 6개의
AST 에서 자동 산출한다(sha256 앞 8자). 청킹을 고치면 자동으로 달라지고, 기동할 때
낡은 색인이 로그에 뜬다.

### 1.3 임베딩

| 항목 | 기본값 | 출처 | env 키 |
|---|---|---|---|
| `EMBED_BATCH_SIZE` | `32` | `app.core.embeddings` | — |
| `PROGRESS_EVERY` | `32` | `app.core.embeddings` | — |

### 1.4 검색

| 항목 | 기본값 | 출처 | env 키 |
|---|---|---|---|
| `TOP_K` | `8` | `app.services.indexer` | — |
| `MAX_HANDOFF_CHARS` | `20971520` | `app.services.indexer` | — |
| `LOW_INFO_PENALTY` | `0.03` | `app.services.indexer` | — |
| `CANDIDATE_MULTIPLIER` | `5` | `app.services.indexer` | — |
| `STYLE_LANGUAGES` | `2개` | `app.services.indexer` | — |
| `ENTRY_POINT_MARKERS` | `5개` | `app.services.indexer` | — |
| `INHERITANCE_MARKERS` | `4개` | `app.services.indexer` | — |

### 1.5 LLM

| 항목 | 기본값 | 출처 | env 키 |
|---|---|---|---|
| `DEFAULT_MODEL` | `'claude-sonnet-5'` | `app.services.claude_client` | — |
| `DEFAULT_EFFORT` | `'medium'` | `app.services.claude_client` | — |
| `MODELS` | `2개` | `app.services.claude_client` | — |
| `EFFORT_LEVELS` | `5개` | `app.services.claude_client` | — |
| `MAX_TOKENS` | `4096` | `app.services.claude_client` | — |
| `MAX_HISTORY_MESSAGES` | `20` | `app.services.claude_client` | — |
| `MAX_TOOL_ROUND_TRIPS` | `3` | `app.services.claude_client` | — |
| `TOOL_SCHEMAS` | `3개` | `app.services.tools` | — |
| `MAX_TOOL_RESULT_TOKENS` | `800` | `app.services.tools` | — |
| `MAX_GREP_MATCHES` | `30` | `app.services.tools` | — |
| `PRICING` | `1개` | `app.services.claude_client` | — |
| `SONNET_5_INTRO_PRICE` | `(2.0, 10.0)` | `app.services.claude_client` | — |
| `SONNET_5_LIST_PRICE` | `(3.0, 15.0)` | `app.services.claude_client` | — |
| `CACHE_WRITE_MULTIPLIER` | `1.25` | `app.services.claude_client` | — |
| `CACHE_READ_MULTIPLIER` | `0.1` | `app.services.claude_client` | — |
| `REFUSAL_PHRASES` | `2개` | `app.services.claude_client` | — |
| `CHARS_PER_TOKEN` | `2.0` | `app.services.context_builder` | — |

**도구 상한 셋은 비용 산식에서 나온 값이다.** 라운드트립 R 회의 입력은
`Σₖ(0.1·P + q + Σᵢ<ₖ(aᵢ + rᵢ))` 라 꼬리가 이차로 누적된다. 기준선($0.008155/질문)에
`P=1,140 · q≈40 · a_tool=150 · a_final=330 · r=800` 을 대입하면 **R=3 이 2.51배,
R=4 가 3.66배**로 `COST_RATIO_LIMIT`(3.0)을 넘는다 — 3 이 상한 아래에 남는 마지막 값이다.
`r` 을 1,500 으로 두면 같은 R=3 에서 3.78배가 된다. **셋 중 하나만 고치면 이 산식이 깨진다.**

sonnet-5 도입가는 `SONNET_5_INTRO_LAST_DAY`(2026-08-31)까지다. **날짜로 자동 전환되므로
사람이 고칠 것이 없다** — `pricing_for(model, at)` 가 그날을 넘기면 정가를 돌려준다.

`REFUSAL_PHRASES` 는 `CHAT_SYSTEM_PROMPT` 가 강제하는 거절 문구다. **프롬프트에 f-string
으로 끼워 넣지 않는다** — 끼워 넣으면 정합성 테스트가 동어반복이 되어 문구가 갈라져도
통과한다. 리터럴로 두고 `test_claude_client.py` 가 포함 여부를 검사한다.

**이 두 문구는 프롬프트 계약이지 채점기가 아니다.** 모델은 규정 문구에 낱말을 끼워
넣어 답하므로(실측 24건 중 15건), 채점은 `tests.test_citation_quality` 의
`REFUSAL_SCOPES`·`REFUSAL_NEGATIONS`·`REFUSAL_CONCESSIONS` 가 맡는다(§1.9).

### 1.6 정적분석

| 항목 | 기본값 | 출처 | env 키 |
|---|---|---|---|
| `RUFF_RULES` | `'E9,F'` | `app.services.static_analysis` | — |
| `TIMEOUT_SECONDS` | `60` | `app.services.static_analysis` | — |
| `TOP_RULES` | `5` | `app.services.static_analysis` | — |
| `TOP_FILES` | `5` | `app.services.static_analysis` | — |
| `JS_SUFFIXES` | `6개` | `app.services.static_analysis` | — |
| `JAVA_SUFFIXES` | `1개` | `app.services.static_analysis` | — |
| `CSS_SUFFIXES` | `1개` | `app.services.static_analysis` | — |
| `STYLELINT_RULES` | `14개` | `app.services.static_analysis` | — |
| `_RUNNERS` | `4개` | `app.services.static_analysis` | — |

### 1.7 GitHub 수집

| 항목 | 기본값 | 출처 | env 키 |
|---|---|---|---|
| `MAX_TREE_ENTRIES` | `200` | `app.services.github_client` | — |
| `MAX_FILE_CHARS` | `3000` | `app.services.github_client` | — |
| `MANIFEST_FILES` | `9개` | `app.services.github_client` | — |
| `GITHUB_HOSTS` | `2개` | `app.services.github_client` | — |
| `RESERVED_OWNERS` | `27개` | `app.services.github_client` | — |
| `SKIP_DIR_PARTS` | `15개` | `app.services.github_client` | — |

### 1.8 저장·운영

| 항목 | 기본값 | 출처 | env 키 |
|---|---|---|---|
| `CONNECT_TIMEOUT_SECONDS` | `5` | `app.db.pool` | — |
| `POOL_TIMEOUT_SECONDS` | `5` | `app.db.pool` | — |
| `CHUNK_TABLES` | `5개` | `app.db.index_status` | — |
| `KEEP_BUILDS` | `1` | `app.db.index_status` | — |
| `FIELDS` | `16개` | `app.db.runs` | — |
| `EMPTY_SESSION_GRACE_HOURS` | `24` | `app.services.cleanup` | — |
| `MAX_DAYS` | `365` | `app.services.usage_stats` | — |
| `TOKEN_FIELDS` | `4개` | `app.services.usage_stats` | — |
| `KEY_SOURCE` | `'pushed_at'` | `app.services.summary_cache` | — |

### 1.9 평가 하네스

**여기만 `tests.` 모듈이다.** 측정 조건은 코드가 아니라 자(尺)라서 `app/` 에 두지 않지만,
값이 흔들리면 측정끼리 비교가 끊기므로 상수로 박고 여기서 대조한다.
두 모듈 다 import 부작용이 없다(임베딩은 지연 로드, DB 풀도 지연 생성) — 대조는 무과금이다.

| 항목 | 기본값 | 출처 | env 키 |
|---|---|---|---|
| `EVAL_SET_VERSION` | `2` | `tests.search_eval_dataset` | — |
| `EVAL_SETS` | `3개` | `tests.search_eval_dataset` | — |
| `ABSENT_SET_VERSION` | `1` | `tests.search_eval_dataset` | — |
| `ABSENT_SETS` | `3개` | `tests.search_eval_dataset` | — |
| `COST_RATIO_LIMIT` | `3.0` | `tests.test_citation_quality` | — |
| `REFUSAL_SCOPES` | `6개` | `tests.test_citation_quality` | — |
| `REFUSAL_NEGATIONS` | `3개` | `tests.test_citation_quality` | — |
| `REFUSAL_CONCESSIONS` | `1개` | `tests.test_citation_quality` | — |

`ABSENT_SETS` 는 저장소에 **없는** 기능을 묻는 질의다(세트당 6개). `EVAL_SETS` 에 섞지
않는다 — 섞으면 Recall@8 의 분모가 바뀌어 `search_evals.jsonl` 의 기존 기록과 비교가
끊기고, 인용 정확도도 조용히 희석된다. 그래서 버전을 따로 매긴다.

`COST_RATIO_LIMIT` 은 tool use 판정 기준 C 의 임계값이다 — 품질이 올라도 질문당 비용이
기준선의 이 배수를 넘으면 전면 도입하지 않는다. 근거는 `tests/test_citation_quality.py`
docstring 에 측정 전에 고정해 두었다.

거절 채점기 셋(`REFUSAL_SCOPES`·`REFUSAL_NEGATIONS`·`REFUSAL_CONCESSIONS`)은
**"[어디를 봤는가] + [거기에 없다]" 문장 구조에서 유도했다.** 정규식을 늘려 실패 건수를
맞춘 것이 아니다.

**이 자는 화이트리스트라 답변 양식이 바뀌면 샌다 — 두 번 연속 그랬다.** 처음에는 규정
문구를 연속 매칭해서 24건 중 15건을, 다음에는 부정 술어를 낱말로 나열해서 tool use
답변 15건을 놓쳤다. 두 번 다 **날조는 0건이었고 전부 자의 문제였다.** 그래서 항목을
낱말이 아니라 구조로 묶어 둔다 — 부정은 셋뿐이고(`없-`+어미 · `[탐색 동사]+지 않` ·
가능성 부정), 스코프는 범위 명사를 **양쪽 어순으로** 감싼다(`전체 X` / `X 전체`).
**다음에도 샐 것이다.** 그때 무과금으로 다시 매길 수 있게 답변 원문을 남겨 두는 것이
이 설계의 값이다. **첫 문장만 본다** — 프롬프트가 "한 문장으로 밝히라"고 요구하므로 진짜
거절은 답변을 열면서 나오고, 본문 어디든 보면 근거를 댄 뒤의 단서까지 거절로 잡힌다.
`tests/test_rescore_refusals.py` 가 양쪽에서 조인다: 거절 질의 24건은 전부 잡히고,
**정답을 짚은 답변은 하나도 거절로 잡히지 않는다**(뒤쪽이 진짜 방어선이다).
채점기를 고치면 `pytest -m evaluation tests/test_rescore_refusals.py` 로 **무과금 재채점**을
하고 거절 축 기준선을 다시 쓴다 — 답변 원문이 `Back/logs/citation_evals.jsonl` 에 남아 있어
LLM 을 다시 부를 필요가 없다.

---

## 2. 현재 시스템 상태 — 사람이 갱신

**최종 확인: 48842cd (2026-08-22)**

이 구역은 자동으로 맞는지 잴 수 없다. 각 항목에 그것이 사는 코드 위치를 적어 두었고,
`Back/tests/test_status_doc.py` 는 **그 경로가 실재하는지만** 검사한다. 내용이 맞는지는
못 재지만, 구조가 바뀌었는데 문서만 남은 상태는 잡힌다.
같은 테스트가 위 커밋 이후 `Back/app/` 변경 줄 수를 세어 300줄을 넘으면 경고한다 —
실패가 아니라 "문서를 한 번 볼 때가 됐다"는 신호다. 확인했으면 해시를 갱신할 것.

### 2.1 운영 전제 — 깨지면 조용히 틀린다

- **단일 프로세스 전제.** `uvicorn --workers 2` 이상이면 셋이 어긋난다:
  색인 큐가 메모리에 있어 워커마다 다른 큐를 갖고(`Back/app/services/index_queue.py`),
  기동 시 `reset_running()` 이 다른 워커가 돌리는 중인 빌드까지 되돌리며
  (`Back/app/db/index_status.py`), 남용 방지의 파일 폴백 경로는 `threading.Lock` 이
  워커마다 따로라 상한이 워커 수만큼 느슨해진다(`Back/app/services/rate_limit.py`).
- **DB 는 선택이다.** `DATABASE_URL` 이 비면 요약 캐시가 꺼지고(매번 LLM 호출)
  `/chat` 이 503 이 된다. 그 외는 그대로 돈다 — 실행 기록과 남용 카운터는 파일로
  폴백한다(`Back/app/services/run_log.py`, `Back/app/services/rate_limit.py`).
- **남용 방지는 서비스 전체 합산이다.** 로그인이 없어 사용자별로 나눌 수 없다.
  캐시 히트에는 걸지 않는다 — LLM 비용이 없는 요청을 막을 이유가 없다.
- **DB 장애 시 남용 제한은 통과시킨다.** 상한은 비용을 지키는 장치이지 관문이 아니다
  (`Back/app/services/rate_limit.py`).

### 2.2 색인이 도는 방식

- **큐 하나, 워커 하나.** 임베딩이 CPU 를 다 쓰므로 직렬화한다(`Back/app/services/index_queue.py`).
- **자동 재색인은 없다.** 청킹 규칙이 바뀌면 모든 색인이 한꺼번에 낡는데, 그때 자동으로
  큐에 넣으면 배포 직후가 곧 장애다. 기동 시 무엇이 낡았는지 로그로만 알리고
  (`Back/app/main.py`), 재색인은 사람이 `/admin/api/rebuild-index` 로 시작한다.
- **빌드를 쌓고 포인터를 옮긴다.** 제자리 교체를 하지 않으므로 재색인 중에도 옛 색인으로
  계속 답한다. 실패해도 활성 포인터는 그대로다(`Back/app/db/index_status.py`).
- **작은 저장소는 검색을 아예 안 만든다.** 소스 전체를 프롬프트에 넣고 빌드를 청크 0개로
  완료 처리한다(`Back/app/services/indexer.py`). 판정은 저장소 이름이 아니라 크기로만 한다.
- **소스 원문을 스냅샷 단위로 보관한다** — `snapshot_source_files` 테이블
  (`Back/app/db/sources.py`). **전체 주입 여부와 무관하게** 채운다. 전에는 원문이 남는 곳이
  전체 주입 번들뿐이라, 소스가 이미 프롬프트에 다 들어간 저장소에만 원문이 있고 큰
  저장소에는 없었다. 청크를 이어붙여 복원할 수 없다 — 실측에서 비어있지 않은 줄의
  **8.5~12.7% 가 사라졌다**(§4 참고).
- **보관 범위는 색인이 본 파일 집합과 같다. 이건 계약이지 결함이 아니다.**
  `fetch_source_files()` 가 이미 거른 것은 보관해도 없다 — `language_for()` 가 모르는
  확장자, `MAX_SOURCE_FILE_BYTES` 초과, 바이너리, `SKIP_DIR_PARTS`, `MAX_SOURCE_FILES` 상한
  (`Back/app/services/github_client.py`). **"저장소에 없다"와 "수집 범위에 없다"는 다른
  말이고, 섞이면 거절 축이 오염된다.**
- **소스가 `MAX_STORED_SOURCE_BYTES` 를 넘으면 한 행도 보관하지 않는다. 자르지 않는다.**
  일부만 보관하면 "없다"는 답이 "저장소에 없다"인지 "잘려서 없다"인지 구분되지 않는다.
  보관 여부는 행 수로 답하고(상태 열은 두지 않는다) 사유는 로그에 남는다.

### 2.3 안 하는 것 — 의도적으로

- **설정·의존성을 읽는 린터는 안 쓴다.** ESLint·Pylint·html-validate 는 남의 저장소 코드를
  우리 서버에서 실행하게 되므로 격리 없이는 못 쓴다(`Back/app/services/static_analysis.py`).
- **저장소를 빌드하지 않는다.** SpotBugs 류가 빠진 이유다. PMD 는 소스만 본다.
- **프로덕션 코드에 저장소 이름을 쓰지 않는다.** 분기는 언어·청크 수·파일 크기 같은
  속성으로 한다(`CLAUDE.md` §7). 저장소 이름이 허용되는 곳은 `Back/tests/` 와 `plan.md` 뿐이다.

### 2.4 대화가 답하는 방식

- **tool use 는 큰 저장소에서만 켜진다.** 전체 주입 임계값을 넘는 스냅샷은 도구로 답하고,
  임계값 이하는 소스 전체를 접두사에 넣은 채 도구 없이 답한다. **측정으로 정한 것이다** —
  임계값을 넘는 세트에서 인용 정확도가 0.7647 → 1.0 (+0.235, 한 건이 0.0588 이므로 4건분)
  이었고, 임계값 이하 세트에서는 전체 주입 1.0 > 도구 0.9375 로 반대였다.
  경위와 표본의 한계는 `docs/log/07-answer-quality.md` 의 '1단계 판정'.
- **검색을 미리 돌리지 않는다.** 모델이 `search_code`·`read_file`·`grep` 을 필요할 때
  부른다(`Back/app/services/tools.py`). 사전 주입한 스니펫은 캐시 브레이크포인트 **뒤**라
  라운드트립마다 정가로 되풀이 청구된다 — 실측 산식으로 3회에 3.78배가 되어 판정 기준
  C(3배)를 넘는다. 도구만 쓰면 같은 3회가 2.11배다.
- **도구 목록은 요청마다 같아야 한다.** `tools` 는 프롬프트 렌더 위치 0 이라 목록이
  갈리면 캐시 접두사가 통째로 갈라진다. 보관된 소스가 없는 스냅샷도 도구는 그대로 받고
  `read_file`·`grep` 이 "없다"고 답한다.
- **도구를 아예 안 붙이는 경우는 둘뿐이다** — 전체 주입 스냅샷(소스가 이미 접두사에 다
  들어가 있다)과 색인이 아직 안 끝난 스냅샷. 둘 다 스냅샷 속성이고 한 대화 안에서
  바뀌지 않는다(`Back/app/api/chat.py`).
- **캐시 브레이크포인트는 2개 그대로다** — system 과 첫 사용자 메시지. 도구 왕복은 그
  뒤에 쌓이므로 접두사는 깨지지 않는다. 꼬리에는 걸지 않는다(R=3 에서는 쓰기 1.25배가
  이득을 먹는다).
- **한도에 닿으면 `tool_choice` 를 바꾸지 않고 꼬리에 안내를 덧붙인다.**
  `tool_choice` 변경은 messages 캐시를 무효화해서 마지막 호출이 스냅샷 접두사를 정가로
  다시 계산한다(`Back/app/services/claude_client.py`).
- **한 질문이 호출 여럿이 된다.** 토큰·시간·비용은 합산해 한 행으로 기록하고
  `round_trips` 를 함께 남긴다 — 마지막 호출만 세면 일일 상한이 사실상 꺼진다
  (`Back/app/db/runs.py`).
- **그래서 `DAILY_LLM_CALL_LIMIT` 은 이제 "질문 수"이지 API 호출 수가 아니다.**
  `check_and_reserve()` 는 질문마다 한 번 부르는데 실제 호출은 최대 `1 + 도구 호출 수`다.
  **비용을 지키는 것은 `DAILY_TOKEN_LIMIT` 쪽이다** — 그쪽은 합산 토큰을 받으므로
  라운드트립이 늘면 그만큼 빨리 찬다(`Back/app/services/rate_limit.py`).
- **tool_result 는 대화 이력에 저장하지 않는다.** `messages` 는 질문과 최종 답변 2행만
  받는다 — 이력을 개수로 자르는 구조라(`MAX_HISTORY_MESSAGES`) 짝 잃은 `tool_use` 가
  생기면 API 가 거부한다(`Back/app/db/chats.py`).

---

## 3. 폐기된 결정 — 현행으로 착각하지 말 것

**`docs/log/` 를 앞에서부터 읽으면 아래를 현행으로 옮겨 적게 된다.** 전부 되돌려졌다.

| 폐기된 것 | 지금은 | 로그 |
|---|---|---|
| `EMBED_BATCH_SIZE = 1` (마이크로벤치에서 32 대비 2.2배 빠름) | **32.** 실제 재색인 3회에서 결론이 3번 뒤집혔다 — 원인은 배치가 아니라 CPU 점유였다. '측정으로 이긴 값'이 아니라 **'검증된 채로 지킨 값'** | `docs/log/05-tasks-a-b.md` — 폐기된 결론이 `:235`, 최종이 `:381` |
| 도메인 용어 사전 자동 생성 (STEP 3a) | **전부 제거.** 못 찾던 2개는 좋아졌지만 잘 찾던 4개가 나빠졌다. `core/symbols.py`·`services/glossary.py`·`repo_glossary` 테이블·`config.GLOSSARY_*` 모두 없다 | `docs/log/02-stage3.md:219, :280` |
| `MAX_CHUNK_CHARS = 2400` + 토큰 한도만 지키기 | **800.** 작은 Java 저장소는 미세하게 좋아졌지만 큰 Python/JS 저장소에서 한국어 Recall@8 이 0.80 → 0.60 으로 무너졌다 | `docs/log/02-stage3.md:503` |
| 스니펫 본문에 줄 번호 붙이기 | **붙이지 않는다.** 청크의 48.8% 가 원본과 줄 수부터 어긋나서 절반이 틀린 번호가 됐다. 헤더에 행 범위만 적는다 | `docs/log/05-tasks-a-b.md:32` |
| Anthropic Admin API 로 실청구 집계 | **로컬 집계.** Admin API 는 조직 계정 + admin 역할이 필요해 개인 계정에서 못 쓴다. 비용은 `pricing_for()` 기반 추정치다 | `docs/log/01-stage1-2.md:80` |
| "2026-08-31 지나면 단가를 $3/$15 로 수정할 것" | **자동화됐다.** `pricing_for()` 가 날짜로 가른다. 손댈 것이 없다 | `docs/log/01-stage1-2.md:49` (죽은 TODO) · 해결은 `docs/log/03-stage4.md:196` |
| `MAX_ARCHIVE_BYTES = 80MB` | **500MB.** 3D 에셋이 든 저장소가 걸려 코드 검색이 통째로 막혀 있었다 | `docs/log/02-stage3.md:315` 에 옛값이 표시 없이 등장 |

---

## 4. 열린 과제

- **청크를 "원본의 연속된 줄"로 재정의** — 그래야 스니펫에 줄 번호를 붙일 수 있다.
  지금은 `_merge_small` 이 떨어진 조각을 이어붙여 줄이 어긋난다. 청크 경계가 바뀌므로
  재색인과 검색 품질 재평가가 따라온다(`Back/app/services/indexer.py` 의 `format_snippets` 참고).
  **어긋나는 것은 줄 번호만이 아니다 — 내용이 사라진다.** 실측 3개 저장소에서 비어있지 않은
  줄의 8.5% · 11.1% · 12.7% 가 어느 청크에도 없었고, 완전히 복원되는 파일은 0~32.6% 였다.
  줄 수가 `end−start+1` 과 어긋나는 청크는 13.8~48.8%(48.8% 가 원래 적힌 그 수치다).
  사라지는 곳은 넷 — `chunker.chunk_file:264`(import 노드를 건너뜀) ·
  `_node_chunks:194-206`(inner 정의 사이의 틈과 꼬리) · `_merge_small:236`(40자 미만 폐기) ·
  `_merge_small:228`(떨어진 조각을 이어 붙임). 반대로 `OVERLAP_LINES` 는 줄을 **중복**시킨다.
  그래서 도구용 원문은 청크가 아니라 `snapshot_source_files` 에서 온다(§2.2).
- **`EMBED_BATCH_SIZE` 는 이 기기로 답을 못 냈다.** 바꾸려면 배포 기기에서 재거나
  CPU 점유를 고정할 것. 배치를 바꾸면 벡터도 달라져(코사인 평균 0.993) 재색인이 따라온다.
- **`FULL_INJECTION_MAX_TOKENS` 는 4세션 표본에서 역산했다.** 세션이 길어지면 임계값이
  올라간다(질문이 전부 6회면 약 88,000). 실사용 기록이 쌓이면 다시 뽑을 것.
- **tool use 판정이 기대는 표본은 사실상 한 세트다.** 임계값을 넘는 두 세트 중 하나는
  +0.235(한 건의 4배)로 명확했지만 다른 하나는 +0.0625, 곧 **한 건이라 노이즈와 구분되지
  않는다.** 판정을 바꾸지는 않는다 — 둘은 같은 코드 경로이고 세트별로 켜고 끄지 않는다.
  다만 **독립 근거가 하나뿐**이므로, `EVAL_SETS` 에 임계값을 넘는 저장소를 더해 다시 재는
  것이 남아 있다. **우선순위는 낮다**(판정이 바뀌지 않는다).
- **의도적 중복 2곳** — `indexer.TOP_K = 8` 과 `db/chunks.search(limit=8)`,
  청크 부스러기 하한 `40` 이 `Back/app/core/chunker.py` 두 곳에. 한쪽만 고치면 조용히 어긋난다.
