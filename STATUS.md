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
| `SEARCH_ONLY_SCHEMAS` | `1개` | `app.services.tools` | — |
| `MAX_TOOL_RESULT_TOKENS` | `800` | `app.services.tools` | — |
| `MAX_GREP_MATCHES` | `30` | `app.services.tools` | — |
| `CITATION_CONTEXT_LINES` | `20` | `app.api.chat` | — |
| `MAX_FILE_VIEW_LINES` | `400` | `app.api.chat` | — |
| `MAX_RANGE_LINES` | `200` | `app.services.citations` | — |
| `MIN_SNIPPET_CHARS` | `6` | `app.services.citations` | — |
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
| `FIELDS` | `17개` | `app.db.runs` | — |
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

**최종 확인: 8901176 (2026-08-25)**

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
- **프록시 뒤에서는 `TRUST_PROXY_HEADERS=1` 과 nginx 의 `X-Forwarded-For $remote_addr`
  덮어쓰기가 짝이다.** 한쪽만 있으면 IP 상한이 뚫리거나(헤더를 믿는데 안 덮어 클라이언트가
  맨 앞 항목을 지어낸다) 전체 공유가 된다(안 믿어서 모든 요청이 nginx 컨테이너 IP 하나로
  보인다). **둘 다 실측했다.** 값은 `docker-compose.prod.yml` 이 `1` 로 고정하고 덮어쓰기는
  `Front/nginx.conf` 에 있다 (`Back/app/services/rate_limit.py` 의 `client_ip`).
  로컬 개발은 프록시가 없어 둘 다 필요 없다 — TCP 연결 IP 를 그대로 쓴다.

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

- **인용 파서는 하나뿐이다** — `Back/app/services/citations.py`. `/chat` 이 화면 링크를
  만들 때와 `tests/test_line_accuracy.py` 가 행 번호 정확도를 채점할 때 **같은 함수**를
  쓴다. 파서가 둘이 되면 "채점하는 인용"과 "링크로 뜨는 인용"이 다른 집합이 되고 한쪽만
  고치면 조용히 어긋난다. **규칙을 고치면 `-m evaluation tests/test_line_accuracy.py` 의
  수치가 움직인다** — 그게 회귀 감시선이다.
- **추출은 행 표기가 있으면 다 잡는다. 채점 관문은 채점 쪽에 있다.**
  `CODE_LIKE`(코드를 그대로 인용한 것만)는 `tests/test_line_accuracy.py` 에 있고
  `_verdict()` 가 `off` 로 빼낸다 — 모수에도 판정불가에도 안 들어간다. 전에는 이것이
  추출 관문이라 **화면 경로까지 막아 450건이 버려졌다.** 옮긴 뒤에도 정확도는
  72.4%(118/163)·판정불가 102건 그대로다. `snippets` 는 채점 재료이고 비어도 인용은 만든다.
- **행 표기를 잡고도 버린 건수를 센다** — `extract()`·`for_answer()` 의 `dropped` Counter,
  `/chat` 이 한 줄로 남긴다. 화면의 `onMiss` 는 **인용을 받은 뒤**를 감시하므로 이쪽
  유실은 못 본다. 현재 남은 유실은 파일명 없음 178 · 경로 해석 실패 171 · 접미사 중복 8.
  **파일 밖 범위는 유실이 아니다** — 그건 화면이 보여 줘야 하는 것이다.
- **서버는 인용이 맞았는지 판정하지 않는다.** 행 번호 실측 정확도가 **72.4%**(118/163)인데
  그대로 넘긴다. 화면은 코드를 보여줄 뿐이고 맞았는지는 사람이 본다 —
  **틀린 것을 감추면 고칠 수가 없다.** 그래서 `GET /chat/{id}/file` 은 인용 범위 앞뒤로
  `CITATION_CONTEXT_LINES` 만큼 여유를 붙이고, 파일 밖을 가리켜도 **고쳐 주지 않는다**
  (요청 범위를 그대로 되돌려 준다).
- **인용은 보관 소스가 있어야 만들어진다.** 경로 해석이 `sources.list_paths` 에 기대므로
  보관이 없으면 목록이 비고 화면은 링크를 안 만든다 — **죽은 링크가 구조적으로 생기지
  않는다.** 특례 처리가 아니라 설계의 결과다.
- **tool use 는 큰 저장소에서만 켜진다.** 전체 주입 임계값을 넘는 스냅샷은 도구로 답하고,
  임계값 이하는 소스 전체를 접두사에 넣은 채 도구 없이 답한다. **측정으로 정한 것이다** —
  임계값을 넘는 세트에서 인용 정확도가 0.7647 → 1.0 (+0.235, 한 건이 0.0588 이므로 4건분)
  이었고, 임계값 이하 세트에서는 전체 주입 1.0 > 도구 0.9375 로 반대였다.
  경위와 표본의 한계는 `docs/log/07-answer-quality.md` 의 '1단계 판정'.
- **검색을 미리 돌리지 않는다.** 모델이 `search_code`·`read_file`·`grep` 을 필요할 때
  부른다(`Back/app/services/tools.py`). 사전 주입한 스니펫은 캐시 브레이크포인트 **뒤**라
  라운드트립마다 정가로 되풀이 청구된다 — 실측 산식으로 3회에 3.78배가 되어 판정 기준
  C(3배)를 넘는다. 도구만 쓰면 같은 3회가 2.11배다.
- **도구 셋이 다 도는 것은 보관 소스가 있는 스냅샷뿐이다.** 없으면 `search_code` 만
  남는다(`Back/app/services/tools.py` 의 `build`). 빈손인 `read_file`·`grep` 이
  "없습니다"를 돌려주면 모델이 그것을 "저장소에 없다"로 읽어 **§2.2 의 계약이 깨지기**
  때문이다. **그리고 그 축소된 경로는 측정된 적이 없다** — 판정은 도구 셋이 다 도는
  스냅샷에서 나왔고 실측 호출 분포가 `grep 86 · search_code 83 · read_file 52` 였다.
  해소는 `/admin/api/rebuild-index` 다.
- **도구 목록이 갈리는 것은 스냅샷당 한 번뿐이라 캐시 접두사가 안 깨진다.**
  `tools` 는 렌더 위치 0 이라 목록이 갈리면 접두사도 갈리는데, 이 분기는 (가) 스냅샷
  속성이고 (나) 한 대화 안에서 안 바뀌며 (다) 보관은 0 → N 으로만 가는 단조 변화라
  스냅샷 하나가 겪는 접두사 교체는 재색인 시점 한 번이다. 전체 주입 스냅샷에 도구를
  안 붙이는 분기와 같은 성질이다. **요청 내용이나 저장소 이름으로 가르지 않는다.**
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
- **빈 답변은 백엔드 밖으로 나가지 않는다.** 모델이 텍스트 블록 없이 끝낸 200 응답이
  실제로 있었다(출력 15~16토큰 · text 블록 0개 · thinking 만). `run_chat` 의 무도구
  분기와 `_call_loop` 이 각각 `NO_ANSWER`(도구 무관) 또는 `NO_ANSWER_AFTER_TOOLS`
  (도구를 썼을 때)로 대체한다(`Back/app/services/claude_client.py`).
  **화면에는 방어를 두지 않는다** — 빈 answer 가 오지 않으므로 일어날 수 없는 상태이고,
  일어날 수 없는 것을 막는 코드는 나중에 이유를 모르게 된다.
- **끝난 이유(`stop_reason`)를 `runs` 에 남긴다.** 답변이 비었을 때 refusal 인지
  end_turn 인지는 이 열로만 갈린다 — 답변 원문이 비어 있는 것이 곧 증상이라 원문으로는
  아무것도 되살릴 수 없다(`Back/app/db/runs.py`). 도구 루프는 **마지막 호출**의 값이다.
- **빈 답변은 읽을 때 질문과 함께 걸러진다** — `Back/app/db/chats.py` 의
  `list_messages`. 저장을 막는 대신 읽는 쪽에 두어 **이미 남은 행까지 함께 정리된다**
  (실제로 두 행이 남아 있고 매 요청 이력에 실려 갔다). 지우지는 않는다 — `runs` 기록과
  대조할 수 있는 유일한 흔적이다.
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
- **`FULL_INJECTION_MAX_TOKENS` 재역산 — 표본을 어떻게 자르느냐가 답을 뒤집는다.**
  산식은 `docs/log/04-tasks-1-2.md:120-133` 의 `S_max = (3·C_rag/p_in + snip) / w̄`,
  `w̄ = Σ(1.25 + 0.1(N−1)) / ΣN` 그대로다. `C_rag`·`p_in`·`snip` 을 고정하고 세션 표본만
  6세션으로 늘려 다시 뽑았다(`Back/scripts/aggregate_runs.py`).

  | 세션 표본 | w̄ | S_max |
  |---|---|---|
  | 원래 4세션 `[3,6,2,2]` | 0.4538 | 56,909 |
  | 6세션 전부 `[1,2,3,5,8,10]` | 0.3379 | 76,430 |
  | 하루 안에 끝난 세션만 `[1,2,5]` | 0.5312 | 48,617 |

  **57,000 은 두 값 사이에 있다** — 전부 넣으면 34% 여유가 생기고, 이어 쓴 세션을 빼면
  오히려 17% 헐겁다. **"빠듯한가"에 단일한 답이 없다.**
  **8·10 짜리 세션은 개발자가 여러 날에 걸쳐 이어 쓴 것이다**(3짜리도 그렇다).
  `w̄` 는 긴 세션에서 캐시 쓰기 1.25배가 나눠지는 것을 반영하는데, 캐시 TTL 이 5분이라
  **이어 쓴 세션에서는 그 나눔이 실제로 일어났는지조차 알 수 없다.** 표본이 작다는 것보다
  이쪽이 중요하다.
  **값은 바꾸지 않는다** — 2세션 늘어난 표본으로 상수를 움직이는 것이 이 절이 경계한
  바로 그 패턴이다.
  **다시 뽑는 조건은 행 수가 아니다** — 외부 사용자 트래픽이 생긴 뒤, 이어 쓴 세션을
  제외하고 뽑는다. 그때까지는 표본이 늘어도 같은 함정이다.
- **`DAILY_LLM_CALL_LIMIT` 은 이름과 실제가 갈렸다 — 어떻게 할지 미정.**
  이 상수는 "질문 수"를 세지 API 호출 수가 아니다(§2.4). 실측 평균 왕복이 0.91 이므로
  실제 호출은 질문 수의 약 1.9배다. **정하지 않았다.** 선택지와 파급:

  | 안 | 하는 일 | 파급 |
  |---|---|---|
  | 가 | 이름을 `DAILY_QUESTION_LIMIT` 으로 | 동작 무변. `config.py`·`.env.example`·`rate_limit.py`·테스트 2개·§1.1 표가 같이 움직인다. **배포 `.env` 의 옛 이름이 조용히 무시되는 것**이 진짜 비용이다 |
  | 나 | 실제 API 호출 수를 세게 | `check_and_reserve()` 는 질문 단위로 미리 잡는데 호출 수는 사후에 정해진다 — 예약·정산 구조를 바꿔야 한다. 상한이 실질 1.9배 조여진다 |
  | 다 | 그대로 두고 문서로만 | 코드 무변. 비용을 지키는 것은 `DAILY_TOKEN_LIMIT` 이고 실사용이 상한의 1.6% 다(§5.1) |
- **하네스의 절대 비용을 예산 값으로 쓰지 말 것 — 접두사가 7배 다르다.**
  하네스는 `context` 를 한 줄로 두어 캐시 접두사가 **약 1,140토큰**인데, 프로덕션은
  README·매니페스트·파일 목록이 다 들어가 **8,120토큰**이다(실측). 그래서 질문당
  비용이 **하네스 $0.0161 vs 프로덕션 $0.0225** 로 갈린다.
  **전에 이 자리에 16,240 · 14배로 적혀 있었다. 틀린 값이었다** — `cache_read_tokens` 는
  왕복마다 합산되므로 8,120 을 2회 읽은 것이었다. 접두사는 `cache_write_tokens` 로
  읽어야 한다(§5.2). 비용 수치는 영향을 받지 않는다.
  **판정(기준 C)은 흔들리지 않는다** — 같은 실행 안의 rag 대비 배수이고 두 팔이 같은
  접두사를 썼다. **흔들리는 것은 절대값이 들어가는 곳이다** — `DAILY_TOKEN_LIMIT`·
  `DAILY_LLM_CALL_LIMIT` 같은 예산 값을 하네스 숫자로 잡으면 실제보다 헐거워진다.
  프로덕션 기준선은 **§5 에 등재했다.** 다만 그 표본은 전부 개발자 검수 트래픽이라
  **외부 사용자 트래픽이 생긴 뒤 다시 뽑아야 한다** — 행 수가 아니라 이것이 조건이다.
  **이 틀림은 앞의 두 건과 성격이 다르다.** 하네스 vs 프로덕션도, `FULL_INJECTION_MAX_TOKENS`
  4세션 역산도 **표본이 작아서** 틀렸다. 이번 건은 표본이 아니라 **값의 의미를 잘못 읽어서**
  틀렸다 — 16,240 은 관측을 덜 한 값이 아니라 애초에 접두사가 아니었다.
  **그래서 방지책도 다르다.** 앞의 둘은 표본을 늘리면 되지만 이번 것은 표본을 아무리 늘려도
  같은 값이 나온다. 막는 것은 **합산 값을 단위 값으로 읽지 않았는지 검산**하는 것뿐이다
  (한 행 = 질문 하나 = API 호출 `round_trips + 1` 번, 토큰은 그 합산이다 — §2.4).
  `aggregate_runs.py` 가 매번 읽기/쓰기 정수배를 다시 검산하는 이유가 이것이다.
- **세 번째 성격 — 분포가 다른 둘을 뭉쳤다.** §5.1 의 chat 질문당 $0.02353 은 **첫 질문과
  이어지는 질문을 한 표본에 담았다.** 전체 주입 저장소의 첫 질문은 소스를 캐시에 쓰느라
  실측 **$0.107**(`cache_write` 39,010토큰)인데 이어지는 질문은 $0.008 대다 — 10배 넘게
  갈리는 두 분포다. 그걸 평균 내면 세션 길이에 따라 값이 흔들리고, 그 평균으로 예상 비용을
  잡아 **13배 빗나갔다**(예상 $0.027 · 실제 $0.122, docs/log/09-deploy.md 3단계).
  **앞의 둘과 방지책이 또 다르다** — ① 표본이 작아서 틀린 것은 표본을 늘리면 되고,
  ② 값의 의미를 잘못 읽은 것은 검산으로 막지만, ③ 이것은 **뭉친 것을 갈라야** 한다.
  평균을 정밀하게 해도 안 고쳐진다.- **한글 파일을 PowerShell 로 치환하는 사고가 세 번째다.** `TROUBLESHOOTING.md` 에 이미
  두 행(한글 파일 치환 · `Out-File` BOM)이 있는데도 또 밟았다 —
  `citations.py` 의 주석이 통째로 깨졌다. **기록이 있어도 작업 중에는 그 파일을 안 읽으므로
  안 막힌다.** 사람의 기억이 아니라 구조로 막아야 한다(치환 전 사본+해시를 강제하는 절차든,
  한글 파일 편집을 Edit 로 한정하는 규칙이든). **방지책 설계가 별도 과제로 남는다.**
- **CRLF 저장소에서 `grep` 을 실환경 확인하지 못했다.** 보관된 228개 파일 중 CRLF 가
  0개다. 단위 테스트로만 덮여 있다.
- **marryday 재색인은 그 세트로 다시 측정할 때 함께 한다. 미리 하지 않는다.**
  (4,365청크 · 29~75분 · 큐가 하나라 그동안 다른 색인이 대기하고 임베딩이 CPU 를 다 쓴다)
  미리 안 하는 이유 셋 — 판정은 air 근거이고 **marryday 는 독립 근거가 아니다**(+0.0625 =
  한 건, 노이즈와 구분 불가), 도구 셋이 다 도는 **기술 검증은 air 에서 끝났다**,
  그리고 **미리 해두면 청킹 규칙이 바뀔 때 또 낡는다.** 비용은 실재하고 이득은 측정
  시점에만 생긴다.
- **tool use 판정이 기대는 표본은 사실상 한 세트다.** 임계값을 넘는 두 세트 중 하나는
  +0.235(한 건의 4배)로 명확했지만 다른 하나는 +0.0625, 곧 **한 건이라 노이즈와 구분되지
  않는다.** 판정을 바꾸지는 않는다 — 둘은 같은 코드 경로이고 세트별로 켜고 끄지 않는다.
  다만 **독립 근거가 하나뿐**이므로, `EVAL_SETS` 에 임계값을 넘는 저장소를 더해 다시 재는
  것이 남아 있다. **우선순위는 낮다**(판정이 바뀌지 않는다).
- **`onMiss` 는 "마커를 못 찾은 유실"만 센다. "노드를 못 고른 유실"은 못 센다.**
  `citationsIn` 단계에서 탈락한 인용은 `split()` 에 도달하지 않으므로 `onMiss` 가 불리지
  않는다(`Front/src/citations.ts`). 실측 유실 1건(`41행`, offset 497)이 정확히 후자라
  **카운터가 0으로 보인다.** 운영 스택에서 인용 7건이 렌더러까지 도달한 상태로 쟀다 —
  6건은 링크됐고 1건은 링크도 카운터도 없다.
  **측정값 0 은 세 가지를 뜻할 수 있다** — 정말 0이거나, 측정 지점에 입력이 도달하지
  않았거나, 측정기가 그 종류의 유실을 아예 안 세거나. **이번은 셋째다.**
- **`citationsIn` 사각지대 — 왜 못 고르는지부터 재야 한다.** `41행`(offset 497)이 어느
  텍스트 노드의 `position` 범위에도 안 들어간다. **원인을 모르는 채 카운터만 늘리지 않는다** —
  관용구를 근거 없이 받아들이는 것과 같다. 브라우저 문제가 아니다: `Front/node_modules` 의
  `remark-parse` → `remark-rehype` 를 Node 로 그대로 돌려도 같은 1건만 노드를 못 찾는다
  (나머지 6건은 노드와 노드 안 위치까지 나온다).
- **색인 진행 폴링에 남은 것 셋.** 빈 답변 조사(2026-08-23) 때 함께 나왔지만 **그 사고의
  원인은 아니었다** — 98건은 색인이 실제로 12분 28초 동안 running 이었고 3초 간격이
  쌓인 정상 수치였다((07:20:30 − 07:15:36) ÷ 3초 = 98.0). 셋 다 별도 과제이고,
  **우선순위는 3 > 1 > 2 다 — 3만 시스템이 영구히 망가진다.**
  1. **null 경로가 조용히 무한이다.** `Front/src/api.ts` 의 `fetchIndexStatus` 가
     !ok·네트워크 실패에 null 을 주고, `Front/src/Chat.tsx` 의 `{index && …}` 가
     배너를 지운 뒤 영원히 폰다. **아직 실제로 관측된 적은 없다.**
     **고칠 것이 폴링인지 배너인지가 먼저 정해져야 한다** — null 은 "상태를 모른다"이지
     "색인이 없다"가 아닌데 화면은 후자로 그린다.
  2. **폴링 간격·상한.** 3초는 배치 주기(청크 32개, 20~30초)보다 촘촘해 같은 숫자를
     7~10번 받고, 40~96분 색인이면 한 페이지가 800~1,900건을 보낸다. 다만 간격을 늘리면
     진행률이 끊겨 보이고 백오프는 완료를 늦게 안다. **무엇이 나은지 잴 자가 없다 —
     그것부터가 과제다.**
  3. **pending 영구 정체.** `reset_running()` 이 만든 pending 을 `begin()` 이 거부하고
     (`Back/app/db/index_status.py`), 자동 재시작은 §2.2 방침상 없다. **색인 중 서버를
     내리면 재현되고, 그 스냅샷은 도구가 영영 안 붙는다.** 지금 걸린 건은 없다(빌드
     22건 전부 completed). **§2.2 의 "자동 재색인은 없다" 방침을 바꿀지가 먼저다** —
     기동 정리와 자동 재시작은 같은 방침의 앞뒤다.
- **의도적 중복 2곳** — `indexer.TOP_K = 8` 과 `db/chunks.search(limit=8)`,
  청크 부스러기 하한 `40` 이 `Back/app/core/chunker.py` 두 곳에. 한쪽만 고치면 조용히 어긋난다.

---

## 5. 실측 기준선 — `runs` 기록에서 뽑음

**집계일 2026-08-24 · 표본 51행(2026-08-14 ~ 08-24) · 무과금.**
재집계는 `Back/scripts/aggregate_runs.py`. §1 은 코드 상수를 대조하는 자리라 대조할
심볼이 없는 이 값들이 갈 곳이 아니고, §2 는 "최종 확인" 해시 하나로 낡음을 재는데
이 절은 **재집계 시점이라는 자기 시계**를 가져서 섞으면 두 시계가 엉킨다. 그래서 별도 절이다.

**표본 51행이 전부 개발자 본인의 검수 트래픽이고 외부 사용자 트래픽은 0이다.**
이것이 행 수보다 중요하다 — **500행이 쌓여도 개발자 트래픽이면 기준선이 아니다.**
아래에서 "기준선"이라 적은 것도 그 성격 안에서의 기준선이다.

**`Back/logs/runs.jsonl` 31행은 전부 DB 에 있다**(ts 대조 31/31). 합산하면 이중계상이라
재집계 스크립트는 DB 만 본다. `run_log.read()` 도 쓰지 않는다 — 그쪽은 DB 조회가
실패하면 파일로 넘어가서, 집계에 쓰면 어느 쪽을 봤는지 모른 채 숫자가 달라진다.

### 5.1 기준선

**일일 실사용 — 최대 8건 / 120,530토큰** (9일 기록, `rate_limit_daily` 실측 카운터).
`DAILY_LLM_CALL_LIMIT`(500)의 **1.6%**, `DAILY_TOKEN_LIMIT`(500만)의 **2.4%** —
상한이 실사용의 **40~60배**다. **상한을 내리자는 말이 아니다.** 외부 트래픽이 0 인
상태에서 정할 값이 아니고, 상한은 사고를 막는 장치이지 사용량 예측이 아니다.

**질문당 실비** (캐시 히트 12건 제외):

| 경로 | 표본 | 질문당 |
|---|---|---|
| analyze | 7건 | $0.01864 (0.0118 ~ 0.0225) |
| chat | 29건 | $0.02353 (0.0036 ~ 0.1004) |
| chat — 도구 도입 이후만 | 11건 | $0.02520 |

`chat` 29건에는 캐시·도구 도입 전후가 섞여 있다. 지금 구조에 대응하는 것은 11건 쪽이다.

**이 표는 첫 질문과 이어지는 질문을 가르지 않았다 — 둘은 분포가 다르다.** 전체 주입
저장소의 **첫 질문**은 소스 전체를 캐시에 쓰면서 그 값을 1.25배로 문다. 운영 스택 실측
(`teaey/apns4j`, 소스 71KB): 첫 질문 **$0.10687**(in 706 · out 793 · **cache_write 39,010**),
같은 세션의 이어지는 질문은 캐시 읽기라 **$0.008 대**다. 위의 평균 $0.02353 은 그 둘을
뭉친 값이므로 **어느 쪽 예산에도 그대로 쓰면 안 된다**(§4 의 세 번째 성격).

### 5.2 관측치 — 기준선이 아니다

**접두사 크기는 `cache_write_tokens` 로 읽는다. `cache_read_tokens` 는 접두사가 아니다.**
한 행은 질문 하나인데 그 안에 API 호출이 `round_trips + 1` 번 있고 토큰이 **합산**되므로
(§2.4), 읽기는 접두사 × 읽은 호출 수다. **이 구분을 놓쳐 접두사를 2배로 적어 두었던
적이 있다** — 16,240 은 8,120 을 2회 읽은 것이었다. 검산 10건이 전부 정수배로 맞았다
(`aggregate_runs.py` 가 매번 다시 검산한다).

| 저장소 성격 | 접두사 변천 | 비고 |
|---|---|---|
| 전체 주입 Java 라이브러리 | 37,674 | 소스 전체가 접두사에 들어간다 |
| 큰 Java 웹앱 | 5,831 → 6,057 → **8,120** | 재색인·도구 도입으로 움직였다 |
| 큰 Python/JS 웹앱 | 7,211 → **7,671** | |
| 중간 Python/JS | 4,754 → **5,788** | |

**평균을 쓰지 않는다** — 4,754 ~ 37,674 로 **7.9배** 폭이고, 같은 저장소도 변한다.
하네스 접두사(약 1,140)와의 배수는 **7.1배**다(8,120 기준).

**`round_trips` — chat 11건에서 0회 4 · 1회 4 · 2회 3, 평균 0.91.**
`MAX_TOOL_ROUND_TRIPS`(3)에 닿은 건은 0건이다. 하네스 실측(1.77~2.18)의 절반 이하인데
**왜 그런지는 모른다.** 가설은 프로덕션 접두사에 README·매니페스트·파일 목록이 들어
있어 모델이 도구를 덜 부른다는 것 — **가설이고 11건으로는 확인되지 않는다.**
질문당 비용은 0회 $0.011 · 1회 $0.028 · 2회 $0.041.
`analyze` 는 도구를 붙이지 않는 경로라 구조적으로 0 이다 — 같이 평균 내면 "도구를 덜
불렀다"가 아니라 "도구가 없었다"가 섞인다. 캐시 히트도 뺀다(`round_trips=0` 으로
기록되지만 LLM 을 부른 적이 없다).

**세션당 질문 수 — 질문이 있는 세션 6개에서 1 · 2 · 3 · 5 · 8 · 10.** 빈 세션이 4개 더 있다.
**그중 8 · 10 · 3 은 여러 날에 걸쳐 이어 쓴 것이라 실사용 세션 길이의 대표값이 아니다.**
이 구분이 표본 크기보다 중요하다 — 임계값 역산이 여기서 갈린다(§4).

**`stop_reason` — 유효 1건.** 열이 방금 추가돼 나머지 50행이 NULL 이다. **집계 불가.**
