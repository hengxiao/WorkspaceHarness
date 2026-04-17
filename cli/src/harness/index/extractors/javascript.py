"""JavaScript / TypeScript symbol extractor — regex-based.

Extracts function/class/method declarations, import/export statements,
and call references from JS/TS source files.
"""

from __future__ import annotations

import re
from ..extractor import ExtractionResult, Extractor, ImportDef, RefDef, SymbolDef, register_extractor

# function declarations (including async, generator)
_FUNC_RE = re.compile(
    r"^[ \t]*(?:export\s+)?(?:default\s+)?"
    r"(?P<async>async\s+)?"
    r"function\s*(?P<star>\*)?\s*"
    r"(?P<name>[A-Za-z_$][\w$]*)\s*"
    r"(?:<[^>]*>\s*)?"                    # optional generics
    r"\((?P<params>[^)]*)\)\s*"
    r"(?::\s*[\w<>[\]|&\s,]+\s*)?"        # optional TS return type
    r"\{",
    re.MULTILINE,
)

# class declarations
_CLASS_RE = re.compile(
    r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?"
    r"class\s+(?P<name>[A-Za-z_$][\w$]*)\s*"
    r"(?:extends\s+(?P<base>[A-Za-z_$][\w$.]*)(?:\s*<[^>]*>)?\s*)?"
    r"(?:implements\s+(?P<ifaces>[^{]+)\s*)?"
    r"\{",
    re.MULTILINE,
)

# methods inside classes / object literals
_METHOD_RE = re.compile(
    r"^[ \t]+(?:(?:static|async|get|set|public|private|protected|readonly|abstract|override)\s+)*"
    r"(?P<name>[A-Za-z_$][\w$]*)\s*"
    r"\((?P<params>[^)]*)\)\s*(?::\s*[\w<>[\]|&\s,]+\s*)?\{",
    re.MULTILINE,
)

# const/let/var arrow or function expression at top level
_ARROW_RE = re.compile(
    r"^[ \t]*(?:export\s+)?(?:const|let|var)\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)\s*"
    r"(?::\s*[\w<>[\]|&\s,]+\s*)?"
    r"=\s*(?:async\s+)?"
    r"(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>\s*",
    re.MULTILINE,
)

# ES module imports
_IMPORT_RE = re.compile(
    r"^[ \t]*import\s+"
    r"(?:(?:type\s+)?"
    r"(?:"
    r"\*\s+as\s+(?P<star>[A-Za-z_$][\w$]*)"                       # import * as X
    r"|\{(?P<named>[^}]+)\}"                                       # import { a, b }
    r"|(?P<default>[A-Za-z_$][\w$]*)(?:\s*,\s*\{(?P<named2>[^}]+)\})?"  # import X / import X, { a }
    r")"
    r"\s+from\s+)?"
    r"['\"](?P<module>[^'\"]+)['\"]",
    re.MULTILINE,
)

# require() calls
_REQUIRE_RE = re.compile(
    r"(?:const|let|var)\s+(?:\{[^}]+\}|[A-Za-z_$][\w$]*)\s*=\s*require\(['\"]([^'\"]+)['\"]\)",
)

# export { ... } from '...'
_REEXPORT_RE = re.compile(
    r"^[ \t]*export\s+\{(?P<names>[^}]+)\}\s+from\s+['\"](?P<module>[^'\"]+)['\"]",
    re.MULTILINE,
)

_CALL_RE = re.compile(r"\b([A-Za-z_$][\w$]*)\s*\(")

_JS_KEYWORDS = frozenset({
    "if", "else", "for", "while", "do", "switch", "case", "return",
    "typeof", "instanceof", "void", "delete", "throw", "try", "catch",
    "finally", "new", "this", "super", "class", "extends", "import",
    "export", "default", "from", "as", "const", "let", "var",
    "function", "async", "await", "yield", "break", "continue",
    "debugger", "with", "in", "of", "true", "false", "null", "undefined",
    "NaN", "Infinity",
})

_JS_NOISE = frozenset({
    "console", "log", "warn", "error", "info", "debug",
    "push", "pop", "shift", "unshift", "splice", "slice",
    "map", "filter", "reduce", "forEach", "find", "findIndex",
    "indexOf", "includes", "join", "split", "replace", "match",
    "keys", "values", "entries", "assign", "freeze",
    "stringify", "parse", "toString", "valueOf",
    "setTimeout", "setInterval", "clearTimeout", "clearInterval",
    "require", "define", "module", "exports",
    "describe", "it", "test", "expect", "beforeEach", "afterEach",
    "beforeAll", "afterAll", "jest", "assert",
})


class JavaScriptExtractor:
    def extract(self, source: bytes, path: str) -> ExtractionResult:
        text = source.decode("utf-8", errors="replace")
        lines = text.split("\n")
        symbols: list[SymbolDef] = []
        refs: list[RefDef] = []
        imports: list[ImportDef] = []

        for m in _FUNC_RE.finditer(text):
            name = m.group("name")
            params = m.group("params").strip()
            is_async = m.group("async") is not None
            is_gen = m.group("star") is not None
            line_start = text[:m.start()].count("\n") + 1
            brace_pos = m.end() - 1
            line_end = _find_brace_end(text, brace_pos)
            prefix = ("async " if is_async else "") + ("function* " if is_gen else "function ")
            is_export = "export" in text[m.start():m.start()+30].split("function")[0]
            symbols.append(SymbolDef(
                name=name, kind="function",
                line_start=line_start, line_end=line_end,
                signature=f"{prefix}{name}({params})",
                is_export=is_export,
            ))

        for m in _CLASS_RE.finditer(text):
            name = m.group("name")
            base = m.group("base")
            line_start = text[:m.start()].count("\n") + 1
            brace_pos = m.end() - 1
            line_end = _find_brace_end(text, brace_pos)
            bases = [base] if base else []
            ifaces_raw = m.group("ifaces")
            if ifaces_raw:
                for iface in ifaces_raw.split(","):
                    iface = iface.strip().split("<")[0].strip()
                    if iface:
                        bases.append(iface)
            is_export = "export" in text[m.start():m.start()+30].split("class")[0]
            symbols.append(SymbolDef(
                name=name, kind="class",
                line_start=line_start, line_end=line_end,
                signature=f"class {name}" + (f" extends {base}" if base else ""),
                bases=bases, is_export=is_export,
            ))

        for m in _METHOD_RE.finditer(text):
            name = m.group("name")
            params = m.group("params").strip()
            if name in _JS_KEYWORDS:
                continue
            line_start = text[:m.start()].count("\n") + 1
            brace_pos = m.end() - 1
            line_end = _find_brace_end(text, brace_pos)
            parent_idx = _find_class_scope(symbols, line_start)
            symbols.append(SymbolDef(
                name=name, kind="method",
                line_start=line_start, line_end=line_end,
                signature=f"{name}({params})",
                parent_idx=parent_idx,
            ))

        for m in _ARROW_RE.finditer(text):
            name = m.group("name")
            line = text[:m.start()].count("\n") + 1
            is_export = "export" in text[m.start():m.start()+20]
            symbols.append(SymbolDef(
                name=name, kind="function",
                line_start=line, line_end=line,
                signature=f"const {name} = (...) =>",
                is_export=is_export,
            ))

        for m in _IMPORT_RE.finditer(text):
            module = m.group("module")
            line = text[:m.start()].count("\n") + 1
            named = m.group("named") or m.group("named2")
            default_name = m.group("default")
            star_name = m.group("star")
            name_list = None
            alias = None
            if star_name:
                alias = star_name
            elif named:
                name_list = [n.strip().split(" as ")[0].strip()
                             for n in named.split(",") if n.strip()]
            if default_name:
                name_list = [default_name] + (name_list or [])
            imports.append(ImportDef(
                module=module, names=name_list, alias=alias, line=line,
            ))

        for m in _REQUIRE_RE.finditer(text):
            module = m.group(1)
            line = text[:m.start()].count("\n") + 1
            imports.append(ImportDef(module=module, line=line))

        for m in _REEXPORT_RE.finditer(text):
            module = m.group("module")
            names_raw = m.group("names")
            line = text[:m.start()].count("\n") + 1
            name_list = [n.strip().split(" as ")[0].strip()
                         for n in names_raw.split(",") if n.strip()]
            imports.append(ImportDef(
                module=module, names=name_list, line=line, is_reexport=True,
            ))

        defined = {s.name for s in symbols}
        seen: set[tuple[str, int]] = set()
        for m in _CALL_RE.finditer(text):
            name = m.group(1)
            if name in _JS_KEYWORDS or name in _JS_NOISE or name in defined:
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


def _find_class_scope(symbols: list[SymbolDef], line: int) -> int | None:
    for i, s in enumerate(symbols):
        if s.kind == "class" and s.line_start <= line <= s.line_end:
            return i
    return None


register_extractor("javascript", JavaScriptExtractor())
register_extractor("typescript", JavaScriptExtractor())
