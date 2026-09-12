#!/bin/bash
# Cuts every demo given on the command line with both cutters over several
# windows and compares the outputs byte for byte. A window is derived from each
# file's own server-time range, so the cases exercised are the ones the
# production two-stage cut actually asks for (open at arm, trim both ends, run
# to the end).
#
# Scratch directories are unique per run (mktemp) on purpose. An earlier version
# used fixed ./c1 and ./c2, and a second copy of this script left running in the
# background raced it: every comparison then diffed one demo's cut against an
# unrelated demo's, which looks exactly like a cutter bug and is not one. If a
# reported DIFF names two files that do not both derive from the source in the
# same line, suspect the harness, not the cutter.
set -u

NEW=${NEW:-/root/cutdev/democut/test_cut}
OLD=${OLD:-/root/cutdev/udt_cut}
SCAN=${SCAN:-/root/cutdev/democut/test_scan}
OUTDIR=${OUTDIR:-/root/cutdev/diffout}

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

mkdir -p "$OUTDIR"
: > "$OUTDIR/cut_failures.txt"

same=0; diffbytes=0; bothfail=0; onefail=0

for f in "$@"; do
  line=$($SCAN --json "$f" 2>/dev/null) || continue
  first=$(echo "$line" | sed 's/.*"first_ms":\([-0-9]*\).*/\1/')
  last=$(echo "$line" | sed 's/.*"last_ms":\([-0-9]*\).*/\1/')
  gs=$(echo "$line" | sed 's/.*"gamestate_count":\([-0-9]*\).*/\1/')
  span=$((last - first))
  [ $span -le 0 ] && continue
  q=$((span / 4))

  for w in "$first $last" "$((first+q)) $((last-q))" "$((first+span/2)) 2147483647" \
           "$first $((first+q))" "$((last-q)) $last"; do
    set -- $w
    s=$1; e=$2
    rm -rf "$work/old" "$work/new"; mkdir -p "$work/old" "$work/new"
    $OLD "$f" "$work/old" "$s" "$e" >/dev/null 2>&1; orc=$?
    $NEW "$f" "$work/new" "$s" "$e" >/dev/null 2>&1; nrc=$?
    o=$(ls "$work/old" 2>/dev/null | head -1)
    n=$(ls "$work/new" 2>/dev/null | head -1)

    if [ -z "$o" ] && [ -z "$n" ]; then
      bothfail=$((bothfail + 1)); continue
    fi
    if [ -z "$o" ] || [ -z "$n" ]; then
      onefail=$((onefail + 1))
      echo "ONEFAIL $(basename "$f") [$s,$e] udt='$o'($orc) new='$n'($nrc) gs=$gs" >> "$OUTDIR/cut_failures.txt"
      continue
    fi
    if cmp -s "$work/old/$o" "$work/new/$n" && [ "$o" = "$n" ]; then
      same=$((same + 1))
    else
      diffbytes=$((diffbytes + 1))
      echo "DIFF $(basename "$f") [$s,$e] names '$o' vs '$n' sizes $(stat -c%s "$work/old/$o") vs $(stat -c%s "$work/new/$n")" \
        >> "$OUTDIR/cut_failures.txt"
    fi
  done
done

echo "cuts: byte_identical=$same differing=$diffbytes one_side_failed=$onefail both_failed=$bothfail"
