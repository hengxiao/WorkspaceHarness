---
title: Harness architecture — xz
tags: [architecture, single-project, c, library]
summary: Single-project harness wrapping the XZ Utils compression library. Standalone C codebase with no backend, no services, no external dependencies at runtime.
updated: 2026-04-15
source: internal
---

# Architecture

Single-project harness wrapping **xz** — XZ Utils, the reference implementation of the `.xz` compression format.

## Stack

- **C library + CLI**, no runtime services
- **GNU Autotools** (primary) with a parallel **CMake** build for Windows / cross-platform convenience
- **No backend**, **no database**, **no network stack**

## Dev workflow

1. `make -f env/Makefile up` — start dev container (ubuntu:24.04 + build toolchain)
2. `make -f env/Makefile deps` — `./autogen.sh && ./configure` (one-time prep)
3. `make -f env/Makefile build` — `make -j$(nproc)`
4. `make -f env/Makefile test` — `make check -j$(nproc)`

## Deployment

Not applicable — this is a library and CLI distributed via source tarball and OS package managers. Releases cut from `master`.
