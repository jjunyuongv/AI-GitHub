"""청킹 규칙 해시. DB 없이 돈다 (순수 계산)."""

from app.core import chunk_rule, chunker


def test_rule_is_stable_across_calls():
    """같은 규칙이면 항상 같은 값이어야 한다 — 매번 달라지면 전부 '재색인 필요'가 된다.

    집합(IMPORT_NODES 등)을 그대로 해시하면 실행마다 순서가 달라질 수 있어서
    정렬해 넣는데, 그것이 실제로 지켜지는지 본다.
    """
    assert chunk_rule.rule_version() == chunk_rule.rule_version()
    assert len(chunk_rule.rule_version()) == 8


def test_changing_a_constant_changes_the_rule(monkeypatch):
    """상수를 손으로 올리는 방식이 아니라 값에서 자동으로 나와야 한다."""
    before = chunk_rule.rule_version()
    monkeypatch.setattr(chunker, "MAX_CHUNK_CHARS", chunker.MAX_CHUNK_CHARS * 3)

    assert chunk_rule.rule_version() != before


def test_changing_overlap_changes_the_rule(monkeypatch):
    """청크 경계에 영향을 주는 값은 전부 해시에 들어가야 한다."""
    before = chunk_rule.rule_version()
    monkeypatch.setattr(chunker, "OVERLAP_LINES", chunker.OVERLAP_LINES + 2)

    assert chunk_rule.rule_version() != before


def test_changing_definition_nodes_changes_the_rule(monkeypatch):
    """언어를 추가하거나 무엇을 정의로 볼지 바꾸면 그 언어의 청크가 통째로 달라진다."""
    before = chunk_rule.rule_version()
    nodes = {**chunker.DEFINITION_NODES, "python": {"function_definition"}}
    monkeypatch.setattr(chunker, "DEFINITION_NODES", nodes)

    assert chunk_rule.rule_version() != before


def test_embedding_model_changes_the_rule(monkeypatch):
    """모델이 바뀌면 토큰 한도가 바뀌고, 한도가 바뀌면 청크가 갈라지는 지점이 달라진다."""
    before = chunk_rule.rule_version()
    monkeypatch.setattr(chunk_rule, "EMBEDDING_MODEL", "some/other-model")

    assert chunk_rule.rule_version() != before


def test_embed_batch_size_changes_the_rule(monkeypatch):
    """배치가 바뀌면 청크 경계는 그대로인데 벡터가 달라진다 — 그것도 재색인 대상이다.

    이 값이 해시에 없으면 배치를 바꿔도 낡음 경고가 안 뜨고, 옛 배치로 만든 색인과
    새 배치로 만든 색인을 겉으로 구분할 수 없다.
    """
    before = chunk_rule.rule_version()
    monkeypatch.setattr(chunk_rule, "EMBED_BATCH_SIZE", chunk_rule.EMBED_BATCH_SIZE * 2)

    assert chunk_rule.rule_version() != before


def _variant(kind: str):
    """같은 이름·같은 로직인데 주석과 docstring 만 다른 함수를 만든다.

    이름을 같게 두는 것이 핵심이다 — 실제로 일어나는 일은 "같은 함수의 주석을 고쳤다"이지
    "다른 함수를 비교한다"가 아니다. (이름이 다르면 AST 가 당연히 달라진다)
    """
    if kind == "original":
        def sample(x):
            """원래 docstring."""
            # 원래 주석
            return x + 1
    elif kind == "reworded":
        def sample(x):
            """완전히 다른 docstring 으로 바꿨다."""
            # 주석도 전부 다르게 고쳤다
            return x + 1
    else:
        def sample(x):
            """원래 docstring."""
            # 원래 주석
            return x + 2
    return sample


def test_comments_do_not_change_the_rule():
    """주석과 docstring 만 고친 편집에는 반응하지 않아야 한다.

    이 저장소는 "왜 이 값인가"를 주석으로 길게 남기는 편이라, 그 편집마다 모든 색인이
    '재색인 필요'로 뜨면 아무도 이 표시를 믿지 않게 된다.
    """
    normalized = chunk_rule._normalized_source

    assert normalized(_variant("original")) == normalized(_variant("reworded"))
    assert normalized(_variant("original")) != normalized(_variant("logic"))


def test_legacy_marker_is_not_a_valid_rule():
    """'legacy' 는 규칙 값이 아니라 '무슨 규칙인지 모른다'는 표식이다."""
    assert chunk_rule.LEGACY == "legacy"
    assert chunk_rule.rule_version() != chunk_rule.LEGACY
