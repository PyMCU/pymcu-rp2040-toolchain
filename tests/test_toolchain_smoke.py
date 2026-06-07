"""
Toolchain supply-chain smoke tests for pymcu-rp2040-toolchain.

These tests verify that the LLVM tools are correctly installed on the current
platform: all five tools exist, execute bits are set, and basic invocation
(--version / --help) works.

Run with:
    pytest tests/test_toolchain_smoke.py -v
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Package availability guard
# ---------------------------------------------------------------------------

try:
    import pymcu_rp2040_toolchain as _tc

    _HAS_TOOLCHAIN = _tc.is_installed()
    _MISSING = _tc.missing_tools()
    _TC_ERROR = f"missing: {_MISSING}" if _MISSING else ""
except Exception as exc:
    _HAS_TOOLCHAIN = False
    _MISSING = []
    _TC_ERROR = str(exc)

pytestmark = pytest.mark.skipif(
    not _HAS_TOOLCHAIN,
    reason=f"pymcu-rp2040-toolchain not installed or tools missing: {_TC_ERROR}",
)

_IS_WIN = sys.platform == "win32"
_EXE = ".exe" if _IS_WIN else ""


def _run(*args, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(a) for a in args],
        capture_output=True,
        timeout=30,
        **kwargs,
    )


def _bin_dir() -> Path:
    d = _tc.tools_bin_dir()
    assert d is not None, "tools_bin_dir() returned None — toolchain not installed"
    return d


# ---------------------------------------------------------------------------
# 1. Package API
# ---------------------------------------------------------------------------


class TestPackageAPI:
    def test_tools_list(self):
        assert set(_tc.TOOLS) >= {"opt", "llc", "llvm-mc", "ld.lld", "llvm-objcopy"}

    def test_is_installed(self):
        assert _tc.is_installed()

    def test_missing_tools_empty(self):
        assert _tc.missing_tools() == []

    def test_tools_bin_dir_exists(self):
        d = _tc.tools_bin_dir()
        assert d is not None and d.is_dir(), f"tools_bin_dir() = {d}"

    @pytest.mark.parametrize("name", ["opt", "llc", "llvm-mc", "ld.lld", "llvm-objcopy"])
    def test_get_tool(self, name):
        p = _tc.get_tool(name)
        assert p.exists(), f"{name} path from get_tool() does not exist: {p}"


# ---------------------------------------------------------------------------
# 2. Binary presence and executability
# ---------------------------------------------------------------------------


class TestBinaryPresence:
    @pytest.mark.parametrize("name", ["opt", "llc", "llvm-mc", "ld.lld", "llvm-objcopy"])
    def test_binary_exists(self, name):
        p = _bin_dir() / f"{name}{_EXE}"
        assert p.exists(), f"{name} not found in {_bin_dir()}"

    @pytest.mark.skipif(_IS_WIN, reason="execute bits are a POSIX concept")
    @pytest.mark.parametrize("name", ["opt", "llc", "llvm-mc", "ld.lld", "llvm-objcopy"])
    def test_binary_executable(self, name):
        p = _bin_dir() / name
        assert os.access(p, os.X_OK), (
            f"{name} is not executable — ZIP artifact upload may have stripped +x bits"
        )

    @pytest.mark.skipif(_IS_WIN, reason="execute bits are a POSIX concept")
    def test_lib_dir_executables(self):
        lib_dir = _bin_dir().parent / "lib"
        if not lib_dir.is_dir():
            pytest.skip("no lib/ directory in this wheel")
        non_exec_dylibs = [
            str(f) for f in lib_dir.rglob("*")
            if f.is_file() and not f.is_symlink()
            and f.suffix in (".so", ".dylib")
            and not os.access(f, os.R_OK)
        ]
        assert not non_exec_dylibs, (
            "lib/ shared libraries not readable:\n" + "\n".join(non_exec_dylibs[:10])
        )


# ---------------------------------------------------------------------------
# 3. Tool execution — basic invocation
# ---------------------------------------------------------------------------


class TestToolExecution:
    @pytest.mark.parametrize("name", ["opt", "llc", "llvm-objcopy"])
    def test_version(self, name):
        r = _run(_bin_dir() / f"{name}{_EXE}", "--version")
        assert r.returncode == 0, f"{name} --version failed:\n{r.stderr.decode()}"
        out = (r.stdout + r.stderr).decode().lower()
        assert "llvm" in out or name in out, f"unexpected output from {name}: {out[:200]}"

    def test_llvm_mc_help(self):
        r = _run(_bin_dir() / f"llvm-mc{_EXE}", "--help")
        # llvm-mc exits 0 or 1 with --help; either is fine as long as it runs
        assert r.returncode in (0, 1), f"llvm-mc --help crashed: {r.stderr.decode()}"

    def test_lld_version(self):
        r = _run(_bin_dir() / f"ld.lld{_EXE}", "--version")
        assert r.returncode == 0, f"ld.lld --version failed:\n{r.stderr.decode()}"
        out = r.stdout.decode().lower()
        assert "lld" in out, f"unexpected output: {out[:200]}"

    def test_llc_target_list(self):
        r = _run(_bin_dir() / f"llc{_EXE}", "--version")
        assert r.returncode == 0
        out = (r.stdout + r.stderr).decode().lower()
        assert "thumb" in out or "arm" in out, (
            "llc does not list ARM/Thumb targets — wrong LLVM build?\n" + out[:500]
        )
