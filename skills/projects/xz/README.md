---
name: xz-skills
description: Project-specific skills for the XZ Utils C library and CLI.
audience: [agent]
project: xz
---

# xz

## What's special about this project

- **Two parallel build systems.** Autotools (primary, `./autogen.sh && ./configure && make`) and CMake (`cmake -S . -B build && cmake --build build`). Changes to `Makefile.am` usually need a corresponding change to `CMakeLists.txt` (and vice versa). CI tests both in a matrix.
- **Multi-platform portability is a core invariant.** The code is expected to build on Linux, macOS, Free/Net/Open/Dragonfly BSD, Haiku, Solaris, Windows (MSVC + MSYS2), and DOS. A change that breaks any of these is a regression.
- **Security-sensitive.** This codebase was the target of the XZ backdoor (CVE-2024-3094) in 2024. Contributions and PRs from new authors, build-script changes, and CI-script changes warrant extra scrutiny. Agent policies should require human review for anything touching `build-aux/`, `m4/`, autogen.sh, or configure.ac.
- **liblzma API stability.** `src/liblzma/api/lzma/` is the public API. Breaking changes require a major version bump and migration notes.

## Build and test

```
make -f env/Makefile deps   # ./autogen.sh --no-po4a && ./configure
make -f env/Makefile build  # make -j$(nproc)
make -f env/Makefile test   # make check -j$(nproc)
```

`deps` is one-time prep. `build` and `test` are iterative. The dev container persists so these are fast after the first run.

## Testing

- C unit tests under `tests/test_*.c` (built via autotools)
- Shell-level integration tests (`tests/test_*.sh`)
- Fuzz harnesses under `tests/ossfuzz/` (integrated with OSS-Fuzz upstream)
- Coverage via `tests/code_coverage.sh`

## Coding style

- C99, no C++ features
- 4-space indent, `{` on same line for functions, K&R-ish but see existing code
- Portable C — no GNU-isms, no glibc-only functions without autoconf checks
- Every new platform-specific branch needs a configure-time feature check

## Deployment

Releases are cut from `master` as source tarballs. Agents should never push to `master` or tag releases.
