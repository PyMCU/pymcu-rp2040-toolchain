# pymcu-rp2040-toolchain

Vendored **LLVM toolchain** for the [PyMCU](https://github.com/begeistert/pymcu)
RP2040 (ARM Cortex-M0+) backend.

The RP2040 backend lowers PyMCU's architecture-agnostic IR to **LLVM IR**
and then invokes five LLVM command-line tools to produce a flashable flat
binary:

```
opt   llc   llvm-mc   ld.lld   llvm-objcopy
```

This package is the RP2040 counterpart of
[`pymcu-avr-toolchain`](https://github.com/begeistert/avr-gcc-build): a
platform-specific wheel whose only job is to ship those tools so that
`pip install pymcu-compiler[rp2040]` is fully self-contained — no
`brew install llvm` or `apt install lld` step required on supported platforms.

## License: MIT packaging + Apache-2.0 WITH LLVM-exception binaries

**The Python packaging code in this repo is MIT.**

The bundled LLVM binaries are distributed under the
**Apache License 2.0 with LLVM Exceptions** — the official license of the
[LLVM Project](https://llvm.org/). This is a **permissive** license with
**no copyleft**. Specifically:

- LLVM is **not GPL**. There is no copyleft infection on this package, on
  PyMCU, or on firmware compiled with these tools.
- The LLVM Exception clause explicitly exempts compiled output: binary
  firmware produced by PyMCU through `opt`/`llc` carries **no license
  obligation from LLVM**.
- **Contrast with AVR:** `pymcu-avr-toolchain` bundles `avr-gcc` (derived
  from GCC), which **is** GPL-3.0. That package must therefore be GPL-
  licensed. The isolation mechanism is the same — a separate optional
  package — but the license differs because the upstream compilers differ.

See [LICENSE](./LICENSE) for the complete text and a plain-language
explanation.

## Installation

`libLLVM.{dylib,so}` is 200–300 MB of code even in a release build — too
large for PyPI's 100 MB per-file ceiling. The distribution is therefore split:

| Channel | What it contains |
|---|---|
| **PyPI** (`pip install pymcu-rp2040-toolchain`) | Pure-Python stub — no binaries; tools are resolved from the cache or PATH |
| **GitHub Releases** | Binary wheels with LLVM bundled (~300 MB each) |

### Option A — direct wheel install (recommended for CI / offline use)

```bash
# Linux x86-64
pip install https://github.com/begeistert/pymcu-rp2040-toolchain/releases/download/v22.1.7/pymcu_rp2040_toolchain-22.1.7-py3-none-manylinux_2_17_x86_64.whl

# Linux arm64
pip install https://github.com/begeistert/pymcu-rp2040-toolchain/releases/download/v22.1.7/pymcu_rp2040_toolchain-22.1.7-py3-none-manylinux_2_17_aarch64.whl

# macOS Apple Silicon
pip install https://github.com/begeistert/pymcu-rp2040-toolchain/releases/download/v22.1.7/pymcu_rp2040_toolchain-22.1.7-py3-none-macosx_14_0_arm64.whl

# Windows x86-64
pip install https://github.com/begeistert/pymcu-rp2040-toolchain/releases/download/v22.1.7/pymcu_rp2040_toolchain-22.1.7-py3-none-win_amd64.whl
```

### Option B — runtime download to cache (recommended for developer installs)

```bash
pip install pymcu-rp2040-toolchain          # stub from PyPI
python -m pymcu_rp2040_toolchain fetch --cache   # download LLVM to ~/.pymcu/tools/
```

### Option C — system LLVM

If you already have LLVM 18+ installed (`brew install llvm lld` /
`apt install llvm lld`), the `Rp2040LlvmToolchain` driver finds the tools via
the cache or `PATH` automatically — no package needed.

## How the driver resolves tools

`Rp2040LlvmToolchain` (in `pymcu-rp2040`) checks these sources in order:

| Priority | Source |
|:---:|---|
| 1 | `pymcu_rp2040_toolchain.get_tool(name)` — wheel bundle (`bin/`) |
| 2 | Shared cache `~/.pymcu/tools/<platform>/llvm-rp2040/bin/` |
| 3 | Common keg dirs (`/opt/homebrew/opt/llvm/bin`, `/usr/lib/llvm/bin`, …) |
| 4 | `PATH` |

A missing wheel never blocks a developer who already has LLVM installed.

## Inspecting installed tools

```bash
pymcu-rp2040-toolchain-info          # entry-point alias
python -m pymcu_rp2040_toolchain     # same
python -m pymcu_rp2040_toolchain status
```

Example output:

```
pymcu-rp2040-toolchain (LLVM 22.1.7, platform darwin-arm64)
  [ok] opt            .../pymcu_rp2040_toolchain/bin/opt
  [ok] llc            .../pymcu_rp2040_toolchain/bin/llc
  [ok] llvm-mc        .../pymcu_rp2040_toolchain/bin/llvm-mc
  [ok] ld.lld         .../pymcu_rp2040_toolchain/bin/ld.lld
  [ok] llvm-objcopy   .../pymcu_rp2040_toolchain/bin/llvm-objcopy
```

## Populating the cache (platforms without a published wheel)

Seed the shared `~/.pymcu/tools` cache from a locally installed LLVM:

```bash
# Symlink from Homebrew (dev convenience — keeps the original rpath):
python -m pymcu_rp2040_toolchain fetch --cache \
    --from-dir /opt/homebrew/opt/llvm --link

# Copy from a system install:
python -m pymcu_rp2040_toolchain fetch --cache \
    --from-dir /usr/lib/llvm-19
```

Or let the module download the pinned LLVM release automatically:

```bash
python -m pymcu_rp2040_toolchain fetch --cache
```

The download URL defaults to the official LLVM GitHub release for
`LLVM_VERSION`. Override with environment variables if needed (see below).

## For maintainers: publishing a new wheel

### Release process

1. Update `LLVM_VERSION` in `src/pymcu_rp2040_toolchain/__init__.py`
   and `version` in `pyproject.toml` to the target LLVM release.
2. Tag and push:
   ```bash
   git tag v19.1.7
   git push origin v19.1.7
   ```
3. The `build-wheels.yml` workflow fires automatically:
   - **Linux x64 / macOS arm64 / Windows x64** — download the official
     `.tar.xz` from the LLVM GitHub release (asset names vary per platform;
     see the comment at the top of `build-wheels.yml`), slim to the five
     required tools + shared libs with `scripts/stage-llvm.sh` (strips debug
     symbols, rewrites macOS dylib paths to `@rpath`), build a
     `py3-none-<platform>` wheel.
   - `collect-and-release` smoke-tests the Linux wheel and generates
     `SHA256SUMS`.
   - `publish-pypi` uploads all wheels + sdist to **public PyPI** via OIDC
     trusted publishing (no stored token required).

### Required GitHub configuration

| Item | Where | Purpose |
|---|---|---|
| `release` environment | Repo → Settings → Environments | Gates OIDC publishing; add tag protection rule `v*` |

### Building a wheel locally (testing)

```bash
# Stage tools from a local LLVM installation:
bash scripts/stage-llvm.sh /opt/homebrew/opt/llvm /tmp/staged-llvm

# Build the platform wheel:
RP2040T_TOOLCHAIN_DIR=/tmp/staged-llvm \
WHEEL_PLATFORM_TAG=macosx_14_0_arm64 \
uv build --wheel
```

Without `RP2040T_TOOLCHAIN_DIR` a pure-Python wheel (`py3-none-any`) is
produced — useful for development and sdist; the driver resolves tools from
the cache or system PATH at runtime.

### Wheel size and distribution strategy

`libLLVM.{dylib,so}` is 200–300 MB of pure code even in a release build
(official LLVM releases are already compiled without debug info — strip does
not help). This exceeds PyPI's 100 MB per-file ceiling.

**Binary wheels are therefore published to GitHub Releases**, not PyPI. PyPI
receives only the pure-Python sdist stub. See the Installation section for the
three ways to get the LLVM tools.

## Environment variables

| Variable | Effect |
|---|---|
| `RP2040T_TOOLCHAIN_DIR` | Path to a staged LLVM tree for `hatch_build.py` |
| `WHEEL_PLATFORM_TAG` | Override the wheel platform tag (e.g. `win_amd64`) |
| `PYMCU_TOOLS_DIR` | Override the `~/.pymcu/tools` cache root |
| `PYMCU_RP2040_LLVM_URL` | Override the LLVM archive download URL |
| `PYMCU_RP2040_LLVM_SHA256` | Expected SHA-256 of the downloaded archive |
| `PYMCU_SKIP_HASH_CHECK` | Set to `1` to skip SHA-256 verification |

## Version history

| Package version | Bundled LLVM |
|---|---|
| 22.1.7 | LLVM 22.1.7 |
