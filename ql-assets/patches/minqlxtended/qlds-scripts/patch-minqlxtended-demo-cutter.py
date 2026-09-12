#!/usr/bin/env python3
"""Place src/democut/ into the build tree and add it to the Makefile's sources.

democut is this repo's own .dm_91 reader/cutter: a self-contained set of plain
C (gnu11) files implementing demo_scan()/demo_index()/demo_cut() for
src/features/demo_match.c. It replaces a 1.3 MB vendored C++ copy of
uberdemotools plus an extern "C" bridge, which this script used to wire in with
a whole parallel C++ toolchain - a `CXX = g++` compile rule, a second object
list, and a `$(CXX_LINK)` link step so libstdc++ resolved.

All of that is gone. The patch is now one line of Makefile: the sources join
COMMON_SOURCES and are built by the .c pattern rules that already exist.

Three consequences worth knowing:

1. `make debug` and `make nopy_debug` now get the cutter too. They never did
   before - the old patch only appended the C++ objects to OBJS and OBJS_NOPY -
   which meant those two targets could not link demo_match.c at all. The VPS
   build only ever runs `make clean all`, so nobody hit it, but it was a real
   hole and COMMON_SOURCES closes it for free.

2. No -I. is needed. The old udt/ tree lived at the build-tree ROOT (outside
   the stock Makefile's only -Isrc), which is why demo_match.c's include of it
   needed an extra include path. src/democut/ sits under src/, so
   `#include "democut/democut.h"` resolves with the flags upstream already has.
   patch-minqlxtended-item-respawn.py still adds -I. for its own build-tree-root
   header; that is now unrelated to this patch.

3. Ordering against patch-minqlxtended-demo-match.py is unchanged: this script
   must still run first, because demo_match.c calls demo_cut()/demo_scan()/
   demo_index() unconditionally and that script refuses to run if the cutter
   sources are not in the Makefile yet.

Like the old udt/ tree, src/democut/ does not exist in pristine upstream
tjone270/minqlxtended, and the real VPS build re-clones upstream from scratch
into $MINQLX_BUILD_DIR. So this is not a pure text patcher: the canonical copy
lives in this repo under minqlxtended-patches/democut/ and is materialised into
the build tree before the Makefile edit below names it - the same "copy the new
files in, then patch the Makefile that names them" pattern
patch-minqlxtended-item-events.py uses.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEMOCUT_SRC = REPO_ROOT / "minqlxtended-patches" / "democut"

# Where the sources land inside the build tree, relative to its root.
DEMOCUT_SUBDIR = Path("src") / "democut"

MARKER = "src/democut/democut.c"

# The library translation units, in dependency-ish order. Listed explicitly
# rather than wildcarded so the harnesses that ship next to them
# (test_scan.c/test_cut.c, each with its own main()) can never be pulled into
# the .so by accident - the old udt/ copy had exactly the same split.
DEMOCUT_SOURCES = (
    "src/democut/democut.c",
    "src/democut/dc_parser.c",
    "src/democut/dc_msg_read.c",
    "src/democut/dc_msg_write.c",
    "src/democut/dc_fields.c",
    "src/democut/dc_huffman.c",
)

# Anchor: the line right after the COMMON_SOURCES definition. Appending to
# COMMON_SOURCES here (rather than editing the definition itself) keeps
# patch-minqlxtended-demo-match.py's own anchor - the tail of that definition -
# byte-for-byte intact, so the two scripts cannot fight over the same text.
#
# It has to sit BEFORE this line, not after: GNU Make expands a rule's
# target/prerequisite text immediately, in file order, so anything feeding
# SOURCES/SOURCES_NOPY must already be defined by the time they are used.
OLD_ANCHOR = "SOURCES_NOPY += $(COMMON_SOURCES)"
NEW_ANCHOR = (
    "# democut: this repo's own .dm_91 reader/cutter (plain C, gnu11), which\n"
    "# src/features/demo_match.c calls for demo_scan()/demo_index()/demo_cut().\n"
    "# Appended to COMMON_SOURCES so all four targets build it - including the\n"
    "# two debug ones, which could not link demo_match.c before.\n"
    "COMMON_SOURCES += " + " \\\n                  ".join(DEMOCUT_SOURCES) + "\n\n"
    + OLD_ANCHOR
)


def copy_democut(build_dir: Path) -> int:
    """Materialise minqlxtended-patches/democut/ into <build_dir>/src/democut/.

    Content-compare per file rather than shutil.copytree()/copy2() over the
    whole tree unconditionally: copy2 rewrites mtime, and a rewritten .c/.h
    would force `make` to rebuild it on every install run even when nothing
    changed. Only genuinely differing (or missing) files are written, so a
    re-run of the installer is a no-op here - the same idempotency the Makefile
    edit below gets from MARKER.

    Nothing is ever deleted from the destination: `make clean`'s
    `$(RM) -r $(BUILDDIR)` already removes the objects, and a stray file left
    behind by an older revision cannot be compiled in anyway (the source list
    above is explicit).
    """
    if not DEMOCUT_SRC.is_dir():
        raise SystemExit(f"democut sources missing: {DEMOCUT_SRC}")
    dest_root = build_dir / DEMOCUT_SUBDIR
    copied = 0
    for src in sorted(DEMOCUT_SRC.rglob("*")):
        rel = src.relative_to(DEMOCUT_SRC)
        dest = dest_root / rel
        if src.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
            continue
        if dest.is_file() and dest.read_bytes() == src.read_bytes():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied += 1
    return copied


def patch_file(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if MARKER in text:
        return False
    if OLD_ANCHOR not in text:
        raise SystemExit(f"COMMON_SOURCES anchor missing/changed in {path}")
    text = text.replace(OLD_ANCHOR, NEW_ANCHOR, 1)
    path.write_text(text, encoding="utf-8")
    return True


def main() -> None:
    # Arguments may be either a minqlxtended-build *directory* (what
    # patch-minqlxtended-qlhub.py passes every patch script, and what this one
    # needs anyway - it has sources to place, not just a Makefile to edit) or a
    # path to the Makefile itself, for hand invocation.
    targets = [Path(p) for p in sys.argv[1:]] or [Path.home() / "minqlxtended-build"]
    for target in targets:
        if target.is_dir():
            build_dir, makefile = target, target / "Makefile"
        else:
            build_dir, makefile = target.parent, target
        if not makefile.is_file():
            print(f"skip (missing): {makefile}")
            continue
        copied = copy_democut(build_dir)
        dest = build_dir / DEMOCUT_SUBDIR
        print(
            f"democut sources up to date: {dest}"
            if copied == 0
            else f"copied {copied} democut file(s) -> {dest}"
        )
        if patch_file(makefile):
            print(f"patched demo-cutter build: {makefile}")
        else:
            print(f"already patched demo-cutter build: {makefile}")


if __name__ == "__main__":
    main()
