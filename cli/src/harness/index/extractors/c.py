"""C/C++ symbol extractor — regex-based.

Extracts function definitions, class/struct/enum/typedef declarations,
#define macros, #include directives, and C++ inheritance from C/C++ source.
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

# C/C++ function: matches `ret name(params) {` with optional qualifiers.
# Allows namespace::name and template-heavy return types.
_FUNC_RE = re.compile(
    r"^(?P<ret>[\w\s*&:<>,]+?)\s+"
    r"(?P<name>[A-Za-z_][\w:~]*)\s*"
    r"\((?P<params>[^)]*)\)\s*"
    r"(?:const\s*)?(?:override\s*)?(?:final\s*)?(?:noexcept(?:\([^)]*\))?\s*)?"
    r"\{",
    re.MULTILINE,
)

# struct/union/enum with optional name
_STRUCT_RE = re.compile(
    r"^(?:typedef\s+)?(?P<keyword>struct|union|enum)\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*\{",
    re.MULTILINE,
)

# C++ class: handles export macros between `class` and name, plus inheritance.
# Examples:
#   class Mat {
#   class CV_EXPORTS Mat {
#   class CV_EXPORTS_W Algorithm : public detail::AlgorithmImpl {
#   class Foo : public Bar, protected Baz {
_CLASS_RE = re.compile(
    r"^(?:template\s*<[^>]*>\s*)?"
    r"class\s+"
    r"(?:(?!:)[A-Z_]\w*\s+)*"       # optional export macros (uppercase)
    r"(?P<name>[A-Za-z_]\w*)\s*"
    r"(?:final\s*)?"
    r"(?::(?P<bases>[^{;]+))?"       # optional base list
    r"\s*\{",
    re.MULTILINE,
)

_TYPEDEF_RE = re.compile(
    r"^typedef\s+(?P<body>.+?)\s+(?P<name>[A-Za-z_]\w*)\s*;",
    re.MULTILINE,
)

# Namespace declarations
_NAMESPACE_RE = re.compile(
    r"^namespace\s+(?P<name>[A-Za-z_][\w:]*)\s*\{",
    re.MULTILINE,
)

_CALL_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")

_C_KEYWORDS = frozenset({
    "if", "else", "for", "while", "do", "switch", "case", "return",
    "sizeof", "typeof", "alignof", "static_assert", "typedef",
    "struct", "union", "enum", "class", "goto", "break", "continue",
    "default", "register", "volatile", "extern", "static", "inline",
    "const", "void", "int", "char", "long", "short", "float", "double",
    "unsigned", "signed", "auto", "restrict", "bool", "namespace",
    "template", "typename", "using", "virtual", "override", "final",
    "public", "private", "protected", "friend", "operator",
    "new", "delete", "throw", "try", "catch", "noexcept",
    "constexpr", "decltype", "nullptr", "true", "false",
})

# Common C++ STL / boilerplate names that generate noise refs
_NOISE_REFS = frozenset({
    "size", "empty", "push_back", "pop_back", "begin", "end",
    "front", "back", "clear", "erase", "find", "insert",
    "resize", "reserve", "data", "at", "swap", "assign",
    "emplace", "emplace_back", "emplace_front",
    "first", "second", "get", "set", "make_pair", "make_tuple",
    "move", "forward", "static_cast", "dynamic_cast", "reinterpret_cast",
    "const_cast", "std", "cv", "this",
    "Copyright", "copyright", "LICENSE", "license",
    "defined", "ifdef", "ifndef", "endif", "elif",
    "printf", "fprintf", "sprintf", "snprintf",
    "strlen", "strcmp", "strcpy", "strcat", "memcpy", "memset", "memmove",
    "malloc", "calloc", "realloc", "free",
    "open", "close", "read", "write",
})


def _parse_bases(bases_str: str) -> list[str]:
    """Parse C++ base class list: 'public Bar, protected Baz' → ['Bar', 'Baz']."""
    result = []
    for part in bases_str.split(","):
        part = part.strip()
        # Remove access specifier
        for prefix in ("public ", "protected ", "private ", "virtual public ",
                       "virtual protected ", "virtual private ", "virtual "):
            if part.startswith(prefix):
                part = part[len(prefix):].strip()
                break
        # Remove template args: Foo<T> → Foo
        if "<" in part:
            part = part[:part.index("<")].strip()
        # Remove namespace prefix for the base name (keep full for parent_name)
        name = part.strip()
        if name and name[0].isalpha():
            result.append(name)
    return result


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

            bare_name = name.split("::")[-1] if "::" in name else name
            if bare_name in _C_KEYWORDS:
                continue
            if bare_name.startswith("~"):
                bare_name = bare_name[1:]

            brace_pos = m.end() - 1
            line_end = _find_brace_end(text, brace_pos)
            if line_end == -1:
                line_end = line_start

            vis = "private" if "static" in ret.split() else None
            sig = f"{ret} {name}({params})"
            if len(sig) > 200:
                sig = sig[:200] + "..."

            doc = _extract_c_comment(lines, line_start - 1)

            kind = "method" if "::" in name else "function"

            symbols.append(SymbolDef(
                name=bare_name, kind=kind,
                line_start=line_start, line_end=line_end,
                signature=sig, docstring=doc, visibility=vis,
            ))
            defined_names.add(bare_name)

        for m in _CLASS_RE.finditer(text):
            name = m.group("name")
            bases_raw = m.group("bases")
            line_start = text[:m.start()].count("\n") + 1
            brace_pos = m.end() - 1
            line_end = _find_brace_end(text, brace_pos)
            if line_end == -1:
                line_end = line_start

            bases = _parse_bases(bases_raw) if bases_raw else []
            doc = _extract_c_comment(lines, line_start - 1)

            symbols.append(SymbolDef(
                name=name, kind="class",
                line_start=line_start, line_end=line_end,
                signature=f"class {name}",
                docstring=doc, bases=bases,
            ))
            defined_names.add(name)

        for m in _STRUCT_RE.finditer(text):
            keyword = m.group("keyword")
            name = m.group("name")
            if name in defined_names:
                continue
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

        for m in _NAMESPACE_RE.finditer(text):
            name = m.group("name")
            line_start = text[:m.start()].count("\n") + 1
            brace_pos = m.end() - 1
            line_end = _find_brace_end(text, brace_pos)
            if line_end == -1:
                line_end = line_start
            symbols.append(SymbolDef(
                name=name, kind="namespace",
                line_start=line_start, line_end=line_end,
                signature=f"namespace {name}",
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
            if name in _C_KEYWORDS or name in _NOISE_REFS or name in defined_names:
                continue
            if len(name) <= 1:
                continue
            line = text[:m.start()].count("\n") + 1
            key = (name, line)
            if key in seen_calls:
                continue
            seen_calls.add(key)
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
    if depth == 0:
        return text[:i].count("\n") + 1
    return -1


def _extract_c_comment(lines: list[str], def_line_idx: int) -> str | None:
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
