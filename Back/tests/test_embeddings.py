"""임베딩 접두어 처리. 모델을 로드하지 않으므로 빠르고 과금도 없다.

접두어는 눈에 보이지 않는 곳에서 조용히 빠지기 쉽고, 빠지면 E5 계열의 검색 품질이
크게 떨어진다. 그러면 모델 비교 측정 자체가 무효가 되므로 테스트로 고정한다.
"""

import pytest

from app.core import embeddings


@pytest.fixture
def prefixes(monkeypatch):
    """E5 계열 설정을 흉내 낸다."""
    monkeypatch.setattr(embeddings, "EMBEDDING_QUERY_PREFIX", "query: ")
    monkeypatch.setattr(embeddings, "EMBEDDING_PASSAGE_PREFIX", "passage: ")


@pytest.fixture
def no_prefixes(monkeypatch):
    """접두어가 필요 없는 모델(jina-code) 설정.

    .env 값을 읽지 않고 **명시적으로** 비운다 — 그러지 않으면 이 테스트의 결과가
    개발자의 .env 설정에 따라 달라진다(실제로 e5 로 전환하자마자 깨졌다).
    """
    monkeypatch.setattr(embeddings, "EMBEDDING_QUERY_PREFIX", "")
    monkeypatch.setattr(embeddings, "EMBEDDING_PASSAGE_PREFIX", "")


def test_no_prefix_leaves_text_untouched(no_prefixes):
    """접두어가 비어 있으면 원문 그대로여야 한다 (공백 하나도 붙이지 않는다)."""
    assert embeddings.query_text("로그인 어디?") == "로그인 어디?"
    assert embeddings.document_text("public class A {}") == "public class A {}"


def test_query_and_document_prefixes_differ(prefixes):
    """질의와 문서에 **서로 다른** 접두어가 붙어야 한다. 같은 걸 붙이면 E5 의 이점이 사라진다."""
    assert embeddings.query_text("로그인 어디?") == "query: 로그인 어디?"
    assert embeddings.document_text("public class A {}") == "passage: public class A {}"


def test_prefix_is_applied_to_every_document(prefixes, monkeypatch):
    """embed_documents 가 일부 청크에만 접두어를 붙이는 실수를 막는다."""
    seen = {}

    class FakeModel:
        def embed(self, texts, **kwargs):
            seen["texts"] = list(texts)
            return iter([_FakeVector() for _ in seen["texts"]])

    monkeypatch.setattr(embeddings, "_get_model", lambda: FakeModel())
    embeddings.embed_documents(["A", "B", "C"])

    assert seen["texts"] == ["passage: A", "passage: B", "passage: C"]


def test_query_uses_embed_not_query_embed(prefixes, monkeypatch):
    """query_embed() 는 접두어를 붙여주지 않으므로 embed() 를 써야 한다."""
    calls = []

    class FakeModel:
        def embed(self, texts, **kwargs):
            calls.append(("embed", list(texts)))
            return iter([_FakeVector()])

        def query_embed(self, texts, **kwargs):  # 불리면 안 된다
            calls.append(("query_embed", list(texts)))
            return iter([_FakeVector()])

    monkeypatch.setattr(embeddings, "_get_model", lambda: FakeModel())
    embeddings.embed_query("비밀번호 암호화")

    assert calls == [("embed", ["query: 비밀번호 암호화"])]


# 모델 → (차원, 청크 테이블). 크기를 바꿔가며 비교하므로 이 표가 곧 정합성 기준이다.
# 차원이 어긋나면 INSERT 가 타입 오류로 막히고, 테이블이 어긋나면 **오류 없이**
# 다른 모델의 벡터와 섞여 검색 결과만 조용히 망가진다.
E5_MODELS = {
    "intfloat/multilingual-e5-large": (1024, "code_chunks_1024"),
    # 같은 모델의 int8 양자화. **차원이 같아도 테이블이 다르다** — 벡터가 fp32 와
    # 비슷하지만 같지 않아서, 섞이면 오류 없이 거리 계산만 조용히 틀어진다.
    "intfloat/multilingual-e5-large-int8": (1024, "code_chunks_1024_int8"),
    "intfloat/multilingual-e5-base": (768, "code_chunks_768_e5"),
    "intfloat/multilingual-e5-small": (384, "code_chunks_384"),
}


def test_current_env_prefixes_are_consistent():
    """지금 .env 설정이 모델과 아귀가 맞는가.

    E5 계열은 접두어가 필수이고, 접두어 끝 공백이 잘리면 "query:질문" 이 되어
    모델이 배운 형식과 달라진다 (.env 에 따옴표를 빠뜨리면 실제로 그렇게 된다).
    설정 실수는 조용히 품질만 떨어뜨리므로 테스트로 잡는다.
    """
    from app import config

    if "e5" not in config.EMBEDDING_MODEL:
        return

    assert config.EMBEDDING_QUERY_PREFIX == "query: ", (
        "E5 모델인데 질의 접두어가 'query: ' 가 아니다 — .env 의 따옴표를 확인하라"
    )
    assert config.EMBEDDING_PASSAGE_PREFIX == "passage: ", (
        "E5 모델인데 문서 접두어가 'passage: ' 가 아니다 — .env 의 따옴표를 확인하라"
    )

    expected = E5_MODELS.get(config.EMBEDDING_MODEL)
    assert expected is not None, (
        f"모르는 E5 모델이다: {config.EMBEDDING_MODEL}."
        " 차원과 청크 테이블을 E5_MODELS 에 등록하라"
    )
    dim, table = expected
    assert config.EMBEDDING_DIM == dim
    assert config.CHUNK_TABLE == table, (
        f"{dim} 차원 벡터는 {table} 에 넣어야 한다 — 다른 테이블은 차원이 달라 거부되거나"
        " 다른 모델의 벡터와 섞인다"
    )


# pooling 동작을 확인한 fastembed 범위. requirements.txt 의 상한과 같아야 한다.
VERIFIED_FASTEMBED = (0, 8)


def test_fastembed_version_is_within_verified_range():
    """fastembed 가 검증 범위를 벗어나면 실패한다 — **저장된 인덱스가 무효일 수 있다.**

    이 라이브러리는 모델의 pooling 방식을 바꾼 전례가 있다(0.5.1 이후 e5-large 가
    CLS → mean). 바뀌면 같은 코드·같은 모델 이름인데 벡터가 달라지는데, 예외가 나지
    않으므로 **옛 인덱스와 새 질의가 섞여 검색 품질만 조용히 떨어진다.**

    청킹 규칙 해시(chunk_rule.rule_version)에 라이브러리 버전을 넣지 않은 것은 의도다 —
    임베딩과 무관한 패치 업데이트마다 모든 인덱스가 '재색인 필요'로 떠 버리면
    그 표시를 아무도 믿지 않게 된다. 대신 여기서 **사람이 알아차리게만** 한다.

    올릴 때 할 일: 이 범위를 올리고, 평가셋으로 품질을 다시 재고, 인덱스를 재생성한다.
    """
    import fastembed

    major, minor = (int(p) for p in fastembed.__version__.split(".")[:2])
    assert (major, minor) == VERIFIED_FASTEMBED, (
        f"fastembed {fastembed.__version__} 은 검증 범위"
        f" {VERIFIED_FASTEMBED[0]}.{VERIFIED_FASTEMBED[1]}.x 밖이다."
        " pooling 방식이 바뀌었을 수 있으므로 저장된 인덱스를 그대로 믿으면 안 된다"
    )


def test_progress_cadence_is_not_tied_to_batch_size(monkeypatch):
    """진행률 보고 주기가 **배치 크기를 따라가면 안 된다.**

    보고 한 번이 DB 쓰기 한 번이라(indexer._report → index_status.advance), 둘이 묶여
    있으면 배치를 줄이는 순간 DB 쓰기가 같은 비율로 늘어난다. 실제로 배치를 32→1 로
    낮추는 측정에서 4,365청크 저장소의 쓰기가 136회 → 4,365회가 될 뻔했다.

    오류가 나지 않고 부하만 늘어나는 종류라 주석으로는 못 막는다.
    """
    monkeypatch.setattr(embeddings, "EMBED_BATCH_SIZE", 1)
    monkeypatch.setattr(embeddings, "PROGRESS_EVERY", 4)

    class FakeModel:
        def embed(self, texts, **kwargs):
            return iter([_FakeVector() for _ in texts])

    monkeypatch.setattr(embeddings, "_get_model", lambda: FakeModel())

    reported = []
    embeddings.embed_documents([str(i) for i in range(10)], on_progress=reported.append)

    # 4·8 에서 보고하고, 끝나면 총 개수를 한 번 더 보고한다 (배치 1 이어도 10번이 아니다).
    assert reported == [4, 8, 10]


def test_empty_documents_short_circuit(monkeypatch):
    """빈 목록에 모델을 로드하지 않는다 (수백 MB 로딩이 헛돈다)."""
    monkeypatch.setattr(
        embeddings, "_get_model", lambda: pytest.fail("모델을 로드하면 안 된다")
    )
    assert embeddings.embed_documents([]) == []


class _FakeVector:
    def tolist(self):
        return [0.0, 1.0]
