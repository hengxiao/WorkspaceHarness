"""C# symbol extractor — regex-based.

Extracts class/interface/struct/enum/record declarations, method
definitions, using directives, and inheritance from C# source files.
"""

from __future__ import annotations

import re
from ..extractor import ExtractionResult, Extractor, ImportDef, RefDef, SymbolDef, register_extractor

_USING_RE = re.compile(
    r"^[ \t]*using\s+(?:static\s+)?(?P<module>[\w.]+)\s*;",
    re.MULTILINE,
)

_NAMESPACE_RE = re.compile(
    r"^[ \t]*namespace\s+(?P<name>[\w.]+)",
    re.MULTILINE,
)

_TYPE_RE = re.compile(
    r"^[ \t]*(?:(?:public|private|protected|internal|static|abstract|sealed|partial|readonly|new|required|file)\s+)*"
    r"(?P<keyword>class|interface|struct|enum|record)\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*"
    r"(?:<[^>]*>\s*)?"
    r"(?::\s*(?P<bases>[^{]+))?"
    r"\s*\{",
    re.MULTILINE,
)

_METHOD_RE = re.compile(
    r"^[ \t]+(?:(?:public|private|protected|internal|static|virtual|override|abstract|async|sealed|new|partial|required)\s+)*"
    r"(?P<ret>[\w.<>\[\]?,\s]+?)\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*"
    r"(?:<[^>]*>\s*)?"
    r"\((?P<params>[^)]*)\)\s*"
    r"(?:where\s+[^{]+)?"
    r"\{",
    re.MULTILINE,
)

_PROP_RE = re.compile(
    r"^[ \t]+(?:(?:public|private|protected|internal|static|virtual|override|abstract|required|new)\s+)*"
    r"(?P<type>[\w.<>\[\]?,]+)\s+"
    r"(?P<name>[A-Z]\w*)\s*"
    r"\{",
    re.MULTILINE,
)

_CALL_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")

_CS_KEYWORDS = frozenset({
    "if", "else", "for", "foreach", "while", "do", "switch", "case",
    "return", "try", "catch", "finally", "throw", "new", "this", "base",
    "class", "interface", "struct", "enum", "record", "namespace",
    "using", "public", "private", "protected", "internal", "static",
    "virtual", "override", "abstract", "sealed", "partial", "async",
    "await", "void", "int", "long", "short", "byte", "char", "float",
    "double", "decimal", "bool", "string", "object", "var", "dynamic",
    "true", "false", "null", "typeof", "sizeof", "nameof", "is", "as",
    "in", "out", "ref", "params", "where", "when", "get", "set",
    "value", "yield", "break", "continue", "default", "lock",
    "checked", "unchecked", "fixed", "unsafe", "delegate", "event",
    "implicit", "explicit", "operator", "const", "readonly", "volatile",
    "extern", "stackalloc", "init", "required", "file", "global",
    "not", "and", "or", "with", "select", "from", "orderby",
    "group", "into", "join", "let", "on", "equals", "ascending",
    "descending",
})

_CS_NOISE = frozenset({
    "Add", "Remove", "Contains", "Count", "Any", "All", "First",
    "FirstOrDefault", "Single", "SingleOrDefault", "Where", "Select",
    "OrderBy", "OrderByDescending", "ThenBy", "GroupBy", "ToList",
    "ToArray", "ToDictionary", "ForEach", "Concat", "Aggregate",
    "ToString", "GetType", "Equals", "GetHashCode", "ReferenceEquals",
    "Dispose", "Configure", "AddScoped", "AddSingleton", "AddTransient",
    "GetRequiredService", "GetService",
    "Assert", "Equal", "NotNull", "Null", "True", "False", "Throws",
    "ThrowsAsync", "IsType", "NotEmpty", "Empty", "Contains",
    "Substitute", "Received", "DidNotReceive", "Returns", "ReturnsForAnyArgs",
    "Arg",
    "LogWarning", "LogError", "LogInformation", "LogDebug",
    "Ok", "NotFound", "BadRequest", "Unauthorized", "Forbid",
    "Task", "Run", "WhenAll", "WhenAny", "FromResult", "CompletedTask",
    "Delay", "ContinueWith",
    "Map", "MapGet", "MapPost", "MapPut", "MapDelete",
})


def _parse_bases(raw: str) -> list[str]:
    result = []
    for part in raw.split(","):
        name = part.strip().split("<")[0].strip()
        if name and name[0].isalpha() and name not in ("where",):
            result.append(name)
    return result


class CSharpExtractor:
    def extract(self, source: bytes, path: str) -> ExtractionResult:
        text = source.decode("utf-8", errors="replace")
        symbols: list[SymbolDef] = []
        refs: list[RefDef] = []
        imports: list[ImportDef] = []

        for m in _USING_RE.finditer(text):
            module = m.group("module")
            line = text[:m.start()].count("\n") + 1
            imports.append(ImportDef(module=module, line=line))

        for m in _NAMESPACE_RE.finditer(text):
            name = m.group("name")
            line = text[:m.start()].count("\n") + 1
            symbols.append(SymbolDef(
                name=name, kind="namespace",
                line_start=line, line_end=line,
                signature=f"namespace {name}",
            ))

        type_names: set[str] = set()

        for m in _TYPE_RE.finditer(text):
            keyword = m.group("keyword")
            name = m.group("name")
            bases_raw = m.group("bases")
            line_start = text[:m.start()].count("\n") + 1
            brace_pos = m.end() - 1
            line_end = _find_brace_end(text, brace_pos)

            bases = _parse_bases(bases_raw) if bases_raw else []
            prefix = text[m.start():m.end()].split(keyword)[0]
            vis = "private" if "private" in prefix else ("protected" if "protected" in prefix else None)
            is_export = "public" in prefix

            sig = f"{keyword} {name}"
            if bases_raw:
                sig += f" : {bases_raw.strip()}"
            if len(sig) > 200:
                sig = sig[:200] + "..."

            doc = _extract_xml_doc(text, line_start)

            symbols.append(SymbolDef(
                name=name, kind=keyword,
                line_start=line_start, line_end=line_end,
                signature=sig, docstring=doc,
                visibility=vis, is_export=is_export, bases=bases,
            ))
            type_names.add(name)

        for m in _METHOD_RE.finditer(text):
            name = m.group("name")
            ret = (m.group("ret") or "").strip()
            params = m.group("params").strip()
            if name in _CS_KEYWORDS or name in type_names or not ret:
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

            sig = f"{ret} {name}({params})"
            if len(sig) > 200:
                sig = sig[:200] + "..."

            doc = _extract_xml_doc(text, line_start)

            symbols.append(SymbolDef(
                name=name, kind="method",
                line_start=line_start, line_end=line_end,
                signature=sig, docstring=doc,
                visibility=vis, parent_idx=parent_idx,
                is_export="public" in line_text,
            ))

        defined = {s.name for s in symbols}
        seen: set[tuple[str, int]] = set()
        for m in _CALL_RE.finditer(text):
            name = m.group(1)
            if name in _CS_KEYWORDS or name in _CS_NOISE or name in defined:
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
        if s.kind in ("class", "interface", "struct", "record"):
            if s.line_start <= line <= s.line_end:
                return i
    return None


def _extract_xml_doc(text: str, def_line: int) -> str | None:
    """Extract XML doc comment (/// lines) above a definition."""
    lines = text.split("\n")
    comments = []
    for i in range(def_line - 2, max(def_line - 15, -1), -1):
        stripped = lines[i].strip()
        if stripped.startswith("///"):
            content = stripped[3:].strip()
            content = re.sub(r"<[^>]+>", "", content).strip()
            if content:
                comments.insert(0, content)
        elif stripped.startswith("[") or stripped.startswith("//"):
            continue
        elif stripped == "":
            continue
        else:
            break
    return " ".join(comments)[:500] if comments else None


register_extractor("csharp", CSharpExtractor())
