# -----------------------------------------------------------------------------
# pymcu-rp2040-toolchain -- LLVM binary staging / download
# Copyright (C) 2026 Ivan Montiel Cardona and the PyMCU Project Authors
#
# SPDX-License-Identifier: MIT
# -----------------------------------------------------------------------------

"""
Stage the five LLVM tools (and the shared libraries they dlopen) into either:

* the in-wheel bundle (``_bin`` / ``_lib``) -- run by CI / the publishing
  pipeline before building a platform wheel, so the wheel is self-contained;
* the shared PyMCU tool cache (``~/.pymcu/tools/<platform>/llvm-rp2040``) --
  run on the user's machine by ``python -m pymcu_rp2040_toolchain fetch
  --cache`` when no bundled binaries are present.

Two sources are supported:

* ``--from-dir DIR``  -- stage from an already-installed LLVM (e.g. a Homebrew
  keg ``/opt/homebrew/opt/llvm`` or an extracted release). With ``--link`` the
  tools are symlinked (developer convenience; keeps the original rpath), else
  they are copied together with the shared libs.
* default            -- download the pinned official LLVM release for the
  current platform from GitHub and stage from it.

Distribution note: the supported platforms ship **pre-built wheels on PyPI**
(`pip install pymcu-rp2040-toolchain`), so the normal install path never runs
this module -- the binaries are already bundled and their integrity is
guaranteed by PyPI. SHA-256 pinning of the upstream archive is therefore
**optional**: it is only a best-effort safety net for the runtime download
fallback used on platforms without a published wheel (or in development).
Set ``PYMCU_RP2040_LLVM_SHA256`` to enforce it, or ``PYMCU_SKIP_HASH_CHECK=1``
to skip it explicitly. ``PYMCU_RP2040_LLVM_URL`` overrides the archive URL.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import ssl
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Dict, Iterable, Optional


def _ssl_context() -> ssl.SSLContext:
    """
    Return an SSL context with working CA certificates.

    Python builds from python.org on macOS use a bundled OpenSSL that does not
    read the system keychain automatically.  We supplement the default context
    with known system CA bundle paths so HTTPS to GitHub works out of the box.
    """
    ctx = ssl.create_default_context()
    _CA_CANDIDATES = [
        os.environ.get("SSL_CERT_FILE", ""),
        "/etc/ssl/cert.pem",                        # macOS system bundle
        "/etc/ssl/certs/ca-certificates.crt",        # Debian/Ubuntu
        "/etc/pki/tls/certs/ca-bundle.crt",          # RHEL/CentOS/Fedora
        "/usr/local/etc/openssl/cert.pem",            # Homebrew OpenSSL
    ]
    for cafile in _CA_CANDIDATES:
        if cafile and os.path.isfile(cafile):
            try:
                ctx.load_verify_locations(cafile=cafile)
                return ctx
            except ssl.SSLError:
                continue
    try:
        import certifi  # noqa: PLC0415
        ctx.load_verify_locations(cafile=certifi.where())
    except (ImportError, ssl.SSLError):
        pass
    return ctx

from . import (
    LLVM_VERSION,
    TOOLS,
    bundled_bin_dir,
    bundled_lib_dir,
    cache_bin_dir,
    cache_tool_dir,
    platform_key,
)

# Shared libraries the LLVM CLI tools load at runtime. Globbed (not exact) so a
# single entry matches the versioned soname variants across platforms.
_LIB_GLOBS = ("libLLVM*", "libLTO*", "libc++*", "libc++abi*", "libunwind*")

# Official LLVM GitHub release assets, keyed by platform, used ONLY by the
# runtime download fallback (the published PyPI wheels bundle the binaries and
# do not download anything). sha256 is intentionally blank -- verification is
# optional here (see module docstring); supply PYMCU_RP2040_LLVM_SHA256 to
# enforce it. The asset names follow the llvm/llvm-project release convention.
_RELEASE_BASE = f"https://github.com/llvm/llvm-project/releases/download/llvmorg-{LLVM_VERSION}"
# Exact asset filenames as published on the llvmorg-22.1.7 release page.
# Windows uses the MSVC tarball (clang+llvm-*-x86_64-pc-windows-msvc.tar.xz)
# rather than the NSIS installer; the CI workflow downloads the same archives
# (kept in sync with build-wheels.yml).
_RELEASES: Dict[str, Dict[str, str]] = {
    "darwin-arm64": {
        "url": f"{_RELEASE_BASE}/LLVM-{LLVM_VERSION}-macOS-ARM64.tar.xz",
        "sha256": "",
    },
    "linux-x86_64": {
        "url": f"{_RELEASE_BASE}/LLVM-{LLVM_VERSION}-Linux-X64.tar.xz",
        "sha256": "",
    },
    "linux-arm64": {
        "url": f"{_RELEASE_BASE}/LLVM-{LLVM_VERSION}-Linux-ARM64.tar.xz",
        "sha256": "",
    },
    "win32-x86_64": {
        "url": f"{_RELEASE_BASE}/clang+llvm-{LLVM_VERSION}-x86_64-pc-windows-msvc.tar.xz",
        "sha256": "",
    },
}


def _exe(name: str) -> str:
    return name + (".exe" if sys.platform == "win32" else "")


def _release_for_platform() -> Dict[str, str]:
    url = os.environ.get("PYMCU_RP2040_LLVM_URL")
    if url:
        return {"url": url, "sha256": os.environ.get("PYMCU_RP2040_LLVM_SHA256", "")}
    key = platform_key()
    rel = _RELEASES.get(key)
    if rel is None:
        raise RuntimeError(
            f"No pinned LLVM release for platform {key!r}. Set "
            f"PYMCU_RP2040_LLVM_URL to an archive, or use --from-dir with a "
            f"locally installed LLVM."
        )
    return rel


def _log(console, msg: str) -> None:
    if console is not None:
        console.print(msg)
    else:
        print(msg)


# --------------------------------------------------------------------------
# staging primitives
# --------------------------------------------------------------------------

def _copy_libs(src_lib: Path, dest_lib: Path) -> int:
    """Copy the LLVM runtime shared objects from *src_lib* into *dest_lib*."""
    if not src_lib.is_dir():
        return 0
    dest_lib.mkdir(parents=True, exist_ok=True)
    n = 0
    for glob in _LIB_GLOBS:
        for f in src_lib.glob(glob):
            # follow symlinks so the cache/bundle is self-contained
            if f.is_symlink():
                target = f.resolve()
                if target.exists():
                    shutil.copy2(target, dest_lib / f.name)
                    n += 1
            elif f.is_file():
                shutil.copy2(f, dest_lib / f.name)
                n += 1
    return n


def _stage_from_dir(
    src_root: Path,
    dest_bin: Path,
    dest_lib: Path,
    link: bool,
    console=None,
) -> None:
    """Stage tools from an installed LLVM tree rooted at *src_root* (has bin/)."""
    src_bin = src_root / "bin" if (src_root / "bin").is_dir() else src_root
    src_lib = (src_root / "lib") if (src_root / "lib").is_dir() else (src_bin.parent / "lib")

    missing = [t for t in TOOLS if not (src_bin / _exe(t)).exists()]
    if missing:
        raise RuntimeError(
            f"{src_bin} is missing required LLVM tools: {', '.join(missing)}"
        )

    dest_bin.mkdir(parents=True, exist_ok=True)
    for t in TOOLS:
        s = src_bin / _exe(t)
        d = dest_bin / _exe(t)
        if d.exists() or d.is_symlink():
            d.unlink()
        if link:
            d.symlink_to(s)
        else:
            shutil.copy2(s, d)
            d.chmod(0o755)
    if link:
        _log(console, f"[pymcu-rp2040-toolchain] linked {len(TOOLS)} tools -> {dest_bin}")
        return

    nlibs = _copy_libs(src_lib, dest_lib)
    _log(
        console,
        f"[pymcu-rp2040-toolchain] copied {len(TOOLS)} tools + {nlibs} shared "
        f"libs -> {dest_bin.parent}",
    )


def _verify_sha256(path: Path, expected: str) -> None:
    if not expected or os.environ.get("PYMCU_SKIP_HASH_CHECK") == "1":
        return
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    actual = h.hexdigest()
    if actual.lower() != expected.lower():
        raise RuntimeError(
            f"SHA-256 mismatch for {path.name}: expected {expected}, got {actual}"
        )


def _download_and_stage(dest_bin: Path, dest_lib: Path, console=None) -> None:
    rel = _release_for_platform()
    url, sha = rel["url"], rel.get("sha256", "")
    with tempfile.TemporaryDirectory(prefix="pymcu-llvm-") as td:
        tmp = Path(td)
        archive = tmp / "llvm.tar.xz"
        _log(console, f"[pymcu-rp2040-toolchain] downloading {url}")
        req = urllib.request.Request(url, headers={"User-Agent": "pymcu-rp2040-toolchain/1.0"})
        with urllib.request.urlopen(req, context=_ssl_context()) as resp, \
                open(archive, "wb") as fh:
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                fh.write(chunk)
        _verify_sha256(archive, sha)
        _log(console, "[pymcu-rp2040-toolchain] extracting ...")
        with tarfile.open(archive, "r:xz") as tf:
            tf.extractall(tmp)  # noqa: S202 -- official LLVM archive
        # The archive expands to a single top-level dir (clang+llvm-...).
        roots = [p for p in tmp.iterdir() if p.is_dir() and (p / "bin").is_dir()]
        if not roots:
            raise RuntimeError("Extracted LLVM archive has no bin/ directory.")
        _stage_from_dir(roots[0], dest_bin, dest_lib, link=False, console=console)


# --------------------------------------------------------------------------
# public entry point
# --------------------------------------------------------------------------

def fetch(
    target: str = "cache",
    from_dir: Optional[str] = None,
    link: bool = False,
    console=None,
) -> Path:
    """
    Populate the *target* (``"cache"`` or ``"bundle"``) with the LLVM tools.

    Returns the bin directory that now holds the tools.
    """
    if target == "bundle":
        dest_bin, dest_lib = bundled_bin_dir(), bundled_lib_dir()
    elif target == "cache":
        dest_bin, dest_lib = cache_bin_dir(), cache_tool_dir() / "lib"
    else:
        raise ValueError("target must be 'cache' or 'bundle'")

    if from_dir:
        _stage_from_dir(Path(from_dir).expanduser(), dest_bin, dest_lib, link, console)
    else:
        if link:
            raise ValueError("--link requires --from-dir")
        _download_and_stage(dest_bin, dest_lib, console)

    if target == "cache":
        (cache_tool_dir() / ".version").write_text(LLVM_VERSION)
    return dest_bin
