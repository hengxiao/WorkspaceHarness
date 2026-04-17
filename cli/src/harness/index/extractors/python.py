"""Python symbol extractor — regex-based for zero-dep reliability.

Extracts function/class/method definitions, imports, and basic references
from Python source files. Works without tree-sitter; a tree-sitter upgrade
path can replace the regex visitor with a CST walker later.
"""

from __future__ import annotations

import re
from ..extractor import ExtractionResult, Extractor, ImportDef, RefDef, SymbolDef, register_extractor

_DEF_RE = re.compile(
    r"^(?P<indent>[ \t]*)"
    r"(?:(?P<async>async)\s+)?"
    r"(?P<keyword>def|class)\s+"
    r"(?P<name>[A-Za-z_]\w*)"
    r"(?P<rest>[^:]*)",
    re.MULTILINE,
)

_IMPORT_RE = re.compile(
    r"^(?P<indent>[ \t]*)"
    r"(?:from\s+(?P<from>[.\w]+)\s+import\s+(?P<names>[^#\n]+)"
    r"|import\s+(?P<module>[^#\n]+))",
    re.MULTILINE,
)

_DECORATOR_RE = re.compile(r"^[ \t]*@(\w[\w.]*)", re.MULTILINE)

_CALL_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")


class PythonExtractor:
    def extract(self, source: bytes, path: str) -> ExtractionResult:
        text = source.decode("utf-8", errors="replace")
        lines = text.split("\n")
        symbols: list[SymbolDef] = []
        refs: list[RefDef] = []
        imports: list[ImportDef] = []

        indent_stack: list[tuple[int, int]] = []  # (indent_level, symbol_idx)

        for m in _DEF_RE.finditer(text):
            indent = len(m.group("indent").replace("\t", "    "))
            keyword = m.group("keyword")
            name = m.group("name")
            rest = m.group("rest").strip()
            is_async = m.group("async") is not None
            line_start = text[:m.start()].count("\n") + 1

            line_end = _find_block_end(lines, line_start - 1, indent)

            while indent_stack and indent_stack[-1][0] >= indent:
                indent_stack.pop()
            parent_idx = indent_stack[-1][1] if indent_stack else None

            kind = keyword
            if keyword == "def" and parent_idx is not None:
                parent_kind = symbols[parent_idx].kind
                if parent_kind == "class":
                    kind = "method"

            sig = f"{'async ' if is_async else ''}{keyword} {name}"
            if rest:
                sig += rest.rstrip(":")

            vis = None
            if name.startswith("__") and not name.endswith("__"):
                vis = "private"
            elif name.startswith("_"):
                vis = "private"

            docstring = _extract_docstring(lines, line_start - 1)

            bases: list[str] = []
            if keyword == "class" and "(" in rest:
                base_str = rest.split("(", 1)[1].rsplit(")", 1)[0]
                bases = [b.strip() for b in base_str.split(",") if b.strip() and "=" not in b]

            sym = SymbolDef(
                name=name, kind=kind,
                line_start=line_start, line_end=line_end,
                parent_idx=parent_idx,
                signature=sig, docstring=docstring,
                visibility=vis, bases=bases,
            )
            idx = len(symbols)
            symbols.append(sym)
            indent_stack.append((indent, idx))

        for m in _IMPORT_RE.finditer(text):
            line = text[:m.start()].count("\n") + 1
            from_mod = m.group("from")
            if from_mod:
                raw_names = m.group("names").strip().rstrip("\\").strip()
                raw_names = raw_names.strip("()")
                name_list = [n.strip().split(" as ")[0].strip()
                             for n in raw_names.split(",") if n.strip()]
                alias_map = {}
                for n in raw_names.split(","):
                    n = n.strip()
                    if " as " in n:
                        orig, al = n.split(" as ", 1)
                        alias_map[orig.strip()] = al.strip()
                imports.append(ImportDef(
                    module=from_mod,
                    names=name_list if name_list else None,
                    line=line,
                ))
            else:
                raw = m.group("module").strip()
                for part in raw.split(","):
                    part = part.strip()
                    alias = None
                    if " as " in part:
                        part, alias = part.split(" as ", 1)
                        part = part.strip()
                        alias = alias.strip()
                    imports.append(ImportDef(
                        module=part, alias=alias, line=line,
                    ))

        seen_calls: set[tuple[str, int]] = set()
        for m in _CALL_RE.finditer(text):
            name = m.group(1)
            if name in ("def", "class", "if", "for", "while", "with",
                         "return", "yield", "assert", "print", "raise",
                         "except", "lambda", "not", "and", "or", "in",
                         "import", "from", "as", "True", "False", "None"):
                continue
            line = text[:m.start()].count("\n") + 1
            key = (name, line)
            if key in seen_calls:
                continue
            seen_calls.add(key)
            scope_idx = _find_scope(symbols, line)
            refs.append(RefDef(name=name, kind="call", line=line, scope_idx=scope_idx))

        return ExtractionResult(symbols=symbols, refs=refs, imports=imports)


def _find_block_end(lines: list[str], start_idx: int, def_indent: int) -> int:
    """Find the last line of a block starting at start_idx."""
    end = start_idx + 1
    for i in range(start_idx + 1, min(start_idx + 500, len(lines))):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("#"):
            continue
        line_indent = len(lines[i]) - len(lines[i].lstrip())
        line_indent = len(lines[i].expandtabs(4)) - len(lines[i].expandtabs(4).lstrip())
        if line_indent <= def_indent:
            break
        end = i + 1
    return end


def _extract_docstring(lines: list[str], def_line_idx: int) -> str | None:
    """Extract docstring from the line after a def/class."""
    for i in range(def_line_idx + 1, min(def_line_idx + 3, len(lines))):
        stripped = lines[i].strip()
        if not stripped:
            continue
        if stripped.startswith(('"""', "'''")):
            delim = stripped[:3]
            if stripped.count(delim) >= 2:
                return stripped[3:stripped.index(delim, 3)].strip()
            doc_lines = [stripped[3:]]
            for j in range(i + 1, min(i + 20, len(lines))):
                if delim in lines[j]:
                    doc_lines.append(lines[j][:lines[j].index(delim)].strip())
                    break
                doc_lines.append(lines[j].strip())
            doc = " ".join(l for l in doc_lines if l)
            return doc[:500] if doc else None
        if stripped.startswith(('"', "'")):
            return stripped.strip("\"'")[:500]
        break
    return None


def _find_scope(symbols: list[SymbolDef], line: int) -> int | None:
    """Find the innermost symbol that contains the given line."""
    best = None
    for i, s in enumerate(symbols):
        if s.line_start <= line <= s.line_end:
            if best is None or s.line_start > symbols[best].line_start:
                best = i
    return best


register_extractor("python", PythonExtractor())
