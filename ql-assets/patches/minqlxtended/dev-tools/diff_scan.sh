#!/bin/bash
# Diffs democut's test_scan --json against the vendored UDT oracle over a corpus.
# One line of JSON per file, compared verbatim - it carries every field the
# acceptance criteria name plus the whole snapshot index, so a match is a strong
# statement and a mismatch points at the exact row.
#
# Scratch files are unique per run (mktemp): two copies of this script sharing
# one temp file would compare one demo's output against another's. See the same
# note in diff_cut.sh.
set -u

NEW=${NEW:-/root/cutdev/democut/test_scan}
OLD=${OLD:-/root/cutdev/udt_json}
OUTDIR=${OUTDIR:-/root/cutdev/diffout}

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

mkdir -p "$OUTDIR"
: > "$OUTDIR/failures.txt"

ok=0; bad=0; skipped=0

for f in "$@"; do
  b=$(basename "$f")
  $OLD "$f" > "$work/old.json" 2> "$work/old.err"; orc=$?
  $NEW --json "$f" > "$work/new.json" 2> "$work/new.err"; nrc=$?

  if [ $orc -ne 0 ] && [ $nrc -ne 0 ]; then
    skipped=$((skipped + 1)); continue
  fi
  if [ $orc -ne 0 ] || [ $nrc -ne 0 ]; then
    bad=$((bad + 1))
    echo "RC-MISMATCH $b old=$orc new=$nrc" >> "$OUTDIR/failures.txt"
    continue
  fi
  if cmp -s "$work/old.json" "$work/new.json"; then
    ok=$((ok + 1))
  else
    bad=$((bad + 1))
    echo "DIFF $b" >> "$OUTDIR/failures.txt"
    cp "$work/old.json" "$OUTDIR/$b.old.json"
    cp "$work/new.json" "$OUTDIR/$b.new.json"
  fi
done

echo "identical=$ok differing=$bad both_failed=$skipped"
