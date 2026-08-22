-- RepoDive 스키마. 앱이 기동할 때 app/db/pool.init_schema() 가 그대로 실행한다.
-- 마이그레이션 도구를 쓰지 않으므로 모든 문장이 멱등이어야 한다.

-- 분석한 저장소. owner/name 은 parse_github_url() 이 만든 소문자 정규화 키이고,
-- display_* 는 GitHub 이 알려준 정식 표기다 (화면에 보여줄 값).
CREATE TABLE IF NOT EXISTS repos (
  id            BIGSERIAL PRIMARY KEY,
  owner         TEXT NOT NULL,
  name          TEXT NOT NULL,
  display_owner TEXT NOT NULL,
  display_name  TEXT NOT NULL,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (owner, name)
);

-- 특정 시점의 저장소 내용 + 그때 만든 요약.
-- version 은 summary_cache._version() 이 pushed_at 에서 뽑은 숫자 문자열이고,
-- key_source 는 그 값을 무엇에서 만들었는지다 (나중에 커밋 SHA로 바꿔도 옛 행과 섞이지 않는다).
-- context 는 build_context() 원문이다. 후속 질문이 GitHub 을 다시 읽지 않고 이걸 재사용한다.
--
-- 옛 스냅샷은 지우지 않는다 — 진행 중인 대화가 그 행을 참조하고 있어서,
-- 지우면 후속 질문이 볼 코드가 사라진다 (파일 캐시 시절에는 옛 버전을 지웠다).
CREATE TABLE IF NOT EXISTS repo_snapshots (
  id         BIGSERIAL PRIMARY KEY,
  repo_id    BIGINT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  key_source TEXT NOT NULL,
  version    TEXT NOT NULL,
  context    TEXT NOT NULL,
  summary    TEXT NOT NULL,
  model      TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (repo_id, key_source, version)
);

-- 대화 한 건. 어느 저장소인지는 snapshot_id 로 조인하면 나오므로 repo_id 를 따로 두지 않는다
-- (두 곳에 두면 어긋날 수 있다). 세션이 보는 코드 버전은 스냅샷 하나로 확정된다.
CREATE TABLE IF NOT EXISTS chat_sessions (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  snapshot_id     BIGINT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_message_at TIMESTAMPTZ
);

-- 토큰·비용 열은 두지 않는다. 사용량 집계는 runs.jsonl(usage_stats)이 이미 담당하고,
-- 여기에 또 두면 같은 숫자가 두 곳에 산다.
CREATE TABLE IF NOT EXISTS messages (
  id         BIGSERIAL PRIMARY KEY,
  session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
  role       TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content    TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS messages_session_idx ON messages (session_id, id);

-- ── 사용량·남용 방지 ─────────────────────────────────────────────────────────
-- 원래 파일(logs/runs.jsonl, cache/rate_limit.json)에 있던 것들이다.
-- 파일 방식은 프로세스 안 threading.Lock 으로 read-modify-write 를 직렬화하는데,
-- **워커가 여럿이면 Lock 이 워커마다 따로라 카운트가 샌다.**
-- 여기서는 Lock 이 아니라 SQL 한 문장의 원자성으로 푼다.
--
-- DATABASE_URL 이 없으면 코드가 파일 경로로 폴백한다 — DB 가 없다고 상한이 꺼지면 안 된다.

-- 이 앱이 보낸 Claude 호출 하나하나. /admin/usage 집계의 원천이다.
CREATE TABLE IF NOT EXISTS runs (
  id                 BIGSERIAL PRIMARY KEY,
  ts                 TIMESTAMPTZ NOT NULL DEFAULT now(),
  source             TEXT NOT NULL,
  cached             BOOLEAN NOT NULL DEFAULT false,
  repo               TEXT,
  model              TEXT,
  effort             TEXT,
  fetch_ms           INT,
  llm_ms             INT,
  input_tokens       INT,
  output_tokens      INT,
  cache_write_tokens INT,
  cache_read_tokens  INT,
  cost_usd           DOUBLE PRECISION,
  context_chars      INT,
  system_prompt      TEXT,
  summary            TEXT
);

-- 최신순 조회가 전부다(관리자 화면·집계 모두).
CREATE INDEX IF NOT EXISTS runs_ts_idx ON runs (ts DESC);

-- 하루치 서비스 전체 카운터. 로그인이 없어 사용자별이 아니라 합산이다.
-- day 는 앱이 넘긴 로컬 날짜다 — CURRENT_DATE(서버 타임존)를 쓰면 집계와 경계가 어긋난다.
CREATE TABLE IF NOT EXISTS rate_limit_daily (
  day    DATE PRIMARY KEY,
  calls  INT NOT NULL DEFAULT 0,
  tokens BIGINT NOT NULL DEFAULT 0
);

-- IP 별 요청 시각. 윈도우가 슬라이딩이라 합계가 아니라 **개별 시각**이 필요하다
-- (자정에 같이 비우면 그 순간이 우회 구멍이 된다는 이유로 날짜와 분리돼 있다).
CREATE TABLE IF NOT EXISTS rate_limit_hits (
  id BIGSERIAL PRIMARY KEY,
  ip TEXT NOT NULL,
  at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS rate_limit_hits_ip_at_idx ON rate_limit_hits (ip, at DESC);

-- ── RAG ─────────────────────────────────────────────────────────────────────
-- 코드 검색용 벡터 확장. 공식 postgres 이미지에는 없어서 docker-compose 가
-- pgvector/pgvector:pg17 을 쓴다. 없으면 아래 테이블 생성이 실패한다.
CREATE EXTENSION IF NOT EXISTS vector;

-- 인덱싱을 마친 시각. 첫 질문 때 lazy 로 인덱싱하므로 "이미 했는지" 판단이 필요한데,
-- code_chunks 존재 여부로 보면 '인덱싱했지만 청크가 0개'(소스가 없는 저장소)를
-- 매번 다시 인덱싱하게 된다. 그래서 시각을 따로 남긴다.
-- (완료 판정은 아래 snapshot_index_status 로 옮겼다. 이 열은 마지막 저장 시각으로 남는다)
ALTER TABLE repo_snapshots ADD COLUMN IF NOT EXISTS indexed_at TIMESTAMPTZ;

-- 인덱싱 진행 상태. 큰 저장소는 임베딩만 수십 분이 걸려(1,683청크 ≈ 29분)
-- 백그라운드로 돌리므로, "진행 중"과 "실패"를 구분해 화면에 보여줄 곳이 필요하다.
--
-- table_name 을 키에 넣는 이유: 차원별로 청크 테이블이 갈려 있어(code_chunks / _1024)
-- 스냅샷 하나가 모델마다 다른 진행 상태를 가진다.
--
-- 완료 판정을 여기서 하는 이유: 청크 행 존재 여부로 보면 청크 0개인 저장소(소스가 없거나
-- 수집이 실패한 경우)를 질문마다 다시 인덱싱한다. 실제로 그 버그를 겪었다.
CREATE TABLE IF NOT EXISTS snapshot_index_status (
  snapshot_id  BIGINT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
  table_name   TEXT NOT NULL,
  status       TEXT NOT NULL CHECK (status IN ('pending', 'running', 'completed', 'failed')),
  chunks_total INT NOT NULL DEFAULT 0,
  chunks_done  INT NOT NULL DEFAULT 0,
  error        TEXT,
  started_at   TIMESTAMPTZ,
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (snapshot_id, table_name)
);

-- (이 표가 생기기 전에 인덱싱을 마친 스냅샷을 채우는 백필은 청크 테이블을 만든 뒤,
--  이 파일 맨 아래에 있다)

-- 이 청크들을 만든 청킹 규칙 (app/core/chunk_rule.rule_version() 의 값).
--
-- 왜 repo_snapshots 가 아니라 여기인가: 청크는 테이블별로 따로 만들어지므로
-- (code_chunks / code_chunks_1024) 규칙도 스냅샷 하나가 아니라 (스냅샷, 테이블) 단위다.
-- 스냅샷에 한 칸만 두면 두 테이블 중 한쪽 값은 반드시 거짓이 된다.
--
-- DEFAULT 'legacy' 가 곧 백필이다 — 이 열이 생기기 전에 만들어진 인덱스는 무슨 규칙으로
-- 만들었는지 알 방법이 없으므로 '모른다'로 남기고 재색인 대상으로 본다.
ALTER TABLE snapshot_index_status
  ADD COLUMN IF NOT EXISTS chunk_rule TEXT NOT NULL DEFAULT 'legacy';

-- 코드 청크와 임베딩. repo 가 아니라 **snapshot** 에 매단다 —
-- 대화 세션이 보는 코드 버전은 스냅샷 하나로 확정되므로(chat_sessions.snapshot_id),
-- 저장소가 갱신돼 새 스냅샷이 생겨도 진행 중인 대화는 자기가 보던 코드를 계속 본다.
--
-- 768 은 jinaai/jina-embeddings-v2-base-code 의 차원이다.
-- 모델을 바꾸면 차원이 달라지므로 이 테이블을 비우고 다시 인덱싱해야 한다.
CREATE TABLE IF NOT EXISTS code_chunks (
  id          BIGSERIAL PRIMARY KEY,
  snapshot_id BIGINT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
  path        TEXT NOT NULL,
  language    TEXT NOT NULL,
  start_line  INT NOT NULL,
  end_line    INT NOT NULL,
  content     TEXT NOT NULL,
  embedding   vector(768) NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS code_chunks_snapshot_idx ON code_chunks (snapshot_id);

-- 코사인 거리 기준 근사 최근접 인덱스. 저장소 하나가 수천 청크가 되면
-- 순차 스캔으로는 검색이 느려진다. 768 차원은 HNSW 상한(2000) 안이다.
CREATE INDEX IF NOT EXISTS code_chunks_embedding_idx
  ON code_chunks USING hnsw (embedding vector_cosine_ops);

-- 1024 차원 모델(intfloat/multilingual-e5-large)용 테이블.
--
-- 왜 컬럼이 아니라 테이블을 나누는가: vector(N) 은 차원이 고정이라 1024 차원 벡터를
-- vector(768) 컬럼에 넣을 수 없다(타입 오류). model 이름 컬럼을 추가하는 방식으로는
-- 차원이 다른 모델을 함께 담지 못한다.
--
-- 기존 code_chunks(768)는 그대로 두고 여기에 따로 쌓아 A/B 비교한다.
-- 어느 쪽을 쓸지는 config.CHUNK_TABLE(환경변수)로 정하므로, 되돌리려면 값만 바꾸면 된다.
CREATE TABLE IF NOT EXISTS code_chunks_1024 (
  id          BIGSERIAL PRIMARY KEY,
  snapshot_id BIGINT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
  path        TEXT NOT NULL,
  language    TEXT NOT NULL,
  start_line  INT NOT NULL,
  end_line    INT NOT NULL,
  content     TEXT NOT NULL,
  embedding   vector(1024) NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS code_chunks_1024_snapshot_idx
  ON code_chunks_1024 (snapshot_id);

CREATE INDEX IF NOT EXISTS code_chunks_1024_embedding_idx
  ON code_chunks_1024 USING hnsw (embedding vector_cosine_ops);

-- 384 차원 모델(intfloat/multilingual-e5-small)용 테이블.
--
-- 위 1024 테이블과 같은 이유로 나눈다 — vector(N) 은 차원이 고정이다.
-- 작은 모델이 큰 모델의 검색 품질을 지키는지 재려면 두 인덱스가 동시에 존재해야 하고,
-- 그래야 기각됐을 때 CHUNK_TABLE 값만 되돌리면 끝난다(재인덱싱 없이).
CREATE TABLE IF NOT EXISTS code_chunks_384 (
  id          BIGSERIAL PRIMARY KEY,
  snapshot_id BIGINT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
  path        TEXT NOT NULL,
  language    TEXT NOT NULL,
  start_line  INT NOT NULL,
  end_line    INT NOT NULL,
  content     TEXT NOT NULL,
  embedding   vector(384) NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS code_chunks_384_snapshot_idx
  ON code_chunks_384 (snapshot_id);

CREATE INDEX IF NOT EXISTS code_chunks_384_embedding_idx
  ON code_chunks_384 USING hnsw (embedding vector_cosine_ops);

-- 같은 e5-large 의 **int8 양자화**용 테이블. 차원은 1024 로 같다.
--
-- 차원이 같은데도 나누는 이유는 위와 같다 — **차원이 아니라 모델이 테이블을 가른다.**
-- 양자화 벡터는 fp32 와 코사인 0.993~0.995 로 비슷하지만 같지는 않아서, 한 테이블에
-- 섞으면 거리 계산이 두 종류의 벡터 사이에서 일어난다. 오류가 나지 않아 조용히 틀린다.
CREATE TABLE IF NOT EXISTS code_chunks_1024_int8 (
  id          BIGSERIAL PRIMARY KEY,
  snapshot_id BIGINT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
  path        TEXT NOT NULL,
  language    TEXT NOT NULL,
  start_line  INT NOT NULL,
  end_line    INT NOT NULL,
  content     TEXT NOT NULL,
  embedding   vector(1024) NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- build_id 는 index_builds 가 아래에서 만들어지므로 거기서 함께 붙인다.

CREATE INDEX IF NOT EXISTS code_chunks_1024_int8_snapshot_idx
  ON code_chunks_1024_int8 (snapshot_id);

CREATE INDEX IF NOT EXISTS code_chunks_1024_int8_embedding_idx
  ON code_chunks_1024_int8 USING hnsw (embedding vector_cosine_ops);

-- 768 차원 **E5** 모델(intfloat/multilingual-e5-base)용 테이블.
--
-- 맨 위 code_chunks 도 768 이지만 그것은 jina-code 의 벡터다. 차원이 같다고 한 테이블에
-- 넣으면 타입 오류가 나지 않아 **조용히 섞이고**, 서로 다른 모델의 벡터 사이 거리는
-- 아무 의미가 없어 검색 결과만 망가진다. 차원이 아니라 모델이 테이블을 가른다.
CREATE TABLE IF NOT EXISTS code_chunks_768_e5 (
  id          BIGSERIAL PRIMARY KEY,
  snapshot_id BIGINT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
  path        TEXT NOT NULL,
  language    TEXT NOT NULL,
  start_line  INT NOT NULL,
  end_line    INT NOT NULL,
  content     TEXT NOT NULL,
  embedding   vector(768) NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- build_id 는 index_builds 가 아래에서 만들어지므로 거기서 함께 붙인다.

CREATE INDEX IF NOT EXISTS code_chunks_768_e5_snapshot_idx
  ON code_chunks_768_e5 (snapshot_id);

CREATE INDEX IF NOT EXISTS code_chunks_768_e5_embedding_idx
  ON code_chunks_768_e5 USING hnsw (embedding vector_cosine_ops);

-- snapshot_index_status 백필. 이 표가 생기기 전에 인덱싱을 마친 스냅샷을 completed 로 채운다.
-- 안 하면 서버를 올리자마자 이미 인덱싱된 저장소를 통째로 다시 인덱싱한다.
-- 멱등: 이미 행이 있으면 아무것도 하지 않는다(진행 중인 인덱싱을 덮어쓰지 않는다).
INSERT INTO snapshot_index_status (snapshot_id, table_name, status, chunks_total, chunks_done)
SELECT snapshot_id, 'code_chunks', 'completed', count(*), count(*)
  FROM code_chunks GROUP BY snapshot_id
ON CONFLICT DO NOTHING;

INSERT INTO snapshot_index_status (snapshot_id, table_name, status, chunks_total, chunks_done)
SELECT snapshot_id, 'code_chunks_1024', 'completed', count(*), count(*)
  FROM code_chunks_1024 GROUP BY snapshot_id
ON CONFLICT DO NOTHING;

-- ── 색인 빌드 ────────────────────────────────────────────────────────────────
-- 인덱싱 한 번의 생애. **청크를 제자리에서 갈아끼우지 않기 위해** 도입했다.
--
-- 제자리 교체(DELETE 후 INSERT)를 하면 큰 저장소 기준 40~96분 동안 청크가 없어서
-- 챗봇이 코드 없이 답한다. 새 빌드를 따로 쌓아 두고 완료된 순간에 포인터
-- (snapshot_index_status.active_build_id)만 바꾸면 그 시간 내내 옛 청크로 답할 수 있고,
-- 결과가 나쁘면 포인터를 되돌리는 것으로 즉시 롤백된다.
--
-- chunk_rule 이 여기 있는 이유: 규칙은 빌드의 속성이다. 같은 스냅샷이라도 빌드마다
-- 다른 규칙으로 만들어질 수 있다 (그게 재색인의 목적이다).
CREATE TABLE IF NOT EXISTS index_builds (
  id           BIGSERIAL PRIMARY KEY,
  snapshot_id  BIGINT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
  table_name   TEXT NOT NULL,
  chunk_rule   TEXT NOT NULL,
  status       TEXT NOT NULL CHECK (status IN ('pending', 'running', 'completed', 'failed')),
  chunks_total INT NOT NULL DEFAULT 0,
  chunks_done  INT NOT NULL DEFAULT 0,
  error        TEXT,
  started_at   TIMESTAMPTZ,
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS index_builds_snapshot_idx
  ON index_builds (snapshot_id, table_name, id DESC);

-- 검색이 보는 빌드. 이 포인터가 곧 "완료된 색인"의 정의다.
ALTER TABLE snapshot_index_status
  ADD COLUMN IF NOT EXISTS active_build_id BIGINT REFERENCES index_builds(id) ON DELETE SET NULL;

-- 청크가 어느 빌드에 속하는지. 빌드가 지워지면 그 청크도 함께 사라진다.
ALTER TABLE code_chunks
  ADD COLUMN IF NOT EXISTS build_id BIGINT REFERENCES index_builds(id) ON DELETE CASCADE;
ALTER TABLE code_chunks_1024
  ADD COLUMN IF NOT EXISTS build_id BIGINT REFERENCES index_builds(id) ON DELETE CASCADE;
ALTER TABLE code_chunks_384
  ADD COLUMN IF NOT EXISTS build_id BIGINT REFERENCES index_builds(id) ON DELETE CASCADE;
ALTER TABLE code_chunks_768_e5
  ADD COLUMN IF NOT EXISTS build_id BIGINT REFERENCES index_builds(id) ON DELETE CASCADE;
ALTER TABLE code_chunks_1024_int8
  ADD COLUMN IF NOT EXISTS build_id BIGINT REFERENCES index_builds(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS code_chunks_build_idx ON code_chunks (build_id);
CREATE INDEX IF NOT EXISTS code_chunks_1024_build_idx ON code_chunks_1024 (build_id);
CREATE INDEX IF NOT EXISTS code_chunks_384_build_idx ON code_chunks_384 (build_id);
CREATE INDEX IF NOT EXISTS code_chunks_768_e5_build_idx ON code_chunks_768_e5 (build_id);
CREATE INDEX IF NOT EXISTS code_chunks_1024_int8_build_idx ON code_chunks_1024_int8 (build_id);

-- 이미 완료된 색인을 '빌드 1'로 묶는 백필.
-- 멱등: active_build_id 가 이미 있으면 건너뛴다.
WITH created AS (
  INSERT INTO index_builds
      (snapshot_id, table_name, chunk_rule, status,
       chunks_total, chunks_done, started_at, updated_at, completed_at)
  SELECT snapshot_id, table_name, chunk_rule, 'completed',
         chunks_total, chunks_done, started_at, updated_at, updated_at
    FROM snapshot_index_status
   WHERE status = 'completed' AND active_build_id IS NULL
  RETURNING id, snapshot_id, table_name
)
UPDATE snapshot_index_status s
   SET active_build_id = c.id
  FROM created c
 WHERE s.snapshot_id = c.snapshot_id AND s.table_name = c.table_name;

-- 기존 청크를 그 빌드에 연결한다 (build_id 가 비어 있는 것만).
UPDATE code_chunks c
   SET build_id = s.active_build_id
  FROM snapshot_index_status s
 WHERE s.snapshot_id = c.snapshot_id AND s.table_name = 'code_chunks'
   AND s.active_build_id IS NOT NULL AND c.build_id IS NULL;

UPDATE code_chunks_1024 c
   SET build_id = s.active_build_id
  FROM snapshot_index_status s
 WHERE s.snapshot_id = c.snapshot_id AND s.table_name = 'code_chunks_1024'
   AND s.active_build_id IS NOT NULL AND c.build_id IS NULL;

-- snapshot_index_status 의 status/chunks_*/error/chunk_rule 은 index_builds 로 옮겨갔다.
-- 코드는 더 이상 읽지 않는다(active_build_id 만 본다). 백필 근거로 남겨 둔 것이라
-- 다음 정리 때 지운다 — DROP 은 되돌릴 수 없어서 한 배포 미룬다.

-- 도메인 용어 사전(repo_glossary)은 도입했다가 되돌렸다 - 2026-08-16.
-- 한국어 질의를 코드 식별자로 넓히는 방식이었는데, 못 찾던 둘(결재 승인 18->2위,
-- 결재 반려 53->5위)은 크게 좋아졌지만 이미 잘 찾던 넷이 나빠졌다
-- (일정 저장 1->2, 일정 삭제 1->3, 비밀번호 4->6, 관리자 권한 47->56).
-- 확장한 식별자가 원래 질의의 초점을 흐리는 게 원인이었다.
-- 되돌리는 김에 테이블도 지운다. 다시 붙일 일이 있으면 이 자리에.

-- ── 작은 저장소 RAG 우회 ────────────────────────────────────────────────────
-- 임계값 이하인 저장소는 검색 대신 소스 전체를 프롬프트에 넣는다. 그 본문을 여기 둔다.
--
-- **context 에 합치지 않는 이유**: context 는 run_summary() 가 그대로 받는 문자열이라,
-- 소스를 합치면 요약 비용까지 같이 커진다. 대화에서만 이어 붙인다.
--
-- source_bundle IS NOT NULL 이 곧 "이 스냅샷은 우회 경로다" 라는 뜻이다.
-- source_tokens 는 판정에 쓴 실측값이라 임계값을 바꿨을 때 무엇이 걸리는지 볼 수 있다.
ALTER TABLE repo_snapshots ADD COLUMN IF NOT EXISTS source_bundle TEXT;
ALTER TABLE repo_snapshots ADD COLUMN IF NOT EXISTS source_tokens INT;

-- ── 스냅샷 소스 원문 ────────────────────────────────────────────────────────
-- 수집한 소스 파일의 **원문**. 위 source_bundle 과 별개다 —
-- 그쪽은 프롬프트에 넣으려고 `12|코드` 로 렌더한 결과물 한 덩어리이고,
-- 여기는 파일 단위 원본이다. 합치면 둘 중 하나는 반드시 거짓이 된다.
--
-- **왜 필요한가**: 지금 원문이 남는 곳은 source_bundle 뿐인데 그것은 전체 주입
-- 임계값 이하일 때만 채워진다. 즉 소스가 이미 프롬프트에 통째로 들어가 있는
-- 저장소에만 원문이 있고, 정작 큰 저장소에는 없다. 청크로는 복원할 수 없다 —
-- 청킹이 import 노드를 건너뛰고, 정의 사이의 틈을 버리고, 40자 미만 조각을
-- 지우기 때문에 실측에서 비어있지 않은 줄의 8.5~12.7% 가 사라졌다.
--
-- 전체 주입 여부와 **무관하게** 채운다. 크기 상한은 config.MAX_STORED_SOURCE_BYTES
-- 이고, 넘으면 한 행도 넣지 않는다(자르지 않는다 — 부분 보관은 "없다"는 답을
-- 거짓말로 만든다).
--
-- PK 가 (snapshot_id, path) 라 파일 하나를 한 행으로 읽는다. 그 선두 열이 곧
-- snapshot_id 인덱스이므로 따로 만들지 않는다.
CREATE TABLE IF NOT EXISTS snapshot_source_files (
  snapshot_id BIGINT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
  path        TEXT NOT NULL,
  content     TEXT NOT NULL,
  PRIMARY KEY (snapshot_id, path)
);
