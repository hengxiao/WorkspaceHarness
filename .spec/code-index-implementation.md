---
title: "Code Structure Index — implementation reference"
status: current
created: 2026-04-17
audience: [agent, human]
---

# Code Structure Index — Implementation Reference

This document describes how the code index works as implemented, not as
designed. For the original design rationale and future roadmap, see
[code-index.md](code-index.md).

## 1. Architecture Overview

```
harness ctx reindex
        │
        ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  walker.py   │────▶│  extractor.py│────▶│  api.py      │────▶│  db.py       │
│  file        │     │  + language  │     │  reindex()   │     │  SQLite +    │
│  discovery   │     │  extractors  │     │  query API   │     │  FTS5        │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
```

**Database:** `.harness/code.db` (SQLite with WAL journal mode). Gitignored,
rebuilt on demand. Single file holds all projects.

**No external dependencies.** All extractors are regex-based. The
`tree_sitter` import is checked at startup (`HAS_TREE_SITTER` flag) but
not required — it exists as an upgrade path for future CST-based extractors.

## 2. Database Schema

### 2.1 Tables

#### `meta` — key-value store for index metadata

| Column | Type | Notes |
|--------|------|-------|
| `key` | TEXT PRIMARY KEY | e.g. `schema_version`, `last_indexed_at`, `last_indexed_ref:opencv` |
| `value` | TEXT NOT NULL | |

#### `files` — one row per indexed source file

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PRIMARY KEY | auto-increment |
| `project` | TEXT NOT NULL | e.g. `"opencv"`, `"pyyaml"` |
| `path` | TEXT NOT NULL | relative to project root, e.g. `modules/core/src/matrix.cpp` |
| `language` | TEXT | from extension mapping, e.g. `"cpp"`, `"python"` |
| `size_bytes` | INTEGER NOT NULL | |
| `content_hash` | TEXT NOT NULL | SHA-256 hex digest, used for incremental diff |
| `indexed_at` | TEXT NOT NULL | ISO-8601 timestamp |

Unique constraint: `(project, path)`.

#### `symbols` — definitions (functions, classes, methods, macros, etc.)

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PRIMARY KEY | |
| `file_id` | INTEGER NOT NULL | FK → files(id) ON DELETE CASCADE |
| `name` | TEXT NOT NULL | symbol name, e.g. `"GaussianBlur"` |
| `kind` | TEXT NOT NULL | `function`, `class`, `method`, `struct`, `enum`, `macro`, `typedef`, `namespace`, `interface`, `def` |
| `line_start` | INTEGER NOT NULL | 1-based |
| `line_end` | INTEGER NOT NULL | 1-based, end of the block/body |
| `col_start` | INTEGER DEFAULT 0 | reserved for column-level precision |
| `col_end` | INTEGER DEFAULT 0 | |
| `parent_id` | INTEGER | FK → symbols(id) ON DELETE CASCADE. Links methods to their class. |
| `signature` | TEXT | e.g. `"void GaussianBlur(InputArray src, ...)"` |
| `docstring` | TEXT | first doc-comment, truncated to 500 chars |
| `visibility` | TEXT | `"private"`, `"protected"`, or NULL (public) |
| `is_export` | BOOLEAN DEFAULT FALSE | marked for exported symbols (JS `export`, Java `public`) |

#### `refs` — references (call sites, usages)

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PRIMARY KEY | |
| `file_id` | INTEGER NOT NULL | FK → files(id) ON DELETE CASCADE |
| `name` | TEXT NOT NULL | name of the referenced symbol |
| `kind` | TEXT | currently always `"call"` |
| `line` | INTEGER NOT NULL | |
| `col` | INTEGER DEFAULT 0 | |
| `scope_id` | INTEGER | FK → symbols(id) ON DELETE SET NULL. The enclosing function/method. |

#### `imports` — import/include edges

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PRIMARY KEY | |
| `file_id` | INTEGER NOT NULL | FK → files(id) ON DELETE CASCADE |
| `module` | TEXT NOT NULL | e.g. `"opencv2/core.hpp"`, `"json"`, `"java.util.List"` |
| `names` | TEXT | JSON array of imported names, or NULL for bare imports |
| `alias` | TEXT | e.g. `"np"` for `import numpy as np` |
| `line` | INTEGER NOT NULL | |
| `is_reexport` | BOOLEAN DEFAULT FALSE | JS `export { x } from 'y'` |

#### `type_edges` — inheritance / implementation relationships

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PRIMARY KEY | |
| `child_id` | INTEGER NOT NULL | FK → symbols(id) ON DELETE CASCADE |
| `parent_name` | TEXT NOT NULL | name as written in source, e.g. `"BaseProcessor"` |
| `parent_id` | INTEGER | FK → symbols(id), resolved after indexing. NULL if unresolved. |
| `kind` | TEXT NOT NULL | currently always `"inherits"` |

### 2.2 Full-text search (FTS5)

```sql
CREATE VIRTUAL TABLE symbols_fts USING fts5(
    name, docstring, signature,
    content=symbols, content_rowid=id
);
```

Three triggers keep the FTS index in sync:
- `symbols_ai` (AFTER INSERT) — adds new symbol to FTS
- `symbols_ad` (AFTER DELETE) — removes from FTS
- `symbols_au` (AFTER UPDATE) — removes old + adds new

Queries use `symbols_fts MATCH ?` with FTS5 ranking.

### 2.3 Indexes

12 B-tree indexes for the common query patterns:

```
idx_symbols_file    ON symbols(file_id)
idx_symbols_name    ON symbols(name)
idx_symbols_kind    ON symbols(kind)
idx_symbols_parent  ON symbols(parent_id)
idx_refs_file       ON refs(file_id)
idx_refs_name       ON refs(name)
idx_imports_file    ON imports(file_id)
idx_imports_module  ON imports(module)
idx_files_project   ON files(project)
idx_files_lang      ON files(project, language)
idx_type_child      ON type_edges(child_id)
idx_type_parent     ON type_edges(parent_id)
```

### 2.4 Cascade behavior

All child tables use `ON DELETE CASCADE` from `files(id)`. Deleting a
file row automatically removes its symbols, refs, and imports. This is
the mechanism for incremental re-indexing: delete the old file row,
insert fresh data.

`type_edges.parent_id` uses `ON DELETE SET NULL` — if the parent class
is deleted, the edge remains with `parent_id=NULL` until the next
`_resolve_type_edges()` pass.

## 3. File Discovery (`walker.py`)

### 3.1 Language classification

Files are classified by extension. The `LANG_EXTENSIONS` dict maps 55+
extensions to 30 language names:

| Extensions | Language |
|-----------|----------|
| `.py`, `.pyx`, `.pxd`, `.pyi` | `python` |
| `.c`, `.h` | `c` |
| `.cc`, `.cpp`, `.cxx`, `.hpp` | `cpp` |
| `.js`, `.mjs`, `.cjs`, `.jsx` | `javascript` |
| `.ts`, `.tsx` | `typescript` |
| `.java` | `java` |
| `.kt` | `kotlin` |
| `.rs` | `rust` |
| `.go` | `go` |
| `.rb` | `ruby` |
| `.el` | `elisp` |
| `.sh`, `.bash` | `bash` |
| `.swift`, `.cs`, `.fs`, `.hs`, `.ml`, `.scala`, `.zig`, `.nim`, `.dart`, `.jl`, ... | (respective) |
| `.md`, `.json`, `.xml`, `.yaml`, `.toml`, `.sql` | data/markup formats |

Files with unmapped extensions are **skipped** — they produce no file
row in the index.

### 3.2 Directory exclusion

The following directories are skipped unconditionally:

```
.git  __pycache__  node_modules  .tox  .venv  venv
.mypy_cache  .ruff_cache  .pytest_cache  dist  build
.eggs  .hg  .svn
vendor  3rdparty  third_party  thirdparty  extern  deps  external
```

Any directory ending with `.egg-info` is also skipped.

### 3.3 File discovery strategy

1. **Try git first:** `git ls-files --cached --others --exclude-standard`
   (30s timeout). This respects `.gitignore` automatically and is the
   preferred path.
2. **Fallback:** `pathlib.rglob("*")` with manual SKIP_DIRS filtering.

Both paths apply:
- `max_file_size` filter (default 1 MB) — skip oversized files
- Zero-byte file skip
- Extension-based language filter (unknown extensions → skip)
- `exclude_patterns` via `fnmatch` (configurable in harness.yml)

### 3.4 Content hashing

SHA-256 digest of file contents, read in 64 KB chunks. Used for
incremental diff — if the hash matches the DB, the file is skipped.

### 3.5 Incremental diff (`diff_against_db`)

Compares discovered `FileEntry` list against the DB's `files` table for
the given project:

```
Input:  entries = [FileEntry(path, hash, ...)]
        DB state = {path: (file_id, content_hash), ...}

Output: new_files      — entries not in DB
        changed_files  — entries where hash differs
        deleted_ids    — file_ids in DB but not in entries
```

## 4. Extraction Framework (`extractor.py`)

### 4.1 Data model

Every extractor produces an `ExtractionResult` containing three lists:

- **`symbols: list[SymbolDef]`** — definitions found in the file
- **`refs: list[RefDef]`** — references (call sites) found in the file
- **`imports: list[ImportDef]`** — import/include statements

`SymbolDef.parent_idx` is an **index into the symbols list** (not a DB
ID). The API layer resolves these to DB IDs after insertion.

`SymbolDef.bases` is a list of parent class names (strings). The API
layer creates `type_edges` rows for each, with `parent_id=NULL` initially,
resolved in a separate pass.

### 4.2 Extractor registry

Language extractors register themselves at import time:

```python
register_extractor("python", PythonExtractor())
```

`extract_file(source, path, language)` looks up the registry and
dispatches. If no extractor is registered for a language, it returns
an empty `ExtractionResult` — the file still gets a row in `files` but
no symbols/refs/imports.

### 4.3 Currently registered extractors

| Language keys | Extractor class | File |
|-------------|----------------|------|
| `python` | `PythonExtractor` | `extractors/python.py` |
| `c`, `cpp` | `CExtractor` | `extractors/c.py` |
| `javascript`, `typescript` | `JavaScriptExtractor` | `extractors/javascript.py` |
| `java`, `kotlin` | `JavaExtractor` | `extractors/java.py` |

All other languages (rust, go, ruby, bash, etc.) get file-level inventory
only — no symbols, refs, or imports extracted.

## 5. Language Extractors

All extractors are regex-based. Each uses `re.MULTILINE` patterns that
match at the start of a line (`^`). This avoids matching inside strings
or comments in most cases, though false positives are possible.

### 5.1 Python extractor

**Symbols extracted:**

| Kind | Pattern | Example |
|------|---------|---------|
| `function` | `def name(` at top-level | `def main():` |
| `class` | `class Name(` | `class MyClass(Base):` |
| `method` | `def name(` inside a class | `def process(self):` |

Detection of `method` vs `function`: if the `def` is nested inside a
`class` (tracked via an indent stack), it's classified as `method`.

**Visibility:** `_name` → `"private"`, `__name` (non-dunder) → `"private"`.

**Docstrings:** Extracted from the first triple-quoted or single-quoted
string within 3 lines after a `def`/`class`. Multi-line docstrings are
joined and truncated to 500 chars.

**Class bases:** Parsed from the parenthesized list after `class Name(`.
Splits on commas, strips whitespace, excludes keyword arguments
(`metaclass=...`).

**Imports:** Matches `from X import Y` and `import X`. Extracts module
name, imported names list, and aliases.

**Call references:** Matches `name(` patterns. Filters Python keywords
(`if`, `for`, `return`, `lambda`, etc.). Deduplicates by `(name, line)`.
Determines the enclosing scope by finding the innermost symbol whose
line range contains the call.

**Block end detection:** Scans forward from a `def`/`class` line, looking
for the first non-blank, non-comment line with indent ≤ the definition's
indent. Caps at 500 lines forward.

### 5.2 C/C++ extractor

**Symbols extracted:**

| Kind | Pattern | Example |
|------|---------|---------|
| `macro` | `#define NAME` | `#define CV_EXPORTS __attribute__((visibility("default")))` |
| `function` | `ret name(params) {` | `int main(int argc, char **argv) {` |
| `method` | `ret Ns::name(params) {` | `void Mat::create(int rows, int cols) {` |
| `class` | `class [MACROS] Name [: bases] {` | `class CV_EXPORTS Mat : public MatExpr {` |
| `struct` | `struct Name {` | `struct Point { int x, y; };` |
| `enum` | `enum Name {` | `enum Color { RED, GREEN, BLUE };` |
| `union` | `union Name {` | `union Data { int i; float f; };` |
| `typedef` | `typedef ... Name;` | `typedef unsigned long size_t;` |
| `namespace` | `namespace Name {` | `namespace cv {` |

**C++ class regex details:** The key challenge is export macros between
`class` and the name:

```
class CV_EXPORTS_W Algorithm : public detail::AlgorithmImpl {
```

The regex `(?:(?!:)[A-Z_]\w*\s+)*` matches zero or more uppercase
identifiers (the macros) before the class name. The negative lookahead
`(?!:)` prevents matching the `:` that starts the base list.

**Inheritance parsing (`_parse_bases`):**

Input: `"public Bar, protected Baz<T>, virtual private Qux"`

1. Split on `,` → `["public Bar", "protected Baz<T>", "virtual private Qux"]`
2. Strip access specifiers (public/protected/private/virtual combos)
3. Strip template args (`Baz<T>` → `Baz`)
4. Result: `["Bar", "Baz", "Qux"]`

**Function vs method:** If the name contains `::` (e.g. `Mat::create`),
it's classified as `method` and the bare name after the last `::` is used.
Destructors (`~ClassName`) are handled by allowing `~` in the name pattern.

**Visibility:** `"private"` if `static` appears in the return type tokens.

**Noise ref filtering:** Two filter sets:
- `_C_KEYWORDS` (70+ entries): `if`, `for`, `void`, `int`, `class`, etc.
- `_NOISE_REFS` (50+ entries): STL methods (`push_back`, `size`, `empty`,
  `begin`, `end`, ...), casts (`static_cast`, `dynamic_cast`), C stdlib
  (`printf`, `malloc`, `memcpy`), boilerplate (`Copyright`, `defined`).

Single-character names are also filtered.

**Brace matching:** Simple depth counter starting from the `{` after the
declaration. Increments on `{`, decrements on `}`. Returns line number
when depth reaches 0. Does not account for braces inside strings or
comments — a known limitation.

**Comment extraction:** Looks up to 20 lines above a definition for `//`
line comments or `/* ... */` block comments. Returns the joined text,
truncated to 500 chars.

### 5.3 JavaScript/TypeScript extractor

**Symbols extracted:**

| Kind | Pattern | Example |
|------|---------|---------|
| `function` | `function name(` | `export async function fetchData(url) {` |
| `function` | `const name = (...) =>` | `const helper = (x) => x + 1` |
| `class` | `class Name [extends Base] {` | `class DataProcessor extends BaseProcessor {` |
| `method` | indented `name(params) {` | `transform(data) {` |

**TypeScript support:** The function regex includes optional generics
(`<T>`) and return type annotations (`): void`). The class regex handles
`implements` clauses. The same extractor handles both `.js` and `.ts`.

**Import patterns (3 styles):**

1. **ES modules:** `import { a, b } from 'x'`, `import X from 'x'`,
   `import * as X from 'x'`, `import type { T } from 'x'`
2. **CommonJS:** `const x = require('module')`
3. **Re-exports:** `export { a, b } from 'module'` (sets `is_reexport=True`)

**Export detection:** Checks if `"export"` appears in the text before
the `function`/`class` keyword on the same line.

**Noise filtering:** `_JS_NOISE` includes console methods, array methods,
string methods, test framework globals (describe, it, expect, jest),
and module system functions (require, define).

### 5.4 Java extractor

**Symbols extracted:**

| Kind | Pattern | Example |
|------|---------|---------|
| `class` | `class Name extends/implements {` | `public class MyService extends AbstractService implements Serializable {` |
| `interface` | `interface Name extends {` | `public interface Processor<T> extends Runnable {` |
| `enum` | `enum Name {` | `public enum Color { RED, GREEN, BLUE; }` |
| `record` | `record Name(...) {` | `public record Point(int x, int y) {` |
| `annotation` | `@interface Name {` | `public @interface MyAnnotation {` |
| `method` | `ret name(params) {` inside a type | `public void addItem(String item) {` |

**Modifier handling:** The type regex matches a sequence of optional
modifiers before the keyword: `public`, `private`, `protected`,
`abstract`, `final`, `static`, `sealed`, `non-sealed`, `strictfp`.

**Generics:** Both type and method regexes handle generic parameters
(`<T>`, `<K, V>`) in the declaration and return type.

**Inheritance/implementation:** `extends` and `implements` clauses are
parsed by `_parse_type_list()`, which strips generic args and extracts
bare type names.

**Visibility:** Derived from the modifier list in the matched text.
`"private"` or `"protected"` set explicitly; public sets `is_export=True`.

**Method scope:** `_find_type_scope()` finds the enclosing
class/interface/enum for a method by matching line ranges.

## 6. Indexing Flow (`api.py`)

### 6.1 `reindex()` — top-level orchestration

```
reindex(harness_root, project_name, project_dir, full=False, exclude=[], max_file_size=1MB)
```

**Step 1 — Connect and optionally clear.**
Open (or create) `.harness/code.db`. If `full=True`, delete all rows for
the project (cascade clears symbols/refs/imports).

**Step 2 — Discover files.**
Call `walk_project()` to get `list[FileEntry]`. Then `diff_against_db()`
to compute new, changed, and deleted file lists.

**Step 3 — Delete removed files.**
For each deleted file ID, call `clear_file()` (cascade delete).

**Step 4 — Index new and changed files.**
For each file in `new + changed`, call `_index_file()`.

**Step 5 — Resolve type edges.**
Run `_resolve_type_edges()` to link `parent_name` → `parent_id` for
inheritance edges within the same project.

**Step 6 — Update metadata.**
Set `last_indexed_at` (global and per-project) and attempt to record
the current git HEAD as `last_indexed_ref:{project}`.

**Step 7 — Commit and return stats.**
Single transaction commit. Count total files, symbols, refs. Return
summary dict.

### 6.2 `_index_file()` — per-file processing

```
_index_file(conn, project, entry: FileEntry, now: str)
```

1. Delete any existing file row for `(project, path)` — cascade removes
   old symbols/refs/imports.
2. Insert new `files` row, capture `file_id`.
3. Read file bytes. If read fails, return (file row exists but empty).
4. Call `extract_file(source, path, language)` → `ExtractionResult`.
5. If empty result, return.
6. Insert symbols with parent_id resolution:
   - Build `sym_id_map: dict[int, int]` mapping extraction-time indices
     to DB IDs.
   - For each symbol, resolve `parent_idx` via the map, insert, record
     the new DB ID.
   - For each base in `symbol.bases`, insert a `type_edges` row with
     `parent_id=NULL`.
7. Insert refs, resolving `scope_idx` via the map.
8. Insert imports, serializing `names` list as JSON.

### 6.3 `_resolve_type_edges()` — post-indexing pass

After all files are indexed, run a single UPDATE:

```sql
UPDATE type_edges SET parent_id = (
    SELECT s.id FROM symbols s
    JOIN files f ON s.file_id = f.id
    WHERE f.project = ? AND s.name = type_edges.parent_name AND s.kind = 'class'
    LIMIT 1
)
WHERE parent_id IS NULL
  AND child_id IN (SELECT s.id FROM symbols s JOIN files f ON s.file_id = f.id WHERE f.project = ?)
```

This resolves `parent_name` to `parent_id` for all inheritance edges
within the same project where the parent class was found. Cross-project
or unresolved parents remain `NULL`.

## 7. Query API

All query functions open a fresh connection, execute, and close. They
return `list[dict]` (from `sqlite3.Row`).

### 7.1 `search_symbols(root, query, project=None, kind=None, limit=20)`

FTS5 full-text search across symbol name, docstring, and signature.

```sql
SELECT ... FROM symbols_fts fts
JOIN symbols s ON s.id = fts.rowid
JOIN files f ON s.file_id = f.id
WHERE symbols_fts MATCH ?
[AND f.project = ?] [AND s.kind = ?]
ORDER BY rank LIMIT ?
```

### 7.2 `lookup_symbol(root, name, project=None, kind=None)`

Exact name match:

```sql
SELECT ... FROM symbols s JOIN files f ON s.file_id = f.id
WHERE s.name = ?
[AND f.project = ?] [AND s.kind = ?]
```

### 7.3 `file_symbols(root, path, project=None)`

Top-level symbols in a file (excludes nested methods):

```sql
SELECT ... FROM symbols s JOIN files f ON s.file_id = f.id
WHERE f.path = ? AND s.parent_id IS NULL
ORDER BY s.line_start
```

### 7.4 `callers_of(root, name, project=None)`

Reverse call graph — find all references to a symbol:

```sql
SELECT f.path, r.line, r.kind,
       scope.name AS scope_name, scope.kind AS scope_kind
FROM refs r
JOIN files f ON r.file_id = f.id
LEFT JOIN symbols scope ON r.scope_id = scope.id
WHERE r.name = ?
ORDER BY f.path, r.line
```

### 7.5 `import_graph(root, module, project=None, reverse=False)`

- **Forward** (`reverse=False`): imports from files matching `path LIKE %module%`
- **Reverse** (`reverse=True`): files that import `module LIKE %module%`

### 7.6 `type_hierarchy(root, class_name, project=None, depth=10)`

Recursive CTE walking inheritance:

```sql
WITH RECURSIVE chain(id, name, kind, path, depth) AS (
    SELECT s.id, s.name, s.kind, f.path, 0
    FROM symbols s JOIN files f ON s.file_id = f.id
    WHERE s.name = ? AND s.kind = 'class'
  UNION ALL
    SELECT s2.id, s2.name, s2.kind, f2.path, c.depth + 1
    FROM chain c
    JOIN type_edges te ON te.child_id = c.id
    JOIN symbols s2 ON s2.id = te.parent_id
    JOIN files f2 ON s2.file_id = f2.id
    WHERE c.depth < ?
)
SELECT * FROM chain ORDER BY depth
```

### 7.7 `raw_query(root, sql)`

Pass-through SQL execution for custom queries. Returns `list[dict]`.

### 7.8 `index_stats(root)`

Returns row counts for all tables, per-project file counts, and
`last_indexed_at` timestamp.

## 8. CLI Commands

All commands are under the `harness ctx` group. Agent-facing commands
support `--json` for structured output.

| Command | Function | Purpose |
|---------|----------|---------|
| `ctx reindex [--full] [--project X]` | `cmd_reindex()` | Build/update index |
| `ctx search <query> [--json]` | `cmd_search()` | FTS5 symbol search |
| `ctx symbol <name> [--kind K] [--json]` | `cmd_symbol()` | Exact name lookup |
| `ctx file <path> [--json]` | `cmd_file()` | List symbols in a file |
| `ctx callers <name> [--json]` | `cmd_callers()` | Find call sites |
| `ctx imports <module> [--reverse] [--json]` | `cmd_imports()` | Import graph |
| `ctx hierarchy <class> [--json]` | `cmd_hierarchy()` | Inheritance tree |
| `ctx query <sql> [--json]` | `cmd_query()` | Raw SQL |
| `ctx stats` | `cmd_stats()` | Index summary |

`cmd_reindex()` loads `HarnessConfig` to discover projects and iterates
over each, calling `api.reindex()`. It prints a one-line summary per
project showing file/symbol/ref counts and deltas.

## 9. Integration Points

### 9.1 Initialization (Phase 6.5)

After `harness.yml` is written (Phase 6) and before seeding skills
(Phase 7), the initialization skill runs:

```
harness ctx reindex
```

This builds the initial index for all projects. The handoff (Phase 8)
includes code index stats.

### 9.2 Agent awareness (CLAUDE.md)

`skills/CLAUDE.md` documents the command table and instructs agents to
prefer index queries over raw grep for structural questions.

### 9.3 Makefile

The existing `reindex` target in `env/Makefile` calls `harness ctx reindex`.
No changes needed.

## 10. Known Limitations

1. **Regex vs. AST:** All extractors use regex, not a real parser. This
   means:
   - Symbols inside multi-line strings or comments can produce false
     positives.
   - Complex C++ templates (`template <template <typename> class C>`)
     may not parse correctly.
   - Python f-strings with braces can confuse the call regex.

2. **No cross-file resolution for refs:** `refs.name` is a bare string,
   not resolved to a specific `symbols.id`. The `callers_of()` query
   matches by name, which can return false positives if multiple symbols
   share a name.

3. **Brace matching doesn't skip strings/comments:** The `_find_brace_end`
   function counts literal `{` and `}` characters. A brace inside a string
   literal or comment will throw off the block-end calculation.

4. **No scope nesting for C/C++ refs:** The C extractor doesn't track
   `scope_id` on refs (unlike Python). All C refs have `scope_id=NULL`.

5. **Languages without extractors** (rust, go, ruby, etc.) get file-level
   inventory only — they appear in `files` but have no symbols, refs,
   or imports.

6. **Single-character names filtered:** Both C and JS extractors skip
   single-char call names to reduce noise, which means legitimate
   single-letter functions (rare) won't appear in refs.

7. **Type edge resolution is name-based:** `_resolve_type_edges()`
   matches `parent_name` to `symbols.name` within the same project. If
   two classes share a name, `LIMIT 1` picks arbitrarily. Cross-project
   inheritance is not resolved.
