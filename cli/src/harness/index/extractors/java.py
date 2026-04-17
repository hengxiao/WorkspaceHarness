"""Java symbol extractor — regex-based.

Extracts class/interface/enum declarations, method definitions,
import statements, and inheritance/implementation from Java source files.
"""

from __future__ import annotations

import re
from ..extractor import ExtractionResult, Extractor, ImportDef, RefDef, SymbolDef, register_extractor

# import statements
_IMPORT_RE = re.compile(
    r"^[ \t]*import\s+(?:static\s+)?(?P<module>[\w.]+(?:\.\*)?)\s*;",
    re.MULTILINE,
)

# package declaration
_PACKAGE_RE = re.compile(r"^[ \t]*package\s+(?P<name>[\w.]+)\s*;", re.MULTILINE)

# class / interface / enum / record / annotation
_TYPE_RE = re.compile(
    r"^[ \t]*(?:(?:public|private|protected|abstract|final|static|sealed|non-sealed|strictfp)\s+)*"
    r"(?P<keyword>class|interface|enum|record|@interface)\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*"
    r"(?:<[^>]*>\s*)?"                                  # generics
    r"(?:extends\s+(?P<extends>[\w.<>,\s]+?)\s*)?"
    r"(?:implements\s+(?P<implements>[\w.<>,\s]+?)\s*)?"
    r"(?:permits\s+[\w.<>,\s]+?\s*)?"
    r"\{",
    re.MULTILINE,
)

# method declarations
_METHOD_RE = re.compile(
    r"^[ \t]+(?:(?:public|private|protected|static|final|abstract|"
    r"synchronized|native|default|strictfp|override)\s+)*"
    r"(?:<[^>]*>\s*)?"                                  # generic return
    r"(?P<ret>[\w.<>\[\],?\s]+?)\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*"
    r"\((?P<params>[^)]*)\)\s*"
    r"(?:throws\s+[\w.<>,\s]+?\s*)?"
    r"\{",
    re.MULTILINE,
)

# constructor
_CTOR_RE = re.compile(
    r"^[ \t]+(?:(?:public|private|protected)\s+)?"
    r"(?P<name>[A-Z]\w*)\s*"
    r"\((?P<params>[^)]*)\)\s*"
    r"(?:throws\s+[\w.<>,\s]+?\s*)?"
    r"\{",
    re.MULTILINE,
)

# annotation declarations on their own line
_ANNOTATION_RE = re.compile(
    r"^[ \t]*@(?P<name>[A-Za-z_]\w*)",
    re.MULTILINE,
)

_CALL_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")

_JAVA_KEYWORDS = frozenset({
    "if", "else", "for", "while", "do", "switch", "case", "return",
    "try", "catch", "finally", "throw", "throws", "new", "this", "super",
    "class", "interface", "enum", "extends", "implements", "import",
    "package", "public", "private", "protected", "static", "final",
    "abstract", "synchronized", "volatile", "transient", "native",
    "strictfp", "void", "int", "long", "short", "byte", "char",
    "float", "double", "boolean", "true", "false", "null",
    "instanceof", "assert", "break", "continue", "default",
    "var", "record", "sealed", "permits", "yield",
})

_JAVA_NOISE = frozenset({
    "get", "set", "put", "add", "remove", "contains", "size", "isEmpty",
    "equals", "hashCode", "toString", "valueOf", "getClass",
    "iterator", "next", "hasNext", "close", "flush", "write", "read",
    "println", "print", "printf", "format", "append",
    "length", "charAt", "substring", "trim", "split", "replace",
    "asList", "of", "copyOf", "stream", "collect", "map", "filter",
    "Test", "Override", "Deprecated", "SuppressWarnings",
    "assertNotNull", "assertNull", "assertEquals", "assertTrue", "assertFalse",
})


def _parse_type_list(raw: str) -> list[str]:
    """Parse 'Foo, Bar<T>, Baz' → ['Foo', 'Bar', 'Baz']."""
    result = []
    for part in raw.split(","):
        name = part.strip().split("<")[0].strip()
        if name and name[0].isalpha():
            result.append(name)
    return result


class JavaExtractor:
    def extract(self, source: bytes, path: str) -> ExtractionResult:
        text = source.decode("utf-8", errors="replace")
        symbols: list[SymbolDef] = []
        refs: list[RefDef] = []
        imports: list[ImportDef] = []

        for m in _IMPORT_RE.finditer(text):
            module = m.group("module")
            line = text[:m.start()].count("\n") + 1
            imports.append(ImportDef(module=module, line=line))

        type_names: set[str] = set()

        for m in _TYPE_RE.finditer(text):
            keyword = m.group("keyword")
            if keyword == "@interface":
                keyword = "annotation"
            name = m.group("name")
            line_start = text[:m.start()].count("\n") + 1
            brace_pos = m.end() - 1
            line_end = _find_brace_end(text, brace_pos)

            bases: list[str] = []
            extends_raw = m.group("extends")
            if extends_raw:
                bases.extend(_parse_type_list(extends_raw))
            impl_raw = m.group("implements")
            if impl_raw:
                bases.extend(_parse_type_list(impl_raw))

            prefix = text[m.start():m.end()].split(keyword)[0].strip()
            vis = None
            if "private" in prefix:
                vis = "private"
            elif "protected" in prefix:
                vis = "protected"

            sig = f"{keyword} {name}"
            if extends_raw:
                sig += f" extends {extends_raw.strip()}"
            if impl_raw:
                sig += f" implements {impl_raw.strip()}"
            if len(sig) > 200:
                sig = sig[:200] + "..."

            symbols.append(SymbolDef(
                name=name, kind=keyword,
                line_start=line_start, line_end=line_end,
                signature=sig, visibility=vis,
                bases=bases, is_export="public" in prefix,
            ))
            type_names.add(name)

        for m in _METHOD_RE.finditer(text):
            name = m.group("name")
            ret = (m.group("ret") or "").strip()
            params = m.group("params").strip()
            if name in _JAVA_KEYWORDS or name in type_names or not ret:
                continue
            line_start = text[:m.start()].count("\n") + 1
            brace_pos = m.end() - 1
            line_end = _find_brace_end(text, brace_pos)
            parent_idx = _find_type_scope(symbols, line_start)

            line_text = text[m.start():m.end()]
            vis = None
            if "private" in line_text:
                vis = "private"
            elif "protected" in line_text:
                vis = "protected"

            sig = f"{ret} {name}({params})" if ret else f"{name}({params})"
            if len(sig) > 200:
                sig = sig[:200] + "..."

            symbols.append(SymbolDef(
                name=name, kind="method",
                line_start=line_start, line_end=line_end,
                signature=sig, visibility=vis,
                parent_idx=parent_idx,
                is_export="public" in line_text,
            ))

        defined = {s.name for s in symbols}
        seen: set[tuple[str, int]] = set()
        for m in _CALL_RE.finditer(text):
            name = m.group(1)
            if name in _JAVA_KEYWORDS or name in _JAVA_NOISE or name in defined:
                continue
            if len(name) <= 1:
                continue
            line = text[:m.start()].count("\n") + 1
            key = (name, line)
            if key not in seen:
                seen.add(key)
                refs.append(RefDef(name=name, kind="call", line=line))

        return ExtractionResult(symbols=symbols, refs=refs, imports=imports)


def _find_brace_end(text: str, open_pos: int) -> int:
    depth = 1
    i = open_pos + 1
    while i < len(text) and depth > 0:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    return text[:i].count("\n") + 1 if depth == 0 else open_pos


def _find_type_scope(symbols: list[SymbolDef], line: int) -> int | None:
    for i, s in enumerate(symbols):
        if s.kind in ("class", "interface", "enum", "record", "annotation"):
            if s.line_start <= line <= s.line_end:
                return i
    return None


register_extractor("java", JavaExtractor())
register_extractor("kotlin", JavaExtractor())
