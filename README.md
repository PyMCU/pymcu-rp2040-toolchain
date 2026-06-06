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

```bash
# Automatic — included when you install the RP2040 extra:
pip install pymcu-compiler[rp2040]

# Standalone:
pip install pymcu-rp2040-toolchain
```

Platform wheels are published for **Linux x86-64**, **macOS arm64**, and
**Windows x86-64**. On other platforms (Linux arm64, macOS Intel, etc.) the
`Rp2040LlvmToolchain` falls back to a system LLVM found via the cache or
`PATH` (`brew install llvm lld` / `apt install llvm lld`).

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
pymcu-rp2040-toolchain (LLVM 19.1.7, platform darwin-arm64)
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
   - **3-platform matrix** downloads the official LLVM archives from
     `github.com/llvm/llvm-project/releases`.
   - `scripts/stage-llvm.sh` slims each archive to the 5 tools + shared
     libs; on macOS it rewrites absolute dylib paths to `@rpath`.
   - `hatch_build.py` bundles the staged tree into a `py3-none-<platform>`
     wheel.
   - `collect-and-release` smoke-tests the Linux wheel and generates
     `SHA256SUMS`.
   - `publish-pypi` uploads all wheels + sdist to **public PyPI** via
     OIDC trusted publishing (no stored token).
   - `publish-private` uploads to the private Gitea index over Headscale.

### Required GitHub secrets / environments

| Name | Where | Purpose |
|---|---|---|
| `release` environment | Repo settings | Enables OIDC trusted publishing on PyPI |
| `HEADSCALE_AUTH_KEY` | Repo secret | Tailscale auth for the private network |
| `HEADSCALE_URL` | Repo secret | Headscale control server URL |
| `PRIVATE_PYPI_URL` | Repo secret | Private Gitea PyPI endpoint |
| `PRIVATE_PYPI_USERNAME` | Repo secret | Gitea username |
| `PRIVATE_PYPI_TOKEN` | Repo secret | Gitea API token |

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
| 19.1.7 | LLVM 19.1.7 |
