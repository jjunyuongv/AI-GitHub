import os

from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")  # optional, raises rate limit
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")

# PostgreSQL 접속 문자열. 비어 있으면 DB를 쓰지 않는다 —
# 요약 캐시가 꺼지고(매번 LLM 호출) 대화 기능은 503이 된다.
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# 저장소 크기 상한(KB, GitHub의 size 필드 기준). 0이면 제한 없음.
# size는 git 히스토리까지 포함한 값이라 LLM에 보내는 양과는 거의 무관하다
# (트리·파일은 MAX_TREE_ENTRIES/MAX_FILE_CHARS로 이미 잘린다).
# 그래서 기본은 끄고, 거대 저장소의 트리 조회가 문제될 때만 .env에서 켠다.
MAX_REPO_SIZE_KB = int(os.environ.get("MAX_REPO_SIZE_KB", "0"))

# 코드 검색용 임베딩 모델. 로컬에서 도는 ONNX 모델이라 호출 비용이 없다.
# 차원(768)은 schema.sql 의 vector(768) 과 맞아야 한다 — 모델을 바꾸면 둘 다 고치고
# code_chunks 를 비운 뒤 다시 인덱싱할 것.
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "jinaai/jina-embeddings-v2-base-code")
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "768"))

# fastembed 목록에 없는 모델을 등록할 때 쓰는 둘. 목록에 있는 모델이면 무시된다.
#
# EMBEDDING_MODEL 은 **우리가 붙이는 이름**이고, 가중치를 어디서 어떤 파일로 받을지는
# 이 둘이 정한다. 이름을 분리한 이유는 같은 저장소의 다른 파일(양자화 등)을 쓸 때
# 이름까지 같으면 rule_version() 이 그대로라 **옛 인덱스와 조용히 섞이기** 때문이다.
#   예) EMBEDDING_MODEL=intfloat/multilingual-e5-large-int8
#       EMBEDDING_SOURCE_REPO=intfloat/multilingual-e5-large
#       EMBEDDING_MODEL_FILE=onnx/model_qint8_avx512_vnni.onnx
EMBEDDING_SOURCE_REPO = os.environ.get("EMBEDDING_SOURCE_REPO", "") or EMBEDDING_MODEL
EMBEDDING_MODEL_FILE = os.environ.get("EMBEDDING_MODEL_FILE", "onnx/model.onnx")

# 모델 가중치 캐시 위치. 기본값을 두지 않으면 fastembed 가 OS 임시 폴더에 받는데,
# 윈도우가 그 폴더를 비우면 655MB 를 매번 다시 받는다.
EMBEDDING_CACHE_DIR = os.environ.get(
    "EMBEDDING_CACHE_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "models"),
)

# 임베딩 접두어. 모델에 따라 **필수**다 — E5 계열은 질의에 "query: ",
# 문서에 "passage: " 를 붙이지 않으면 검색 품질 측정이 무효가 된다.
# fastembed 의 query_embed() 는 접두어를 붙여주지 않으므로(embed() 를 그대로 호출한다)
# 우리가 직접 붙인다. 접두어가 필요 없는 모델(jina-code)은 빈 문자열이 정답이다.
EMBEDDING_QUERY_PREFIX = os.environ.get("EMBEDDING_QUERY_PREFIX", "")
EMBEDDING_PASSAGE_PREFIX = os.environ.get("EMBEDDING_PASSAGE_PREFIX", "")

# 청크를 넣을 테이블. pgvector 의 vector(N) 은 차원이 고정이라 차원이 다른 모델을
# 한 테이블에 담을 수 없다. 모델을 바꿔 A/B 하려면 차원별 테이블을 쓴다.
#   code_chunks      = 768  (jinaai/jina-embeddings-v2-base-code)
#   code_chunks_1024 = 1024 (intfloat/multilingual-e5-large)
#   code_chunks_384  = 384  (intfloat/multilingual-e5-small)
CHUNK_TABLE = os.environ.get("CHUNK_TABLE", "code_chunks")

# RAG 인덱싱용 소스 수집 상한. 0이면 해당 제한을 끈다.
# 소스는 tarball 한 번으로 통째로 받으므로 GitHub 요청 수가 아니라 크기가 비용이다.
#
# 80MB 로 시작했다가 500MB 로 올렸다 — 3D 에셋이 든 저장소가 여기 걸려
# 코드 검색이 통째로 막혀 있었다(경위는 plan.md 의 Stage 3.6).
# tarball 은 이미지·모델 파일까지 포함하는데
# 우리가 뽑아 쓰는 건 소스뿐이라, 아카이브 크기는 실제 인덱싱 부담과 비례하지 않는다.
# (받는 쪽은 SpooledTemporaryFile 이라 큰 파일은 디스크로 넘어간다)
MAX_ARCHIVE_BYTES = int(os.environ.get("MAX_ARCHIVE_BYTES", str(500 * 1024 * 1024)))
MAX_SOURCE_FILE_BYTES = int(os.environ.get("MAX_SOURCE_FILE_BYTES", str(200 * 1024)))
MAX_SOURCE_FILES = int(os.environ.get("MAX_SOURCE_FILES", "3000"))

# 작은 저장소 RAG 우회. 소스 본문이 이 토큰 수 이하면 검색 없이 통째로 프롬프트에 넣는다.
# 0이면 우회를 끄고 항상 RAG 를 쓴다.
#
# 비용 규칙에서 역산한 값이다 — "질문 1회당 입력 비용이 RAG 경로의 4배를 넘지 않을 것".
#
#     S_max = (3·C_rag/p_in + snip) / w̄
#
#   C_rag  질문당 RAG 비용 $0.0237 (대화 로그 13질문, 수정된 estimate_cost, 정가)
#   p_in   입력 단가 $3/1M
#   snip   질문당 스니펫 토큰 2,128 (전체 주입에서 사라지는 몫)
#   w̄      질문 하나가 지는 접두사 배율 0.4538 = Σ(1.25+0.1(N−1)) / ΣN
#
# **w̄ 가 이 값을 지배한다.** 실측 세션은 질문 2~6회(평균 3.25)로 짧아서 쓰기 1.25배가
# 잘 나눠지지 않는다. 세션이 길어지면 w̄ 가 떨어져 임계값이 올라간다
# (질문이 전부 6회면 w̄ 0.29 → 약 88,000). 표본이 4세션뿐이므로 실사용 기록이 쌓이면
# 다시 뽑을 것. 산식과 측정은 plan.md 의 '작은 저장소 RAG 우회'.
FULL_INJECTION_MAX_TOKENS = int(os.environ.get("FULL_INJECTION_MAX_TOKENS", "57000"))

# 사전 게이트. tarball 을 풀기 전에 소스 바이트 합만 보고 명백히 큰 저장소를 걸러낸다.
# 토큰 수보다 느슨하게 잡는다 — 여기서 떨어뜨린 저장소는 토큰을 세어 보지도 않으므로,
# 조이면 우회 대상이 조용히 사라진다.
FULL_INJECTION_MAX_SOURCE_BYTES = int(
    os.environ.get("FULL_INJECTION_MAX_SOURCE_BYTES", str(500 * 1024))
)

# 남용 방지 상한. 어느 값이든 0이면 그 제한을 끈다.
# 로그인이 없어 누구나 호출할 수 있으므로 서비스 전체(=모든 사용자 합산) 기준이다.
# 실사용 데이터가 없어 넉넉하게 시작하고 .env에서 조인다.
DAILY_LLM_CALL_LIMIT = int(os.environ.get("DAILY_LLM_CALL_LIMIT", "500"))
DAILY_TOKEN_LIMIT = int(os.environ.get("DAILY_TOKEN_LIMIT", "5000000"))
IP_RATE_LIMIT = int(os.environ.get("IP_RATE_LIMIT", "20"))
IP_RATE_WINDOW_SECONDS = int(os.environ.get("IP_RATE_WINDOW_SECONDS", "3600"))

# X-Forwarded-For는 클라이언트가 위조할 수 있다. 프록시(Nginx·Cloudflare 등) 뒤에
# 있을 때만 켤 것. 켜지 않으면 TCP 연결 IP를 쓴다.
TRUST_PROXY_HEADERS = os.environ.get("TRUST_PROXY_HEADERS", "0") == "1"
