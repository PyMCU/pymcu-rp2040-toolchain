# pymcu-rp2040-toolchain

Vendored **LLVM toolchain** for the [PyMCU](https://github.com/PyMCU/pymcu)
RP2040 (ARM Cortex-M0+) backend.

The RP2040 backend lowers PyMCU's architecture-agnostic IR to **LLVM IR**
and then invokes five LLVM command-line tools to produce a flashable flat
binary:

```
opt   llc   llvm-mc   ld.lld   llvm-objcopy
```

This package is the RP2040 counterpart of
[`pymcu-avr-toolchain`](https://github.com/PyMCU/avr-gcc-build): a
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

```bash
pip install pymcu-rp2040-toolchain
```

`libLLVM.{dylib,so}` is 200–300 MB of code even in a release build — too
large for PyPI's 100 MB per-file ceiling. The distribution is therefore split:

| Channel | What it contains |
|---|---|
| **PyPI** (`pip install pymcu-rp2040-toolchain`) | Lightweight stub (~20 KB) |
| **[GitHub Releases](https://github.com/PyMCU/pymcu-rp2040-toolchain/releases)** | Binary wheels with LLVM bundled (~300 MB each) |

**The LLVM tools are downloaded automatically.** The first call to
`get_tool()` (or any PyMCU RP2040 build) downloads the official LLVM
release for your platform from GitHub and extracts the five required tools
into the shared cache at `~/.pymcu/tools/`. Subsequent calls are instant.

```python
import pymcu_rp2040_toolchain
opt = pymcu_rp2040_toolchain.get_tool("opt")   # downloads on first call
```

For CI or air-gapped environments, override the download URL or install the
binary wheel directly:

```bash
# Linux x86-64
pip install https://github.com/PyMCU/pymcu-rp2040-toolchain/releases/download/v22.1.7.post3/pymcu_rp2040_toolchain-22.1.7.post3-py3-none-manylinux_2_17_x86_64.whl

# Linux arm64
pip install https://github.com/PyMCU/pymcu-rp2040-toolchain/releases/download/v22.1.7.post3/pymcu_rp2040_toolchain-22.1.7.post3-py3-none-manylinux_2_17_aarch64.whl

# macOS Apple Silicon
pip install https://github.com/PyMCU/pymcu-rp2040-toolchain/releases/download/v22.1.7.post3/pymcu_rp2040_toolchain-22.1.7.post3-py3-none-macosx_14_0_arm64.whl

# Windows x86-64
pip install https://github.com/PyMCU/pymcu-rp2040-toolchain/releases/download/v22.1.7.post3/pymcu_rp2040_toolchain-22.1.7.post3-py3-none-win_amd64.whl
```

### System LLVM (alternative)

If you already have LLVM 18+ installed (`brew install llvm lld` /
`apt install llvm lld`), the `Rp2040LlvmToolchain` driver finds the tools via
the cache or `PATH` automatically — no package needed.

## How the driver resolves tools

`Rp2040LlvmToolchain` (in `pymcu-rp2040`) checks these sources in order:

| Priority | Source |
|:---:|---|
| 1 | `pymcu_rp2040_toolchain.get_tool(name)` — wheel bundle or auto-downloaded cache |
| 2 | Shared cache `~/.pymcu/tools/<platform>/llvm-rp2040/bin/` |
| 3 | Common keg dirs (`/opt/homebrew/opt/llvm/bin`, `/usr/lib/llvm/bin`, …) |
| 4 | `PATH` |

A missing wheel never blocks a developer who already has LLVM installed.

## Inspecting installed tools

```bash
pymcu-rp2040-toolchain-info          # entry-point
python -m pymcu_rp2040_toolchain status
```

Example output:

```
pymcu-rp2040-toolchain (LLVM 22.1.7, platform darwin-arm64)
  [ok] opt            ~/.pymcu/tools/darwin-arm64/llvm-rp2040/bin/opt
  [ok] llc            ~/.pymcu/tools/darwin-arm64/llvm-rp2040/bin/llc
  [ok] llvm-mc        ~/.pymcu/tools/darwin-arm64/llvm-rp2040/bin/llvm-mc
  [ok] ld.lld         ~/.pymcu/tools/darwin-arm64/llvm-rp2040/bin/ld.lld
  [ok] llvm-objcopy   ~/.pymcu/tools/darwin-arm64/llvm-rp2040/bin/llvm-objcopy
```

## Seeding the cache manually

For platforms without a published wheel, or to use a locally installed LLVM:

```bash
# Download the pinned LLVM release automatically:
python -m pymcu_rp2040_toolchain fetch --cache

# Use a Homebrew LLVM (symlinked, dev convenience):
python -m pymcu_rp2040_toolchain fetch --cache \
    --from-dir /opt/homebrew/opt/llvm --link

# Copy from a system install:
python -m pymcu_rp2040_toolchain fetch --cache \
    --from-dir /usr/lib/llvm-19
```

## For maintainers: publishing a new wheel

### Release process

1. Update `LLVM_VERSION` in `src/pymcu_rp2040_toolchain/__init__.py`
   and `version` in `pyproject.toml`.
2. Tag and push:
   ```bash
   git tag v22.1.7
   git push origin v22.1.7
   ```
3. The `build-wheels.yml` workflow fires automatically:
   - Downloads the official LLVM `.tar.xz`, slims to the five tools +
     shared libs via `scripts/stage-llvm.sh`, builds a `py3-none-<platform>`
     wheel per platform.
   - Binary wheels → **GitHub Releases** (too large for PyPI's 100 MB limit).
   - PyPI receives only the **pure-Python sdist stub**.
   - `publish-pypi` uses OIDC trusted publishing (no stored token required).

### Required GitHub configuration

| Item | Where | Purpose |
|---|---|---|
| `release` environment | Repo → Settings → Environments | Gates OIDC publishing; add tag protection rule `v*` |

### Building a wheel locally

```bash
bash scripts/stage-llvm.sh /opt/homebrew/opt/llvm /tmp/staged-llvm

RP2040T_TOOLCHAIN_DIR=/tmp/staged-llvm \
WHEEL_PLATFORM_TAG=macosx_14_0_arm64 \
uv build --wheel
```

## Environment variables

| Variable | Effect |
|---|---|
| `RP2040T_TOOLCHAIN_DIR` | Path to a staged LLVM tree for `hatch_build.py` |
| `WHEEL_PLATFORM_TAG` | Override the wheel platform tag (e.g. `win_amd64`) |
| `PYMCU_TOOLS_DIR` | Override the `~/.pymcu/tools` cache root |
| `PYMCU_RP2040_LLVM_URL` | Override the LLVM archive download URL (air-gapped installs) |
| `PYMCU_RP2040_LLVM_SHA256` | Expected SHA-256 of the downloaded archive |
| `PYMCU_SKIP_HASH_CHECK` | Set to `1` to skip SHA-256 verification |

## Version history

| Package version | Bundled LLVM | Notes |
|---|---|---|
| 22.1.7.post3 | LLVM 22.1.7 | Fix project URLs; auto-download on first use |
| 22.1.7 | LLVM 22.1.7 | Initial release |
