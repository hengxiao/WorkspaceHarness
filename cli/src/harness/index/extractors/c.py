"""C/C++ symbol extractor — regex-based.

Extracts function definitions, struct/enum/typedef declarations,
#define macros, and #include directives from C/C++ source files.
"""

from __future__ import annotations

import re
from ..extractor import ExtractionResult, Extractor, ImportDef, RefDef, SymbolDef, register_extractor

_INCLUDE_RE = re.compile(
    r'^[ \t]*#\s*include\s+[<"]([^>"]+)[>"]', re.MULTILINE
)

_DEFINE_RE = re.compile(
    r"^[ \t]*#\s*define\s+(?P<name>[A-Za-z_]\w*)"
    r"(?:\((?P<params>[^)]*)\))?",
    re.MULTILINE,
)

_FUNC_RE = re.compile(
    r"^(?P<ret>[\w\s*]+?)\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*"
    r"\((?P<params>[^)]*)\)\s*\{",
    re.MULTILINE,
)

_STRUCT_RE = re.compile(
    r"^(?:typedef\s+)?(?P<keyword>struct|union|enum)\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*\{",
    re.MULTILINE,
)

_TYPEDEF_RE = re.compile(
    r"^typedef\s+(?P<body>.+?)\s+(?P<name>[A-Za-z_]\w*)\s*;",
    re.MULTILINE,
)

_CALL_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")

_C_KEYWORDS = frozenset({
    "if", "else", "for", "while", "do", "switch", "case", "return",
    "sizeof", "typeof", "alignof", "static_assert", "typedef",
    "struct", "union", "enum", "goto", "break", "continue",
    "default", "register", "volatile", "extern", "static", "inline",
    "const", "void", "int", "char", "long", "short", "float", "double",
    "unsigned", "signed", "auto", "restrict", "bool",
})


class CExtractor:
    def extract(self, source: bytes, path: str) -> ExtractionResult:
        text = source.decode("utf-8", errors="replace")
        lines = text.split("\n")
        symbols: list[SymbolDef] = []
        refs: list[RefDef] = []
        imports: list[ImportDef] = []

        for m in _INCLUDE_RE.finditer(text):
            line = text[:m.start()].count("\n") + 1
            imports.append(ImportDef(module=m.group(1), line=line))

        defined_names: set[str] = set()

        for m in _DEFINE_RE.finditer(text):
            name = m.group("name")
            params = m.group("params")
            line = text[:m.start()].count("\n") + 1
            sig = f"#define {name}"
            if params is not None:
                sig += f"({params})"
            symbols.append(SymbolDef(
                name=name, kind="macro",
                line_start=line, line_end=line,
                signature=sig,
            ))
            defined_names.add(name)

        for m in _FUNC_RE.finditer(text):
            name = m.group("name")
            ret = m.group("ret").strip()
            params = m.group("params").strip()
            line_start = text[:m.start()].count("\n") + 1

            if name in _C_KEYWORDS:
                continue

            brace_pos = m.end() - 1
            line_end = _find_brace_end(text, brace_pos)
            if line_end == -1:
                line_end = line_start

            vis = "private" if "static" in ret else None
            sig = f"{ret} {name}({params})"

            doc = _extract_c_comment(lines, line_start - 1)

            symbols.append(SymbolDef(
                name=name, kind="function",
                line_start=line_start, line_end=line_end,
                signature=sig, docstring=doc, visibility=vis,
            ))
            defined_names.add(name)

        for m in _STRUCT_RE.finditer(text):
            keyword = m.group("keyword")
            name = m.group("name")
            line_start = text[:m.start()].count("\n") + 1
            brace_pos = m.end() - 1
            line_end = _find_brace_end(text, brace_pos)
            if line_end == -1:
                line_end = line_start
            symbols.append(SymbolDef(
                name=name, kind=keyword,
                line_start=line_start, line_end=line_end,
                signature=f"{keyword} {name}",
            ))
            defined_names.add(name)

        for m in _TYPEDEF_RE.finditer(text):
            name = m.group("name")
            if name in defined_names:
                continue
            line = text[:m.start()].count("\n") + 1
            symbols.append(SymbolDef(
                name=name, kind="typedef",
                line_start=line, line_end=line,
                signature=f"typedef ... {name}",
            ))
            defined_names.add(name)

        seen_calls: set[tuple[str, int]] = set()
        for m in _CALL_RE.finditer(text):
            name = m.group(1)
            if name in _C_KEYWORDS or name in defined_names:
                continue
            line = text[:m.start()].count("\n") + 1
            key = (name, line)
            if key in seen_calls:
                continue
            seen_calls.add(key)
            refs.append(RefDef(name=name, kind="call", line=line))

        return ExtractionResult(symbols=symbols, refs=refs, imports=imports)


def _find_brace_end(text: str, open_pos: int) -> int:
    """Find the line number of the closing brace matching the one at open_pos."""
    depth = 1
    i = open_pos + 1
    while i < len(text) and depth > 0:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    if depth == 0:
        return text[:i].count("\n") + 1
    return -1


def _extract_c_comment(lines: list[str], def_line_idx: int) -> str | None:
    """Extract a comment block immediately above a definition."""
    comments = []
    for i in range(def_line_idx - 1, max(def_line_idx - 20, -1), -1):
        stripped = lines[i].strip()
        if stripped.startswith("//"):
            comments.insert(0, stripped[2:].strip())
        elif stripped.endswith("*/"):
            block = []
            for j in range(i, max(i - 20, -1), -1):
                line = lines[j].strip()
                block.insert(0, line.lstrip("/*").rstrip("*/").strip())
                if line.startswith("/*"):
                    break
            return " ".join(b for b in block if b)[:500]
        elif stripped == "":
            continue
        else:
            break
    if comments:
        return " ".join(comments)[:500]
    return None


register_extractor("c", CExtractor())
register_extractor("cpp", CExtractor())
