---
title: xz — overview
tags: [upstream, overview, c, autotools, cmake, compression]
summary: XZ Utils — general-purpose data-compression library (liblzma) plus command-line tools for the .xz file format. C project with both Autotools and CMake build systems. Extensive test suite; mature multi-platform CI.
updated: 2026-04-15
source: derived
project: xz
project_ref: ebb0e678
---

# xz

## Purpose

XZ Utils provides a general-purpose data-compression library (`liblzma`) and the `xz` command-line tool. The native format is `.xz`; it also supports legacy `.lzma`. The primary filter is LZMA2. `liblzma`'s API is intentionally similar to zlib to ease adoption.

## Language & Toolchain

- **Language:** C (C99)
- **Build systems:** GNU Autotools (primary) *and* CMake (secondary, kept in sync)
- **Bootstrap:** `./autogen.sh` generates the `configure` script
- **i18n:** po4a / autopoint / gettext
- **Docs:** doxygen
- **Standards:** portable across Linux, macOS, BSDs (Free/Net/Open/Dragonfly), Haiku, Solaris, Windows (MSVC, MSYS2), DOS

## How it's built

Two interchangeable paths:

**Autotools (primary):**
```
./autogen.sh              # generate configure (needs autoconf/automake/libtool/autopoint)
./configure               # configure the build
make -j$(nproc)           # build
sudo make install         # install (optional)
```

**CMake:**
```
cmake -S . -B build
cmake --build build -j$(nproc)
```

Required apt packages (Ubuntu):
- `build-essential autoconf automake libtool pkg-config`
- `po4a autopoint gettext doxygen`
- `cmake` (for the CMake path)
- Optional: `musl-tools valgrind gcc-multilib`

The repo also provides a CI orchestration script at `build-aux/ci_build.bash` that wraps both build systems with flags for sanitizers, 32-bit builds, and feature subsets (encoders/decoders/threads/bcj/delta).

## How it's tested

- **Framework:** AutoTest-style C tests built with Autotools + shell scripts
- **Invocation:** `make check -j$(nproc)` (or `ctest` under CMake)
- **C test binaries:** `tests/test_*.c` (lzip_decoder, block_header, check, index, vli, filter_flags/str, memlimit, microlzma, stream_flags, bcj_exact_size, compress, hardware)
- **Shell tests:** `tests/test_compress.sh`, `tests/test_files.sh`, `tests/test_scripts.sh`, `tests/test_suffix.sh`
- **Fuzzing:** `tests/ossfuzz/` — integrated with OSS-Fuzz
- **Coverage:** `tests/code_coverage.sh`

## Service dependencies

None. Standalone C library and CLI. No database, no network services.

## CI footprint

Extensive multi-platform matrix:
- `ci.yml` — Linux (x86_64, arm64) + macOS × (autotools, cmake) with 32-bit, sanitizer, musl, and feature-subset variants
- Per-OS workflows: `freebsd.yml`, `netbsd.yml`, `openbsd.yml`, `dragonflybsd.yml`, `solaris.yml`, `haiku.yml`
- `msvc.yml`, `msys2.yml` — Windows
- `coverity.yml` — static analysis
- `cifuzz.yml` — OSS-Fuzz integration

The harness will run the primary Linux/Autotools path. Other platform variants are out of scope.

## Notable directories

```
src/          — sources (liblzma, xz, xzdec, scripts, common)
tests/        — test binaries and shell scripts
lib/          — vendored support code (getopt_long)
doc/          — reference documentation
po/ po4a/     — translations
m4/           — autotools macros
cmake/        — CMake helpers
build-aux/    — build scripts including ci_build.bash
debug/        — debugging tools
extra/        — extra utilities (scripts for format, decoders)
windows/      — Windows-specific scripts
```

## Open questions

- Which build system variant (autotools vs cmake) is preferred for the default harness commands? *Defaulting to autotools since it's the primary.*
- Should the harness run the full CI matrix (sanitizers, 32-bit, musl) or just the baseline build? *Defaulting to baseline; adding a matrix is future work.*
- No code linter is configured (normal for this codebase). clang-format exists upstream but is not enforced.
