---
title: "Code Structure Index — design spec"
status: draft
created: 2026-04-17
audience: [agent, human]
---

# Code Structure Index

A SQLite database at `.harness/code.db` that stores the static-analysis
structure of every wrapped project. Agents query it instead of scanning
files, turning O(n-files) lookups into O(1) SQL queries.

## 1. Motivation

Agents working on large codebases (emacs: ~15k files, pyyaml: ~200 files)
spend most of their context window budget on exploration — grepping for
definitions, tracing call chains, figuring out which file owns a concept.
This is:

- **Slow:** each grep is a subprocess + output parse.
- **Noisy:** results include irrelevant matches (comments, strings, tests).
- **Context-hungry:** agents load raw file contents to answer structural
  questions that a pre-built index could answer in one row.

A structured index lets agents ask precise questions:

```
"What functions does src/lread.c define?"
"Which files import yaml._yaml?"
"Show the class hierarchy rooted at yaml.Dumper."
"What changed since the last index build?"
```

## 2. What We Extract

### 2.1 Universal (all languages)

| Fact | Source | Example |
|------|--------|---------|
| **File inventory** | filesystem walk | path, size, last-modified, sha256 |
| **Language classification** | extension + shebang | `.py` → python, `.c` → c |
| **Symbol definitions** | tree-sitter parse | function, class, struct, method, macro, type |
| **Symbol references** | tree-sitter parse | calls, attribute access, name usage |
| **Import/include graph** | tree-sitter parse | `import yaml`, `#include "config.h"` |
| **Documentation** | tree-sitter parse | docstrings, comment blocks attached to symbols |
| **Scope nesting** | tree-sitter parse | module → class → method → inner function |

### 2.2 Language-specific enrichment

| Language | Extra facts |
|----------|-------------|
| **Python** | decorators, `__all__` exports, type annotations, `setup.py` entry_points |
| **C** | `#define` macros, typedef chains, `extern` declarations, header guard symbols |
| **JavaScript/TypeScript** | `export`/`export default`, JSX component names, `package.json` exports map |
| **Rust** | trait implementations, `pub` visibility, `mod` tree, derive macros |
| **Go** | interface satisfaction (type + method set), package-level exports (capitalized) |
| **Emacs Lisp** | `defun`, `defvar`, `defcustom`, `provide`/`require`, autoload cookies |

### 2.3 Relationship types

| Relationship | Direction | Example |
|-------------|-----------|---------|
| `defines` | file → symbol | `src/lread.c` defines `Fread()` |
| `references` | file → symbol | `src/eval.c` references `Fread` |
| `imports` | file → file/module | `yaml/__init__.py` imports `yaml._yaml` |
| `inherits` | class → class | `SafeDumper` inherits `Dumper` |
| `implements` | type → trait/interface | `Reader` implements `io.Reader` |
| `contains` | symbol → symbol | `class Loader` contains `def construct_yaml_map` |
| `calls` | symbol → symbol | `safe_load()` calls `load()` |
| `decorates` | decorator → function | `@staticmethod` decorates `from_dict` |
| `overrides` | method → method | `SafeLoader.construct_mapping` overrides `BaseLoader.construct_mapping` |

### 2.4 What we do NOT extract

- **Runtime behavior:** dynamic dispatch, monkey-patching, `eval()`/`exec()`,
  plugin loading. These are undecidable at static analysis time.
- **Values:** we don't track what constants equal, what config defaults are,
  or what data structures contain at runtime.
- **Metrics:** line counts, complexity scores, coverage — these belong in
  the report pipeline, not the structure index.
- **Comments (free-form):** only structured doc-comments attached to symbols
  are indexed. Random inline comments are noise.

## 3. Extraction Pipeline

### 3.1 Parser: tree-sitter

[Tree-sitter](https://tree-sitter.github.io/) is the extraction engine:

- **Fast:** incremental parsing; can re-parse a changed file in <1ms.
- **Multi-language:** grammar bindings exist for every language we detect.
- **Concrete syntax tree:** gives us exact byte ranges, so we can map
  symbols back to file:line for agent navigation.
- **Python bindings:** `tree-sitter` + `tree-sitter-languages` (or
  per-grammar wheels) integrate with the existing CLI.

### 3.2 Extraction flow

```
┌──────────────┐     ┌──────────────┐     ┌─────────────┐     ┌──────────────┐
│  git diff    │────▶│  file list   │────▶│  tree-sitter │────▶│  SQLite      │
│  (changed)   │     │  (to parse)  │     │  parse + walk│     │  upsert      │
└──────────────┘     └──────────────┘     └─────────────┘     └──────────────┘
       │                    │                    │                    │
  incremental          skip unchanged       extract symbols      REPLACE rows
  (full on first)      (hash match)         + relationships      for changed files
```

**Step 1 — Identify changed files.**
- First run: walk the entire project tree (respecting `.gitignore`).
- Subsequent runs: `git diff --name-only <last-indexed-ref>..HEAD` plus any
  unstaged changes from `git status --porcelain`.
- Deleted files: remove their rows from all tables.

**Step 2 — Filter and classify.**
- Skip binary files, vendored directories (`node_modules/`, `vendor/`,
  `.git/`), and files larger than a configurable threshold (default: 1MB).
- Classify language from file extension; fall back to shebang line.

**Step 3 — Parse and extract.**
- For each changed file, parse with tree-sitter using the appropriate
  grammar.
- Walk the CST with a language-specific visitor that emits `Symbol` and
  `Reference` records.
- Extract imports as `Import` records.
- Attach doc-comments to their nearest symbol.

**Step 4 — Persist.**
- Delete all existing rows for the changed file (cascade to symbols,
  references, imports).
- Insert new rows in a single transaction.
- Update the file's `content_hash` so future runs can skip it.
- Record the current `HEAD` ref as the last-indexed commit.

### 3.3 Incremental indexing cost

| Scenario | Files parsed | Time (est.) |
|----------|-------------|-------------|
| First index of pyyaml (~200 files) | 200 | <2s |
| First index of emacs (~15k files) | 15,000 | ~30-60s |
| After editing 3 files | 3 | <100ms |
| After `git pull` with 50 changed files | 50 | <1s |

These estimates assume tree-sitter parsing only (no LLM calls, no network).

## 4. Database Schema

### 4.1 Core tables

```sql
-- Metadata
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- Stores: schema_version, last_indexed_ref, last_indexed_at, project_name

-- Files
CREATE TABLE files (
    id           INTEGER PRIMARY KEY,
    project      TEXT NOT NULL,           -- e.g. "emacs", "pyyaml"
    path         TEXT NOT NULL,           -- relative to project root
    language     TEXT,                    -- "python", "c", "elisp", ...
    size_bytes   INTEGER NOT NULL,
    content_hash TEXT NOT NULL,           -- sha256 of file content
    indexed_at   TEXT NOT NULL,           -- ISO timestamp
    UNIQUE(project, path)
);

-- Symbols (definitions)
CREATE TABLE symbols (
    id          INTEGER PRIMARY KEY,
    file_id     INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,            -- "safe_load", "Fread", "Loader"
    kind        TEXT NOT NULL,            -- "function", "class", "method", "macro", ...
    line_start  INTEGER NOT NULL,
    line_end    INTEGER NOT NULL,
    col_start   INTEGER NOT NULL,
    col_end     INTEGER NOT NULL,
    parent_id   INTEGER REFERENCES symbols(id) ON DELETE CASCADE,
    signature   TEXT,                     -- "def safe_load(stream, Loader=None)"
    docstring   TEXT,                     -- first doc-comment, truncated to 500 chars
    visibility  TEXT,                     -- "public", "private", "protected", NULL
    is_export   BOOLEAN DEFAULT FALSE
);

-- References (usages of symbols)
CREATE TABLE refs (
    id          INTEGER PRIMARY KEY,
    file_id     INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,            -- symbol name being referenced
    kind        TEXT,                     -- "call", "attribute", "type", "name"
    line        INTEGER NOT NULL,
    col         INTEGER NOT NULL,
    scope_id    INTEGER REFERENCES symbols(id) ON DELETE SET NULL
);

-- Import/include edges
CREATE TABLE imports (
    id          INTEGER PRIMARY KEY,
    file_id     INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    module      TEXT NOT NULL,            -- "yaml._yaml", "<config.h>", "lodash"
    names       TEXT,                     -- JSON array: ["safe_load", "dump"] or NULL for star
    alias       TEXT,                     -- "import numpy as np" → alias="np"
    line        INTEGER NOT NULL,
    is_reexport BOOLEAN DEFAULT FALSE     -- "export { x } from './y'"
);

-- Inheritance / implementation edges
CREATE TABLE type_edges (
    id          INTEGER PRIMARY KEY,
    child_id    INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    parent_name TEXT NOT NULL,            -- may be unresolved ("BaseLoader")
    parent_id   INTEGER REFERENCES symbols(id) ON DELETE SET NULL,
    kind        TEXT NOT NULL             -- "inherits", "implements", "mixes_in"
);
```

### 4.2 Full-text search

```sql
-- FTS5 virtual table over symbol names and docstrings
CREATE VIRTUAL TABLE symbols_fts USING fts5(
    name,
    docstring,
    signature,
    content=symbols,
    content_rowid=id
);

-- FTS5 over file paths for fast glob-like lookup
CREATE VIRTUAL TABLE files_fts USING fts5(
    path,
    content=files,
    content_rowid=id
);
```

### 4.3 Indexes for common query patterns

```sql
CREATE INDEX idx_symbols_file   ON symbols(file_id);
CREATE INDEX idx_symbols_name   ON symbols(name);
CREATE INDEX idx_symbols_kind   ON symbols(kind);
CREATE INDEX idx_symbols_parent ON symbols(parent_id);
CREATE INDEX idx_refs_file      ON refs(file_id);
CREATE INDEX idx_refs_name      ON refs(name);
CREATE INDEX idx_imports_file   ON imports(file_id);
CREATE INDEX idx_imports_module ON imports(module);
CREATE INDEX idx_files_project  ON files(project);
CREATE INDEX idx_files_language  ON files(project, language);
CREATE INDEX idx_type_edges_child  ON type_edges(child_id);
CREATE INDEX idx_type_edges_parent ON type_edges(parent_id);
```

### 4.4 Size estimates

| Project | Files | Symbols | Refs | DB size (est.) |
|---------|-------|---------|------|----------------|
| pyyaml | ~200 | ~2k | ~10k | ~2 MB |
| xz | ~400 | ~5k | ~30k | ~5 MB |
| emacs | ~15k | ~150k | ~1M | ~100 MB |

SQLite handles all of these comfortably. The DB is gitignored and
regenerated on demand.

## 5. Query Interface

### 5.1 CLI commands

```bash
# Rebuild the index (incremental by default)
harness ctx reindex [--full] [--project <name>]

# Search symbols by name (FTS5)
harness ctx search "safe_load"

# Lookup a specific symbol's definition
harness ctx symbol <name> [--kind function|class|...] [--project <name>]

# Show what a file defines
harness ctx file <path>

# Show the import graph for a file or module
harness ctx imports <path-or-module> [--reverse]

# Show the class/type hierarchy
harness ctx hierarchy <class-name> [--depth N]

# Show callers/callees of a function
harness ctx callers <function-name>
harness ctx callees <function-name>

# Diff the index against the working tree (what's stale?)
harness ctx stale
```

### 5.2 Programmatic API (for agents)

Agents calling the CLI get structured JSON output with `--json`:

```bash
harness ctx symbol safe_load --json
```

```json
[
  {
    "name": "safe_load",
    "kind": "function",
    "file": "yaml/__init__.py",
    "line_start": 125,
    "line_end": 142,
    "signature": "def safe_load(stream)",
    "docstring": "Parse the first YAML document in a stream...",
    "project": "pyyaml"
  }
]
```

For complex queries agents can also execute raw SQL:

```bash
harness ctx query "SELECT s.name, f.path FROM symbols s JOIN files f ON s.file_id = f.id WHERE s.kind = 'class' AND s.name LIKE '%Loader%'"
```

### 5.3 Common query patterns

**"Where is X defined?"**
```sql
SELECT f.path, s.line_start, s.signature
FROM symbols s JOIN files f ON s.file_id = f.id
WHERE s.name = 'safe_load';
```

**"What does this file export?"**
```sql
SELECT s.name, s.kind, s.signature
FROM symbols s JOIN files f ON s.file_id = f.id
WHERE f.path = 'yaml/__init__.py'
  AND s.parent_id IS NULL
  AND s.visibility != 'private';
```

**"Who calls this function?"**
```sql
SELECT f.path, r.line, scope.name AS caller
FROM refs r
JOIN files f ON r.file_id = f.id
LEFT JOIN symbols scope ON r.scope_id = scope.id
WHERE r.name = 'safe_load' AND r.kind = 'call';
```

**"Show the inheritance chain for SafeLoader."**
```sql
WITH RECURSIVE chain(id, name, depth) AS (
    SELECT id, name, 0 FROM symbols WHERE name = 'SafeLoader' AND kind = 'class'
    UNION ALL
    SELECT s.id, s.name, c.depth + 1
    FROM chain c
    JOIN type_edges te ON te.child_id = c.id
    JOIN symbols s ON s.id = te.parent_id
)
SELECT * FROM chain ORDER BY depth;
```

**"What files import this module?"**
```sql
SELECT f.path, i.names, i.line
FROM imports i JOIN files f ON i.file_id = f.id
WHERE i.module = 'yaml._yaml';
```

**"What changed since last index?"**
```sql
-- Files in the DB whose hash doesn't match the current file
SELECT path FROM files WHERE project = 'pyyaml'
EXCEPT
SELECT path FROM files WHERE content_hash = <current_hash>;
```

## 6. Applications

### 6.1 Agent context retrieval

**Before:** agent asks "what does `safe_load` do?", searches with grep,
gets 47 matches across tests/docs/source, loads 3-4 files to find the
definition, burns 2k tokens on exploration.

**After:** agent queries `harness ctx symbol safe_load --json`, gets the
exact file:line, signature, and docstring in one call. Total: ~100 tokens.

### 6.2 Targeted test discovery

Agent edits `yaml/constructor.py`. Which tests cover it?

```sql
-- Files that import the changed module
SELECT f.path FROM imports i
JOIN files f ON i.file_id = f.id
WHERE i.module LIKE 'yaml.constructor%'
  AND f.path LIKE 'test%';
```

Output: `test/lib/test_constructor.py` — agent runs that one file instead
of the entire suite.

### 6.3 Impact analysis before changes

Agent is asked to rename `BaseLoader.construct_yaml_map`. Before editing:

```sql
-- All symbols that override this method
SELECT f.path, s.name, s.line_start
FROM symbols s
JOIN files f ON s.file_id = f.id
WHERE s.name = 'construct_yaml_map'
  AND s.kind = 'method';

-- All call sites
SELECT f.path, r.line
FROM refs r JOIN files f ON r.file_id = f.id
WHERE r.name = 'construct_yaml_map' AND r.kind = 'call';
```

Agent now knows every file that needs updating — no grep, no risk of
missing a dynamic reference pattern.

### 6.4 Onboarding and exploration

New agent enters the harness and asks "give me an overview of pyyaml's
architecture."

```sql
-- Top-level modules (files with no parent directory beyond root)
SELECT f.path, COUNT(s.id) as symbol_count,
       GROUP_CONCAT(DISTINCT s.kind) as symbol_kinds
FROM files f
LEFT JOIN symbols s ON s.file_id = f.id AND s.parent_id IS NULL
WHERE f.project = 'pyyaml' AND f.language = 'python'
GROUP BY f.path ORDER BY symbol_count DESC;
```

Combined with the class hierarchy query, this produces a structural
overview without reading a single file.

### 6.5 Stale-context detection

After a `git pull`, the index can diff its stored hashes against the
working tree and report which context documents reference symbols that
moved or were deleted — automating the "is this doc still accurate?"
check.

### 6.6 Code navigation in agents

Agents can implement "go to definition" without IDE support:

```
User: "What does the `compose_node` method do in pyyaml?"
Agent: harness ctx symbol compose_node --kind method --json
→ file: yaml/composer.py, line: 62, signature: def compose_node(self, parent, index)
Agent: [reads yaml/composer.py:62-95]
→ gives informed answer with exact code context
```

### 6.7 Policy enforcement (future)

Agent policies can reference the index:

```yaml
agent:
  policies:
    - rule: "Do not modify functions with more than 5 callers without review"
      check: |
        harness ctx callers $FUNCTION --json | jq length
```

## 7. Integration Points

### 7.1 harness.yml configuration

```yaml
context:
  index:
    backend: sqlite       # only supported backend for now
    path: .harness/code.db
    exclude:
      - "test/data/**"    # fixture files, not real code
      - "vendor/**"
      - "node_modules/**"
    max_file_size: 1048576  # 1MB, skip larger files
    languages:              # override auto-detect per extension
      ".pyx": "python"
      ".el": "elisp"
```

### 7.2 CLI module structure

```
cli/src/harness/
├── index/
│   ├── __init__.py         # public API: reindex(), search(), query()
│   ├── db.py               # SQLite schema, migrations, connection management
│   ├── walker.py            # file discovery, git-diff, hash comparison
│   ├── extractor.py         # tree-sitter parsing, symbol/ref extraction
│   ├── extractors/          # language-specific visitors
│   │   ├── python.py
│   │   ├── c.py
│   │   ├── javascript.py
│   │   └── elisp.py
│   └── queries.py           # canned queries (symbol, callers, hierarchy, ...)
├── ctx.py                   # updated: cmd_reindex() calls index.reindex()
└── cli.py                   # updated: new ctx subcommands wired
```

### 7.3 Dependencies

New pip dependencies for the CLI:

```toml
[project]
dependencies = [
    # ... existing ...
    "tree-sitter>=0.23",
    "tree-sitter-python>=0.23",
    "tree-sitter-c>=0.23",
    "tree-sitter-javascript>=0.23",
]

[project.optional-dependencies]
# Language grammars that aren't needed by every harness
extra-grammars = [
    "tree-sitter-rust>=0.23",
    "tree-sitter-go>=0.23",
    "tree-sitter-java>=0.23",
    "tree-sitter-ruby>=0.23",
]
```

Core grammars (python, c, javascript) ship with the CLI. Others are
opt-in via `pip install harness[extra-grammars]` or by adding the
grammar package to the container's pip install.

### 7.4 Makefile integration

The existing `reindex` target already calls `harness ctx reindex`. No
Makefile changes needed — just replace the stub implementation.

### 7.5 Container integration

Tree-sitter compiles grammar .so files at install time. The Dockerfile
already has `build-essential`, so this works without changes. Grammars
are installed as pip packages; no system-level tree-sitter install needed.

## 8. Freshness Strategy

### 8.1 When to re-index

| Trigger | Scope | Automatic? |
|---------|-------|------------|
| `make reindex` / `harness ctx reindex` | incremental (changed files only) | manual |
| `harness ctx reindex --full` | full rebuild | manual |
| After `make deps` (post-hook) | incremental | optional (configurable) |
| Before `harness ctx search` if stale >N minutes | incremental | configurable |
| CI pipeline | full rebuild | yes (in `ci` target) |

### 8.2 Staleness detection

The `meta` table stores `last_indexed_ref` (the git commit SHA at index
time). On any query, the CLI compares this against `HEAD`:

- Same ref → index is fresh.
- Different ref → print a warning: "index is N commits behind HEAD,
  run `harness ctx reindex`."
- If `--auto-reindex` is set (or configured in harness.yml), reindex
  silently before the query.

### 8.3 Multi-project indexes

Each project is namespaced in the `files.project` column. A single
`.harness/code.db` file holds all projects. Cross-project queries
("who in project A calls a function defined in project B?") work
naturally through joins.

## 9. Future Extensions

These are explicitly **out of scope** for the initial implementation but
inform the schema design:

- **Semantic search via embeddings.** Add an `embeddings` table with
  vector columns (via `sqlite-vec` or export to Lance/Qdrant). Useful
  for "find functions similar to X" queries. The `docstring` and
  `signature` columns are the natural embedding inputs.
- **Call graph visualization.** Export the `refs` table as a DOT/Mermaid
  graph for architecture diagrams.
- **Change impact scoring.** Weight symbols by number of callers +
  inheritance depth to estimate blast radius of a change.
- **Cross-language FFI tracing.** Connect Python's `_yaml.pyx` calls
  to the C library's `yaml_parser_parse()` through Cython's declaration
  files.
- **LSP integration.** Expose the index as a lightweight LSP server so
  IDEs can use it for navigation alongside agents.

## 10. Implementation Plan

| Phase | Deliverable | Effort |
|-------|------------|--------|
| **P0** | Schema + db.py + walker.py (file inventory, hashing, incremental diff) | 1 session |
| **P1** | extractor.py + Python visitor (symbols, refs, imports for .py files) | 1 session |
| **P2** | C visitor (functions, structs, macros, includes) | 1 session |
| **P3** | FTS5 setup + `ctx search`, `ctx symbol`, `ctx file` CLI commands | 1 session |
| **P4** | `ctx callers`, `ctx imports --reverse`, `ctx hierarchy` | 1 session |
| **P5** | JavaScript visitor + Emacs Lisp visitor | 1 session |
| **P6** | Auto-reindex hooks, staleness warnings, CI integration | 1 session |
| **P7** | Tests for all of the above | throughout |

Each phase is independently useful — P0+P1 alone gives Python agents a
working symbol lookup.
