# hatch_build.py
# Custom hatchling build hook: copies the slimmed LLVM tools into the wheel
# before packaging, producing a Python-version-agnostic but platform-specific
# wheel (py3-none-<platform>), exactly like pymcu-avr-toolchain.
#
# Environment variables:
#   ARMT_TOOLCHAIN_DIR  Path to a staged LLVM tree (required). Must contain
#                       bin/{opt,llc,llvm-mc,ld.lld,llvm-objcopy} and a
#                       sibling lib/ with the shared libraries they need.
#                       Produced by scripts/stage-llvm.sh.
#   WHEEL_PLATFORM_TAG  Override the wheel platform tag, e.g.
#                       manylinux_2_17_x86_64, win_amd64, macosx_14_0_arm64.

from __future__ import annotations

import os
import platform
import shutil
import sys
import sysconfig
from pathlib import Path
from typing import Optional

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

# The five tools the ARM LLVM pipeline invokes (see toolchain/rp2040/llvm.py).
_REQUIRED_BINS = ["opt", "llc", "llvm-mc", "ld.lld", "llvm-objcopy"]
# Subdirectories copied into the package (and cleaned up afterwards).
_STAGED_SUBDIRS = ["bin", "lib"]


class CustomBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict) -> None:
        root = Path(self.root)
        toolchain_dir = _find_toolchain_dir()
        if toolchain_dir is None:
            # No staged toolchain (editable install, plain `uv build`, sdist):
            # produce a pure-Python wheel with no binaries. At runtime the
            # package then resolves from the ~/.pymcu/tools cache or system LLVM.
            self.app.display_info(
                "[hatch-hook] ARMT_TOOLCHAIN_DIR not set -- building a "
                "pure-Python wheel (no bundled LLVM)."
            )
            return
        self.app.display_info(f"[hatch-hook] Using LLVM toolchain: {toolchain_dir}")

        _validate_toolchain(toolchain_dir / "bin")

        pkg_dir = root / "src" / "pymcu_arm_toolchain"

        # Remove any previously staged binaries (keep the .gitkeep placeholders).
        for sub in _STAGED_SUBDIRS:
            d = pkg_dir / sub
            if d.exists():
                for item in d.iterdir():
                    if item.name == ".gitkeep":
                        continue
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()

        # Copy bin/ and lib/ siblings so the tools resolve libLLVM via their
        # default ../lib rpath.
        for sub in _STAGED_SUBDIRS:
            src = toolchain_dir / sub
            if not src.is_dir():
                continue
            dst = pkg_dir / sub
            dst.mkdir(parents=True, exist_ok=True)
            for item in src.iterdir():
                target = dst / item.name
                if item.is_dir():
                    shutil.copytree(item, target, symlinks=True)
                else:
                    shutil.copy2(item, target, follow_symlinks=False)
            self.app.display_info(f"[hatch-hook] staged {src} -> {dst}")

        plat_tag = _get_wheel_platform_tag()
        build_data["pure_python"] = False
        build_data["tag"] = f"py3-none-{plat_tag}"
        self.app.display_info(f"[hatch-hook] Wheel tag: py3-none-{plat_tag}")

    def finalize(self, version: str, build_data: dict, artifact_path: str) -> None:
        # Leave the source tree clean: drop everything staged except .gitkeep.
        pkg_dir = Path(self.root) / "src" / "pymcu_arm_toolchain"
        for sub in _STAGED_SUBDIRS:
            d = pkg_dir / sub
            if not d.is_dir():
                continue
            for item in d.iterdir():
                if item.name == ".gitkeep":
                    continue
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            self.app.display_info(f"[hatch-hook] cleaned up: {d}")


def _find_toolchain_dir() -> "Optional[Path]":
    """Return the staged LLVM dir, or None if ARMT_TOOLCHAIN_DIR is unset."""
    env = os.environ.get("ARMT_TOOLCHAIN_DIR")
    if not env:
        return None
    d = Path(env).resolve()
    if not d.is_dir():
        raise FileNotFoundError(f"ARMT_TOOLCHAIN_DIR does not exist: {d}")
    return d


def _validate_toolchain(bin_dir: Path) -> None:
    plat_tag = os.environ.get("WHEEL_PLATFORM_TAG", "")
    exe = ".exe" if sys.platform == "win32" or plat_tag.startswith("win") else ""
    missing = [b for b in _REQUIRED_BINS if not (bin_dir / (b + exe)).exists()]
    if missing:
        raise FileNotFoundError(
            f"Staged toolchain bin/ is missing required tools: {missing}\n"
            f"Checked in: {bin_dir}"
        )


def _get_wheel_platform_tag() -> str:
    override = os.environ.get("WHEEL_PLATFORM_TAG")
    if override:
        return override
    if sys.platform.startswith("linux"):
        arch = platform.machine().lower()
        return f"manylinux_2_17_{arch}"
    return sysconfig.get_platform().replace("-", "_").replace(".", "_")
