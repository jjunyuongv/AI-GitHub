"""청킹 규칙 테스트. tree-sitter 만 쓰므로 네트워크도 과금도 없다."""

from app.core.chunker import (
    MAX_CHUNK_CHARS,
    chunk_file,
    chunk_files,
)
from app.core.languages import language_for

# 메서드를 실제 코드만큼 채운다 — MIN_CHUNK_CHARS 미만인 조각은 이웃과 합쳐지도록
# 설계돼 있어서, 짧은 샘플로는 "메서드가 분리되는지"를 확인할 수 없다 (PYTHON 도 같은 이유).
JAVA = """\
package com.example;

import java.util.List;
import org.springframework.context.annotation.Bean;

@Configuration
public class SecurityConfig {

    private final UserRepository userRepository;

    public SecurityConfig(UserRepository userRepository) {
        this.userRepository = userRepository;
    }

    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http.csrf(csrf -> csrf.disable())
            .authorizeHttpRequests(auth -> auth
                .requestMatchers("/admin/**").hasRole("ADMIN")
                .requestMatchers("/login", "/join", "/css/**").permitAll()
                .anyRequest().authenticated())
            .formLogin(form -> form
                .loginPage("/login")
                .defaultSuccessUrl("/", true)
                .failureUrl("/login?error"));
        return http.build();
    }

    @Bean
    public PasswordEncoder passwordEncoder() {
        // 저장할 때도, 로그인할 때 비교할 때도 같은 인코더를 쓴다.
        int strength = 10;
        SecureRandom random = new SecureRandom();
        return new BCryptPasswordEncoder(strength, random);
    }
}
"""

# 함수를 넉넉히 채운다 — MIN_CHUNK_CHARS 미만인 조각은 앞뒤와 합쳐지도록
# 설계돼 있어서, 짧은 샘플로는 "분리되는지"를 확인할 수 없다.
PYTHON = """\
import os
from typing import List


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ValueError("설정 파일의 최상위는 객체여야 합니다")
    for required in ("database_url", "api_key", "cache_dir"):
        if required not in raw:
            raise KeyError(f"설정에 {required} 가 없습니다")
    return raw


class Repository:
    def __init__(self, url):
        self.url = url
        self.cloned_at = None
        self.default_branch = "main"

    def clone(self, destination: str) -> int:
        command = ["git", "clone", "--depth", "1", self.url, destination]
        completed = subprocess.run(command, capture_output=True, text=True)
        if completed.returncode != 0:
            raise RuntimeError(f"클론 실패: {completed.stderr}")
        self.cloned_at = time.time()
        return completed.returncode
"""


def _contents(chunks):
    return "\n".join(c["content"] for c in chunks)


# ── 언어 판별 ────────────────────────────────────────────────

def test_language_is_detected_by_extension():
    assert language_for("src/Main.java") == "java"
    assert language_for("app/main.py") == "python"
    assert language_for("ui/App.tsx") == "tsx"
    # 확장자가 겹쳐 보여도 정확히 갈린다
    assert language_for("a.ts") == "typescript"
    assert language_for("a.cc") == "cpp"
    assert language_for("a.hpp") == "cpp"


def test_non_source_files_have_no_language():
    assert language_for("README.md") is None
    assert language_for("logo.png") is None
    assert language_for("Makefile") is None


def test_extension_case_is_ignored():
    assert language_for("Main.JAVA") == "java"


# ── 청킹 ────────────────────────────────────────────────────

def test_non_source_file_yields_no_chunks():
    assert chunk_file("README.md", "# 제목\n본문") == []


def test_empty_file_yields_no_chunks():
    assert chunk_file("a.py", "   \n\n  ") == []


def test_class_is_split_into_methods():
    """클래스를 통째로 두면 그 벡터가 '클래스가 하는 모든 일'의 평균이 되어
    어떤 질문에도 어중간하게 걸린다. 메서드 단위로 갈라져야 한다."""
    chunks = chunk_file("SecurityConfig.java", JAVA)
    bodies = [c["content"] for c in chunks]

    assert any("passwordEncoder" in b for b in bodies)
    assert any("filterChain" in b for b in bodies)
    # 두 메서드가 같은 청크에 뭉뚱그려지지 않았는지
    assert not any("passwordEncoder" in b and "filterChain" in b for b in bodies)


def test_short_class_header_is_kept():
    """짧은 클래스 선언을 버리면 상속 정보가 인덱스에서 통째로 사라진다.

    평가 질의 id_04("TextWebSocketHandler 상속")는 순위가 낮았던 게 아니라 정답 자체가
    없었다 — `class X extends Y` 는 그 파일에서 그 한 줄에만 있는데, 헤더가 짧다는
    이유로 버려졌기 때문이다.
    """
    source = """\
//준영
public class ChatHandler extends TextWebSocketHandler {

    private static final Map<String, WebSocketSession> sessions = new ConcurrentHashMap<>();

    @Override
    public void afterConnectionEstablished(WebSocketSession session) throws Exception {
        String userId = (String) session.getAttributes().get("userId");
        sessions.put(userId, session);
        log.info("연결됨: {} (총 {}명)", userId, sessions.size());
        broadcastPresence(userId, true);
    }
}
"""
    text = _contents(chunk_file("ChatHandler.java", source))
    assert "extends TextWebSocketHandler" in text


def test_small_chunks_are_absorbed_only_once():
    """작은 조각은 이웃 하나에만 붙는다.

    연쇄로 붙게 두면 짧은 메서드들이 줄줄이 한 청크로 뭉쳐, 그 벡터가 "이 메서드들이
    하는 일"의 평균이 된다 — 클래스를 통째로 두지 않는 것과 같은 이유로 막는다.
    """
    source = "class A:\n" + "\n".join(
        f"    def m{i}(self):\n        return {i}" for i in range(6)
    ) + "\n"
    bodies = [c["content"] for c in chunk_file("a.py", source)]

    # 6개가 하나로 뭉치지 않는다 (짝을 이뤄 붙는 것까지는 허용된다).
    assert not any(sum(f"def m{i}" in b for i in range(6)) > 2 for b in bodies)


def test_imports_are_excluded():
    """import 는 검색에 걸리기만 하고 답의 근거가 되지 못한다."""
    text = _contents(chunk_file("SecurityConfig.java", JAVA))
    assert "import java.util.List" not in text
    assert "import org.springframework" not in text
    # 정작 필요한 코드는 남아 있어야 한다
    assert "BCryptPasswordEncoder" in text


def test_python_functions_and_methods_are_separated():
    chunks = chunk_file("repo.py", PYTHON)
    bodies = [c["content"] for c in chunks]
    assert any("load_config" in b for b in bodies)
    assert any("def clone" in b for b in bodies)
    assert not any("load_config" in b and "def clone" in b for b in bodies)


def test_line_numbers_match_the_source():
    """줄 번호는 답변이 "SecurityConfig.java 89행"처럼 근거를 짚는 데 쓰인다.
    어긋나면 사용자가 엉뚱한 곳을 열게 된다.

    앞 공백은 비교하지 않는다 — tree-sitter 는 노드 시작을 들여쓰기 뒤로 잡아서
    청크 첫 줄에 원본의 들여쓰기가 빠진다 (줄 번호 자체는 정확하다).
    """
    for path, source in (("SecurityConfig.java", JAVA), ("repo.py", PYTHON)):
        lines = source.splitlines()
        for chunk in chunk_file(path, source):
            assert 1 <= chunk["start_line"] <= chunk["end_line"] <= len(lines)
            first = chunk["content"].splitlines()[0].strip()
            assert lines[chunk["start_line"] - 1].strip() == first


def test_chunks_stay_within_the_size_limit():
    # 정의가 하나도 없는 거대 파일도 라인 폴백으로 잘려야 한다
    huge = "\n".join(f"x = {i}  # {'설명 ' * 20}" for i in range(400))
    for chunk in chunk_file("big.py", huge):
        assert len(chunk["content"]) <= MAX_CHUNK_CHARS


def test_broken_syntax_still_produces_chunks():
    """문법이 깨졌다고 그 파일이 검색에서 통째로 사라지면 안 된다."""
    broken = "public class Oops {\n" + "\n".join(f"  int v{i} = {i};" for i in range(80))
    chunks = chunk_file("Oops.java", broken)
    assert chunks
    assert "v79" in _contents(chunks)


def test_tiny_fragments_are_dropped():
    """주석 한 줄짜리 청크는 임베딩 비용만 쓴다."""
    for chunk in chunk_file("repo.py", PYTHON):
        assert len(chunk["content"].strip()) >= 40


def test_chunk_files_flattens_every_file():
    chunks = chunk_files({"A.java": JAVA, "b.py": PYTHON, "README.md": "# 무시"})
    paths = {c["path"] for c in chunks}
    assert paths == {"A.java", "b.py"}


# ── 토큰 한도 재분할 ────────────────────────────────────────

# 문자 2개 = 토큰 1개인 가짜 토크나이저. 실제 모델을 쓰면 테스트가 2GB 가중치를
# 내려받아 올려야 하므로, chunk_files 는 카운터를 주입으로 받는다.
def _fake_counter(texts):
    return [len(t) // 2 for t in texts]


def test_chunks_over_the_token_limit_are_split():
    """문자 상한으로는 토큰 한도를 지킬 수 없다 — 실측 비율이 1.68~17.4 로 벌어진다.

    그래서 한도를 넘는 청크만 토크나이저 기준으로 다시 자른다.
    """
    long_source = "\n".join(f"    total = total + value_{i} * weight_{i}" for i in range(60))
    files = {"a.py": f"def calculate(values, weights):\n{long_source}\n    return total\n"}

    without = chunk_files(files)
    with_limit = chunk_files(files, count_tokens=_fake_counter, token_limit=100)

    # 한도(100 - 여유)를 넘는 청크가 없어야 한다
    assert max(_fake_counter([c["content"] for c in without])) > 100
    assert max(_fake_counter([c["content"] for c in with_limit])) <= 100
    assert len(with_limit) > len(without)


def test_chunks_within_the_limit_are_left_alone():
    """한도 안에 있는 청크는 건드리지 않는다 — 문맥이 온전한 편이 검색에 유리하다."""
    files = {"a.py": PYTHON}

    without = chunk_files(files)
    with_limit = chunk_files(files, count_tokens=_fake_counter, token_limit=100_000)

    assert [c["content"] for c in with_limit] == [c["content"] for c in without]


def test_missing_tokenizer_falls_back_to_the_char_limit():
    """토크나이저에 닿지 못해도 인덱싱은 진행돼야 한다 (문자 상한만 믿는다)."""
    files = {"a.py": PYTHON}

    assert chunk_files(files, count_tokens=lambda texts: None, token_limit=100) == chunk_files(files)


def test_line_numbers_survive_the_token_split():
    """재분할 뒤에도 줄 번호가 원본과 맞아야 한다 (답변이 근거를 짚는 데 쓴다)."""
    source = "def f():\n" + "\n".join(f"    x{i} = {i} + 1" for i in range(80)) + "\n"
    lines = source.splitlines()

    for chunk in chunk_files({"a.py": source}, count_tokens=_fake_counter, token_limit=100):
        assert 1 <= chunk["start_line"] <= chunk["end_line"] <= len(lines)
        assert lines[chunk["start_line"] - 1].strip() == chunk["content"].splitlines()[0].strip()


def test_chunk_shape_matches_the_table():
    """code_chunks 테이블에 그대로 넣으므로 열 이름이 어긋나면 안 된다."""
    chunk = chunk_file("repo.py", PYTHON)[0]
    assert set(chunk) == {"path", "language", "start_line", "end_line", "content"}
