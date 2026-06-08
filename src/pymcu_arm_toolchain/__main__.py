# -----------------------------------------------------------------------------
# pymcu-arm-toolchain -- CLI
# Copyright (C) 2026 Ivan Montiel Cardona and the PyMCU Project Authors
#
# SPDX-License-Identifier: MIT
# -----------------------------------------------------------------------------

"""
Command line for vendoring / inspecting the ARM LLVM toolchain.

    python -m pymcu_arm_toolchain status
    python -m pymcu_arm_toolchain fetch [--cache | --bundle]
                                        [--from-dir DIR] [--link]

Examples
--------
Download the pinned LLVM release into the shared cache (user install)::

    python -m pymcu_arm_toolchain fetch --cache

Vendor binaries into the wheel before building a platform wheel (CI)::

    python -m pymcu_arm_toolchain fetch --bundle

Developer convenience -- point at a system LLVM without copying::

    python -m pymcu_arm_toolchain fetch --cache \
        --from-dir /opt/homebrew/opt/llvm --link
"""

from __future__ import annotations

import argparse
import sys

from . import (
    LLVM_VERSION,
    TOOLS,
    get_tool,
    is_installed,
    missing_tools,
    platform_key,
)
from ._fetch import fetch


def _cmd_status() -> int:
    print(f"pymcu-arm-toolchain (LLVM {LLVM_VERSION}, platform {platform_key()})")
    ok = is_installed()
    for t in TOOLS:
        try:
            print(f"  [ok] {t:14s} {get_tool(t)}")
        except FileNotFoundError:
            print(f"  [--] {t:14s} not vendored")
    if not ok:
        print(f"\nMissing: {', '.join(missing_tools())}")
        print("Run: python -m pymcu_arm_toolchain fetch --cache")
    return 0 if ok else 1


def _cmd_fetch(args: argparse.Namespace) -> int:
    target = "bundle" if args.bundle else "cache"
    dest = fetch(target=target, from_dir=args.from_dir, link=args.link)
    print(f"pymcu-arm-toolchain: staged into {dest}")
    return 0 if is_installed() else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pymcu_arm_toolchain")
    # No subcommand defaults to `status` (the package's info entry point).
    sub = parser.add_subparsers(dest="cmd", required=False)

    sub.add_parser("status", help="show which LLVM tools are vendored")

    p_fetch = sub.add_parser("fetch", help="download or stage the LLVM tools")
    where = p_fetch.add_mutually_exclusive_group()
    where.add_argument("--cache", action="store_true",
                       help="stage into ~/.pymcu/tools (default)")
    where.add_argument("--bundle", action="store_true",
                       help="stage into the in-wheel bundle (publishing)")
    p_fetch.add_argument("--from-dir",
                         help="stage from an installed LLVM tree instead of downloading")
    p_fetch.add_argument("--link", action="store_true",
                         help="symlink tools from --from-dir (dev only)")

    args = parser.parse_args(argv)
    if args.cmd in (None, "status"):
        return _cmd_status()
    if args.cmd == "fetch":
        return _cmd_fetch(args)
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
