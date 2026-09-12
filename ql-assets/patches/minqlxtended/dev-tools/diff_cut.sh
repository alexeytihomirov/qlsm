#!/bin/bash
# Cuts every demo in the corpus with both cutters over several windows and
# compares the outputs byte for byte. A window is derived from each file's own
# server-time range, so the cases exercised are the ones the production
# two-stage cut actually asks for (open at arm, trim both ends, run to the end).
set -u
NEW=/root/cutdev/democut/test_cut
OLD=/root/cutdev/udt_cut
SCAN=/root/cutdev/democut/test_scan
same=0; diffbytes=0; bothfail=0; onefail=0
: > /root/cutdev/diffout/cut_failures.txt
for f in "$@"; do
  line=$($SCAN --json "$f" 2>/dev/null) || continue
  first=$(echo "$line" | sed 's/.*"first_ms":\([-0-9]*\).*/\1/')
  last=$(echo "$line" | sed 's/.*"last_ms":\([-0-9]*\).*/\1/')
  gs=$(echo "$line" | sed 's/.*"gamestate_count":\([-0-9]*\).*/\1/')
  span=$((last-first))
  [ $span -le 0 ] && continue
  q=$((span/4))
  for w in "$first $last" "$((first+q)) $((last-q))" "$((first+span/2)) 2147483647" "$first $((first+q))" "$((last-q)) $last"; do
    set -- $w
    s=$1; e=$2
    rm -rf /root/cutdev/c1 /root/cutdev/c2; mkdir -p /root/cutdev/c1 /root/cutdev/c2
    $OLD "$f" /root/cutdev/c1 $s $e >/dev/null 2>&1; orc=$?
    $NEW "$f" /root/cutdev/c2 $s $e >/dev/null 2>&1; nrc=$?
    o=$(ls /root/cutdev/c1 2>/dev/null | head -1)
    n=$(ls /root/cutdev/c2 2>/dev/null | head -1)
    if [ -z "$o" ] && [ -z "$n" ]; then bothfail=$((bothfail+1)); continue; fi
    if [ -z "$o" ] || [ -z "$n" ]; then
      onefail=$((onefail+1)); echo "ONEFAIL $(basename $f) [$s,$e] udt='$o'($orc) new='$n'($nrc) gs=$gs" >> /root/cutdev/diffout/cut_failures.txt; continue
    fi
    if cmp -s "/root/cutdev/c1/$o" "/root/cutdev/c2/$n" && [ "$o" = "$n" ]; then same=$((same+1));
    else
      diffbytes=$((diffbytes+1))
      echo "DIFF $(basename $f) [$s,$e] names '$o' vs '$n' sizes $(stat -c%s /root/cutdev/c1/$o) vs $(stat -c%s /root/cutdev/c2/$n)" >> /root/cutdev/diffout/cut_failures.txt
    fi
  done
done
echo "cuts: byte_identical=$same differing=$diffbytes one_side_failed=$onefail both_failed=$bothfail"
