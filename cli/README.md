# `harness` — Workspace Harness CLI

The single binary that backs every `make` target and every agent hook in the harness.

## Install (development)

```
pip install -e cli/
```

## Install (inside the dev container)

The `env/Dockerfile` `COPY`s `cli/` and `pip install`s it. Rebuild the dev image whenever the CLI changes:

```
docker build -f env/Dockerfile -t harness-dev .
```

## Subcommands

| Command | Status | Purpose |
| --- | --- | --- |
| `harness bootstrap` | working | Regenerate `env/Dockerfile` + `env/docker-compose.yml` from `harness.yml`. |
| `harness ctx add PATH` | working | Scaffold a context doc with frontmatter. |
| `harness ctx validate` | working | Validate frontmatter and index freshness. |
| `harness ctx search QUERY` | stub (M2) | FTS5-backed search. |
| `harness ctx reindex` | stub (M2) | Rebuild `context/index.json`. |
| `harness policy check` | working | Check a command (or staged paths) against `agent/policies.yaml`. |
| `harness exec TARGET` | working | Run the per-project command (build/test/lint/run) from `harness.yml`. |
| `harness report` | stub (M4) | Aggregate `.harness/reports/` into `report.md`. |
| `harness status` | working | Print harness state. |

Each subcommand exits non-zero on failure and prints structured output where it makes sense.

## Layout

```
cli/
  pyproject.toml
  src/harness/
    cli.py          # Click root + command groups
    config.py       # load harness.yml + .harness/state.json
    bootstrap.py    # render Jinja2 templates → env/
    ctx.py          # context library commands
    policy.py       # policy load + check
    exec_.py        # harness exec ...
    report.py       # report aggregation
    status.py       # harness status
    templates/
      Dockerfile.j2
      docker-compose.yml.j2
```
