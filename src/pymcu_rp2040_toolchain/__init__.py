# -----------------------------------------------------------------------------
# pymcu-rp2040-toolchain -- vendored LLVM toolchain for the PyMCU RP2040 backend
# Copyright (C) 2026 Ivan Montiel Cardona and the PyMCU Project Authors
#
# SPDX-License-Identifier: MIT
# -----------------------------------------------------------------------------

"""
Vendored LLVM toolchain for the PyMCU RP2040 (ARM Cortex-M0+) backend.

This package ships the five LLVM command-line tools the RP2040 toolchain
driver needs to turn LLVM IR into a flashable flat image:

    opt  llc  llvm-mc  ld.lld  llvm-objcopy

It mirrors the role ``pymcu-avr-toolchain`` plays for the AVR backend: a
platform-specific wheel whose only job is to make ``get_tool(name)`` return a
path to a ready-to-run binary, so ``pip install pymcu-compiler[rp2040]`` is
self-contained and reproducible (no system ``brew install llvm`` step).

Resolution order for :func:`get_tool`:

1. Binaries bundled inside this wheel under ``bin`` / ``lib`` (the normal
   case for a published platform wheel from PyPI -- see ``hatch_build.py`` / CI).
2. The shared PyMCU tool cache at
   ``~/.pymcu/tools/<platform>/llvm-rp2040/bin`` (populated by
   ``python -m pymcu_rp2040_toolchain fetch --cache``; this is also the
   directory the Rp2040LlvmToolchain driver probes directly).

If neither is present a :class:`FileNotFoundError` is raised and the driver
falls back to a system LLVM on PATH.
"""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import List, Optional

__all__ = [
    "TOOLS",
    "LLVM_VERSION",
    "platform_key",
    "get_tool",
    "tools_bin_dir",
    "bundled_bin_dir",
    "cache_bin_dir",
    "is_installed",
    "missing_tools",
]

# LLVM version the published wheels are built against. Kept in one place so the
# fetch script, the wheel metadata and any diagnostics agree.
LLVM_VERSION = "19.1.7"

# The exact tools the RP2040 pipeline invokes (see toolchain/rp2040/llvm.py).
TOOLS: List[str] = ["opt", "llc", "llvm-mc", "ld.lld", "llvm-objcopy"]

_PKG_DIR = Path(__file__).resolve().parent


def _exe(name: str) -> str:
    """Append the platform executable suffix."""
    return name + (".exe" if sys.platform == "win32" else "")


def platform_key() -> str:
    """Return the ``{os}-{arch}`` discriminator (matches the toolchain SDK)."""
    machine = platform.machine().lower()
    if machine in ("amd64", "x86_64"):
        arch = "x86_64"
    elif machine in ("arm64", "aarch64"):
        arch = "arm64"
    else:
        arch = machine
    os_name = sys.platform if not sys.platform.startswith("linux") else "linux"
    return f"{os_name}-{arch}"


def bundled_bin_dir() -> Path:
    """Directory holding binaries bundled inside this wheel (may be empty).

    Named ``bin`` (with a sibling ``lib``) so the LLVM tools resolve their
    shared libraries through their default ``@loader_path/../lib`` /
    ``$ORIGIN/../lib`` rpath without any patching.
    """
    return _PKG_DIR / "bin"


def bundled_lib_dir() -> Path:
    """Directory holding shared libraries bundled alongside the binaries."""
    return _PKG_DIR / "lib"


def cache_root() -> Path:
    """Root of the shared PyMCU tool cache, honouring PYMCU_TOOLS_DIR."""
    override = os.environ.get("PYMCU_TOOLS_DIR")
    if override:
        root = Path(override)
        if not root.is_absolute():
            raise ValueError(
                f"PYMCU_TOOLS_DIR must be an absolute path, got: {override!r}"
            )
        return root / platform_key()
    return Path.home() / ".pymcu" / "tools" / platform_key()


def cache_tool_dir() -> Path:
    """Per-tool cache directory: ``<cache_root>/llvm-rp2040``."""
    return cache_root() / "llvm-rp2040"


def cache_bin_dir() -> Path:
    """``bin`` directory inside the cache tool dir (probed by the driver)."""
    return cache_tool_dir() / "bin"


def _resolve(name: str) -> Optional[Path]:
    """Return the first existing path for *name*, or None."""
    exe = _exe(name)
    for d in (bundled_bin_dir(), cache_bin_dir()):
        cand = d / exe
        if cand.exists():
            return cand
    return None


def get_tool(name: str) -> Path:
    """
    Return the filesystem path to a bundled (or cached) LLVM tool.

    Raises
    ------
    FileNotFoundError
        If *name* is not one of :data:`TOOLS`, or no binary is available in
        the wheel bundle or the cache.
    """
    if name not in TOOLS:
        raise FileNotFoundError(
            f"{name!r} is not provided by pymcu-rp2040-toolchain "
            f"(known tools: {', '.join(TOOLS)})"
        )
    found = _resolve(name)
    if found is None:
        raise FileNotFoundError(
            f"LLVM tool {name!r} is not vendored in this install.\n"
            f"Populate it with: python -m pymcu_rp2040_toolchain fetch --cache"
        )
    return found


def tools_bin_dir() -> Optional[Path]:
    """
    Return the directory that contains a complete set of tools (bundle first,
    then cache), or None if neither location has all of :data:`TOOLS`.
    """
    for d in (bundled_bin_dir(), cache_bin_dir()):
        if all((d / _exe(t)).exists() for t in TOOLS):
            return d
    return None


def missing_tools() -> List[str]:
    """Return the tools that cannot currently be resolved."""
    return [t for t in TOOLS if _resolve(t) is None]


def is_installed() -> bool:
    """True when every tool in :data:`TOOLS` resolves to an existing binary."""
    return not missing_tools()
