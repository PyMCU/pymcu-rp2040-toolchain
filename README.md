# pymcu-rp2040-toolchain

Vendored **LLVM toolchain** for the PyMCU RP2040 (ARM Cortex-M0+) backend.

The RP2040 backend emits **LLVM IR**, not assembly, and relies on five LLVM
command-line tools to turn that IR into a flashable flat image:

```
opt   llc   llvm-mc   ld.lld   llvm-objcopy
```

This package is the RP2040 analogue of [`pymcu-avr-toolchain`](../pymcu-avr):
a platform-specific wheel whose sole job is to make those tools available so
`pip install pymcu-compiler[rp2040]` is self-contained — no system
`brew install llvm` / `apt install llvm lld` step required.

## How the driver finds the tools

`Rp2040LlvmToolchain` resolves each binary in this order:

1. `pymcu_rp2040_toolchain.get_tool(name)` — binaries bundled in this wheel,
   or staged into the shared cache `~/.pymcu/tools/<platform>/llvm-rp2040/bin`.
2. Common system keg directories (`/opt/homebrew/opt/llvm/bin`, …).
3. `PATH`.

So a missing wheel never blocks a developer who already has LLVM installed.

## Vendoring the binaries

The wheel ships **pure Python**; the binaries are staged in separately, exactly
like `pymcu-avr-toolchain` is built by the `avr-gcc-build` repo.

```bash
# User install: download the pinned LLVM release into the shared cache.
python -m pymcu_rp2040_toolchain fetch --cache

# CI / publishing: stage binaries into the wheel before building a
# platform-tagged wheel.
python -m pymcu_rp2040_toolchain fetch --bundle

# Developer convenience: reuse a system LLVM without copying (symlinks,
# keeps the original rpath).
python -m pymcu_rp2040_toolchain fetch --cache \
    --from-dir /opt/homebrew/opt/llvm --link

# Inspect what is currently vendored.
python -m pymcu_rp2040_toolchain status
```

The download URL and SHA-256 per platform live in `_fetch.py` and can be
overridden with `PYMCU_RP2040_LLVM_URL` / `PYMCU_RP2040_LLVM_SHA256` (e.g. to
point at a slimmed re-packaged archive).

## License

MIT for this packaging glue. The bundled LLVM binaries are distributed under
the [Apache-2.0 WITH LLVM-exception](https://llvm.org/LICENSE.txt) license.
