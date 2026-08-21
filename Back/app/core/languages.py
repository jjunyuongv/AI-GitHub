"""확장자 → tree-sitter 언어 이름 매핑.

수집(github_client)과 청킹(chunker)이 같은 판단을 해야 한다 —
수집이 가져온 파일을 청킹이 파싱하지 못하면 임베딩할 게 없고,
청킹이 아는 언어를 수집이 버리면 애초에 검색되지 않는다.
그래서 "이 파일이 소스인가"의 기준을 이 표 하나로 둔다.

값은 tree_sitter_language_pack.get_parser() 가 받는 이름이다.
"""

EXTENSION_TO_LANGUAGE = {
    ".py": "python",
    ".java": "java",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".swift": "swift",
    ".scala": "scala",
    ".sh": "bash",
    ".bash": "bash",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".vue": "vue",
    ".dart": "dart",
    ".lua": "lua",
    ".r": "r",
    ".ex": "elixir",
    ".exs": "elixir",
    ".hs": "haskell",
    ".clj": "clojure",
    ".yaml": "yaml",
    ".yml": "yaml",
}


def language_for(path: str) -> str | None:
    """파일 경로의 tree-sitter 언어 이름. 소스가 아니면 None.

    확장자 판단은 소문자 기준이다 (.PY, .Java 같은 표기도 같은 파일로 본다).
    """
    _, _, ext = path.rpartition(".")
    return EXTENSION_TO_LANGUAGE.get(f".{ext.lower()}") if ext else None
