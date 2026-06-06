#!/usr/bin/env bash
# stage-llvm.sh -- slim an LLVM installation down to the five tools the PyMCU
# RP2040 backend needs, plus the shared libraries they load, into a self-
# contained <dest>/{bin,lib} tree suitable for RP2040T_TOOLCHAIN_DIR.
#
# Usage:
#   scripts/stage-llvm.sh <src-llvm-dir> <dest-dir>
#
#   <src-llvm-dir>  An extracted official LLVM release (has bin/ and lib/), a
#                   Homebrew keg (/opt/homebrew/opt/llvm), an MSYS2 /mingw64,
#                   etc.
#   <dest-dir>      Output directory; <dest-dir>/bin and <dest-dir>/lib are
#                   created/overwritten.
#
# The tools keep their default ../lib rpath, so bin/ + lib/ siblings are all
# that is required at runtime. On macOS any absolute Homebrew dylib references
# are rewritten to @rpath for portability (mirrors avr-gcc-build's
# bundle-macos-toolchain.sh).
set -euo pipefail

SRC="${1:?usage: stage-llvm.sh <src-llvm-dir> <dest-dir>}"
DEST="${2:?usage: stage-llvm.sh <src-llvm-dir> <dest-dir>}"

TOOLS=(opt llc llvm-mc ld.lld llvm-objcopy)
# Shared objects the LLVM CLI tools dlopen (globbed across platforms).
LIB_GLOBS=(libLLVM* libLTO* libc++* libc++abi* libunwind*)

EXE=""
case "${OS:-}${OSTYPE:-}" in *[Ww]indows*|*msys*|*cygwin*) EXE=".exe" ;; esac

src_bin="$SRC/bin"; [ -d "$src_bin" ] || src_bin="$SRC"
src_lib="$SRC/lib"; [ -d "$src_lib" ] || src_lib="$(dirname "$src_bin")/lib"

mkdir -p "$DEST/bin" "$DEST/lib"

echo "==> staging tools from $src_bin"
for t in "${TOOLS[@]}"; do
    f="$src_bin/${t}${EXE}"
    if [ ! -f "$f" ]; then
        echo "ERROR: required tool not found: $f" >&2
        exit 1
    fi
    cp -p "$f" "$DEST/bin/"
    echo "    + ${t}${EXE}"
done

echo "==> staging shared libraries from $src_lib"
nlibs=0
if [ -d "$src_lib" ]; then
    for glob in "${LIB_GLOBS[@]}"; do
        for f in "$src_lib"/$glob; do
            [ -e "$f" ] || continue
            # Resolve symlinks so the staged tree is self-contained.
            cp -pL "$f" "$DEST/lib/$(basename "$f")" 2>/dev/null || cp -p "$f" "$DEST/lib/"
            nlibs=$((nlibs + 1))
        done
    done
fi
# On Windows the DLLs usually live next to the executables.
for f in "$src_bin"/LLVM*.dll "$src_bin"/libLLVM*.dll; do
    [ -e "$f" ] || continue
    cp -p "$f" "$DEST/bin/"
    nlibs=$((nlibs + 1))
done
echo "    staged $nlibs shared libraries"

# macOS: rewrite any absolute dylib paths to @rpath and add a ../lib rpath.
if [ "$(uname -s 2>/dev/null)" = "Darwin" ]; then
    echo "==> fixing macOS rpaths"
    for t in "${TOOLS[@]}"; do
        bin="$DEST/bin/$t"
        [ -f "$bin" ] || continue
        install_name_tool -add_rpath "@loader_path/../lib" "$bin" 2>/dev/null || true
        while read -r dep; do
            case "$dep" in
                /opt/homebrew/*|/usr/local/*)
                    install_name_tool -change "$dep" "@rpath/$(basename "$dep")" "$bin" 2>/dev/null || true
                    ;;
            esac
        done < <(otool -L "$bin" | awk 'NR>1{print $1}')
    done
fi

# Strip debug symbols to stay under PyPI's 100 MB per-file limit.
# libLLVM.dylib alone is ~250 MB unstripped; strip brings it to ~70-90 MB.
# -x (macOS) = keep external symbols but remove debug; identical effect to
# --strip-debug on ELF. Windows MSVC DLLs are already release-stripped.
echo "==> stripping debug symbols"
_do_strip() {
    local f="$1"
    if [ "$(uname -s 2>/dev/null)" = "Darwin" ]; then
        strip -x "$f" 2>/dev/null || true
    else
        strip --strip-debug --strip-unneeded "$f" 2>/dev/null || true
    fi
}
for t in "${TOOLS[@]}"; do
    f="$DEST/bin/${t}${EXE}"
    [ -f "$f" ] && _do_strip "$f"
done
for f in "$DEST/lib"/libLLVM* "$DEST/lib"/libLTO* "$DEST/bin"/*.dll; do
    [ -f "$f" ] && _do_strip "$f"
done

echo "==> done: $DEST"
du -sh "$DEST/bin" "$DEST/lib" 2>/dev/null || ls -l "$DEST/bin"
