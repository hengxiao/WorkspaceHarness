"""Base extractor and tree-sitter integration for code structure extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class SymbolDef:
    name: str
    kind: str           # function, class, method, struct, macro, ...
    line_start: int
    line_end: int
    col_start: int = 0
    col_end: int = 0
    parent_idx: int | None = None   # index into the symbols list
    signature: str | None = None
    docstring: str | None = None
    visibility: str | None = None
    is_export: bool = False
    bases: list[str] = field(default_factory=list)  # for classes


@dataclass
class RefDef:
    name: str
    kind: str | None    # call, attribute, type, name
    line: int
    col: int = 0
    scope_idx: int | None = None    # index of enclosing symbol


@dataclass
class ImportDef:
    module: str
    names: list[str] | None = None  # ["foo", "bar"] or None for bare import
    alias: str | None = None
    line: int = 0
    is_reexport: bool = False


@dataclass
class ExtractionResult:
    symbols: list[SymbolDef] = field(default_factory=list)
    refs: list[RefDef] = field(default_factory=list)
    imports: list[ImportDef] = field(default_factory=list)


class Extractor(Protocol):
    def extract(self, source: bytes, path: str) -> ExtractionResult: ...


_EXTRACTORS: dict[str, Extractor] = {}


def register_extractor(language: str, extractor: Extractor) -> None:
    _EXTRACTORS[language] = extractor


def get_extractor(language: str) -> Extractor | None:
    return _EXTRACTORS.get(language)


def extract_file(source: bytes, path: str, language: str) -> ExtractionResult:
    ext = get_extractor(language)
    if ext is None:
        return ExtractionResult()
    return ext.extract(source, path)


def _try_load_tree_sitter() -> bool:
    """Attempt to import tree-sitter. Returns True if available."""
    try:
        import tree_sitter  # noqa: F401
        return True
    except ImportError:
        return False


HAS_TREE_SITTER = _try_load_tree_sitter()
