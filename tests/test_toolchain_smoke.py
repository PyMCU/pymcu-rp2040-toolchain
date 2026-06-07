"""
Toolchain supply-chain smoke tests for pymcu-rp2040-toolchain.

These tests verify that the LLVM tools are correctly installed on the current
platform and that the full pipeline (LLVM IR → opt → llc → llvm-mc → ld.lld
→ llvm-objcopy) produces a valid flat binary.

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
    # get_tool() triggers auto-download on first use when only the stub is
    # installed (no bundled binaries) — same pattern as AVR's get_bin_dir().
    _BIN_DIR: Path = _tc.get_tool("opt").parent
    _HAS_TOOLCHAIN = True
    _TC_ERROR = ""
except Exception as exc:
    _BIN_DIR = Path("/nonexistent")
    _HAS_TOOLCHAIN = False
    _TC_ERROR = str(exc)

pytestmark = pytest.mark.skipif(
    not _HAS_TOOLCHAIN,
    reason=f"pymcu-rp2040-toolchain not available: {_TC_ERROR}",
)

_IS_WIN = sys.platform == "win32"
_EXE = ".exe" if _IS_WIN else ""

# RP2040 target identifiers — must match llvm.py in the rp2040 backend
TARGET_TRIPLE = "thumbv6m-none-eabi"
TARGET_CPU = "cortex-m0plus"

# Minimal LLVM IR for Thumb-2 (single function, no side effects)
_MINIMAL_LL = f"""\
target triple = "{TARGET_TRIPLE}"
target datalayout = "e-m:e-p:32:32-i64:64-v128:64:128-a:0:32-n32-S64"

define i32 @add(i32 %a, i32 %b) {{
  %sum = add i32 %a, %b
  ret i32 %sum
}}

define void @main() {{
  ret void
}}
"""

# Minimal RP2040 linker script: flash at 0x10000000, SRAM at 0x20000000
_MINIMAL_LD = """\
ENTRY(main)
SECTIONS {
  . = 0x10000000;
  .text : { *(.text*) }
  . = ALIGN(4);
  . = 0x20000000;
  .data : { *(.data*) }
  .bss  : { *(.bss*) *(COMMON) }
}
"""

# Minimal Thumb-2 assembly (crt0 stub) for llvm-mc to assemble
_MINIMAL_ASM = f"""\
.syntax unified
.arch armv6-m
.thumb
.global _start
.type _start, %function
_start:
    bl main
    b .
"""


def _run(*args, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(a) for a in args],
        capture_output=True,
        timeout=60,
        **kwargs,
    )


def _bin_dir() -> Path:
    return _BIN_DIR


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

    def test_llc_lists_thumb_target(self):
        r = _run(_bin_dir() / f"llc{_EXE}", "--version")
        assert r.returncode == 0
        out = (r.stdout + r.stderr).decode().lower()
        assert "thumb" in out or "arm" in out, (
            "llc does not list ARM/Thumb targets — wrong LLVM build?\n" + out[:500]
        )


# ---------------------------------------------------------------------------
# 4. Full LLVM pipeline: IR → opt → llc → llvm-mc → ld.lld → llvm-objcopy
#
# Mirrors the sequence in rp2040 backend's llvm.py:
#   opt  -O2              firmware.ll    → firmware.opt.ll
#   llc  -mtriple=thumbv6m-none-eabi     → firmware.o
#   llvm-mc -triple=thumbv6m-none-eabi   → crt0.o
#   ld.lld -T rp2040.ld  *.o            → firmware.elf
#   llvm-objcopy -O binary               → firmware.bin
# ---------------------------------------------------------------------------


class TestLlvmPipeline:
    """End-to-end pipeline sanity check on every CI platform."""

    @pytest.fixture(autouse=True)
    def tmp(self, tmp_path):
        self._d = tmp_path
        yield tmp_path

    def _d_path(self, name: str) -> Path:
        return self._d / name

    # ── individual stage tests ─────────────────────────────────────────────

    def test_opt_optimizes_ir(self):
        ll = self._d_path("add.ll")
        ll.write_text(_MINIMAL_LL)
        out_ll = self._d_path("add.opt.ll")
        r = _run(
            _tc.get_tool("opt"),
            "-O2", "-S",
            str(ll), "-o", str(out_ll),
        )
        assert r.returncode == 0, f"opt failed:\n{r.stderr.decode()}"
        assert out_ll.exists() and out_ll.stat().st_size > 0

    def test_llc_compiles_ir_to_object(self):
        ll = self._d_path("add.ll")
        ll.write_text(_MINIMAL_LL)
        obj = self._d_path("add.o")
        r = _run(
            _tc.get_tool("llc"),
            f"-mtriple={TARGET_TRIPLE}",
            f"-mcpu={TARGET_CPU}",
            "-O2", "-filetype=obj",
            str(ll), "-o", str(obj),
        )
        assert r.returncode == 0, f"llc failed:\n{r.stderr.decode()}"
        assert obj.exists() and obj.stat().st_size > 0

    def test_llvm_mc_assembles_asm(self):
        asm = self._d_path("crt0.s")
        asm.write_text(_MINIMAL_ASM)
        obj = self._d_path("crt0.o")
        r = _run(
            _tc.get_tool("llvm-mc"),
            f"-triple={TARGET_TRIPLE}",
            "-filetype=obj",
            str(asm), "-o", str(obj),
        )
        assert r.returncode == 0, f"llvm-mc failed:\n{r.stderr.decode()}"
        assert obj.exists() and obj.stat().st_size > 0

    def test_lld_links_objects(self):
        # Build IR object
        ll = self._d_path("add.ll")
        ll.write_text(_MINIMAL_LL)
        fw_o = self._d_path("fw.o")
        _run(
            _tc.get_tool("llc"),
            f"-mtriple={TARGET_TRIPLE}", f"-mcpu={TARGET_CPU}",
            "-O2", "-filetype=obj",
            str(ll), "-o", str(fw_o),
        )
        # Write linker script
        ld_script = self._d_path("rp2040.ld")
        ld_script.write_text(_MINIMAL_LD)
        # Link
        elf = self._d_path("firmware.elf")
        r = _run(
            _tc.get_tool("ld.lld"),
            "-T", str(ld_script),
            str(fw_o),
            "-o", str(elf),
        )
        assert r.returncode == 0, f"ld.lld failed:\n{r.stderr.decode()}"
        assert elf.exists() and elf.stat().st_size > 0

    def test_objcopy_extracts_binary(self):
        # Build + link
        ll = self._d_path("add.ll")
        ll.write_text(_MINIMAL_LL)
        fw_o = self._d_path("fw.o")
        _run(
            _tc.get_tool("llc"),
            f"-mtriple={TARGET_TRIPLE}", f"-mcpu={TARGET_CPU}",
            "-O2", "-filetype=obj",
            str(ll), "-o", str(fw_o),
        )
        ld_script = self._d_path("rp2040.ld")
        ld_script.write_text(_MINIMAL_LD)
        elf = self._d_path("firmware.elf")
        _run(
            _tc.get_tool("ld.lld"),
            "-T", str(ld_script), str(fw_o), "-o", str(elf),
        )
        # objcopy → flat binary
        binfile = self._d_path("firmware.bin")
        r = _run(
            _tc.get_tool("llvm-objcopy"),
            "-O", "binary", str(elf), str(binfile),
        )
        assert r.returncode == 0, f"llvm-objcopy failed:\n{r.stderr.decode()}"
        assert binfile.exists() and binfile.stat().st_size > 0

    def test_full_pipeline(self):
        """Full pipeline in one shot: IR + asm → opt → obj × 2 → link → binary."""
        ll = self._d_path("fw.ll")
        ll.write_text(_MINIMAL_LL)
        asm = self._d_path("crt0.s")
        asm.write_text(_MINIMAL_ASM)
        ld_script = self._d_path("rp2040.ld")
        ld_script.write_text(_MINIMAL_LD)

        # Step 1 — optimize IR
        opt_ll = self._d_path("fw.opt.ll")
        r = _run(_tc.get_tool("opt"), "-O2", "-S", str(ll), "-o", str(opt_ll))
        assert r.returncode == 0, f"opt: {r.stderr.decode()}"

        # Step 2a — compile IR to object
        fw_o = self._d_path("fw.o")
        r = _run(
            _tc.get_tool("llc"),
            f"-mtriple={TARGET_TRIPLE}", f"-mcpu={TARGET_CPU}",
            "-O2", "-filetype=obj", str(opt_ll), "-o", str(fw_o),
        )
        assert r.returncode == 0, f"llc: {r.stderr.decode()}"

        # Step 2b — assemble startup stub
        crt0_o = self._d_path("crt0.o")
        r = _run(
            _tc.get_tool("llvm-mc"),
            f"-triple={TARGET_TRIPLE}", "-filetype=obj",
            str(asm), "-o", str(crt0_o),
        )
        assert r.returncode == 0, f"llvm-mc: {r.stderr.decode()}"

        # Step 3 — link
        elf = self._d_path("firmware.elf")
        r = _run(
            _tc.get_tool("ld.lld"),
            "-T", str(ld_script), str(crt0_o), str(fw_o), "-o", str(elf),
        )
        assert r.returncode == 0, f"ld.lld: {r.stderr.decode()}"

        # Step 4 — extract flat binary
        binfile = self._d_path("firmware.bin")
        r = _run(
            _tc.get_tool("llvm-objcopy"),
            "-O", "binary", str(elf), str(binfile),
        )
        assert r.returncode == 0, f"llvm-objcopy: {r.stderr.decode()}"

        assert binfile.stat().st_size > 0, "firmware.bin is empty — pipeline produced no code"


# ---------------------------------------------------------------------------
# 5. Rp2040LlvmToolchain integration (only when pymcu-rp2040 is installed)
# ---------------------------------------------------------------------------

try:
    from pymcu.toolchain.rp2040.llvm import Rp2040LlvmToolchain as _Rp2040Toolchain
    from rich.console import Console as _Console
    _HAS_BACKEND = True
except ImportError:
    _HAS_BACKEND = False


@pytest.mark.skipif(not _HAS_BACKEND, reason="pymcu-rp2040 not installed")
class TestRp2040LlvmToolchain:
    """Validate Rp2040LlvmToolchain API — skipped if pymcu-rp2040 is absent."""

    @pytest.fixture
    def toolchain(self):
        return _Rp2040Toolchain(_Console(quiet=True))

    def test_supports_rp2040(self, toolchain):
        assert toolchain.supports("rp2040")

    def test_is_cached(self, toolchain):
        assert toolchain.is_cached(), (
            "Toolchain reports not cached despite pymcu-rp2040-toolchain being installed"
        )

    def test_full_pipeline(self, toolchain, tmp_path):
        ll = tmp_path / "fw.ll"
        ll.write_text(_MINIMAL_LL)
        binfile = toolchain.compile(
            ll_file=ll,
            out_dir=tmp_path,
        )
        assert binfile.exists() and binfile.stat().st_size > 0
