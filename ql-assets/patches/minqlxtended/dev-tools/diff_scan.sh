#!/bin/bash
# Diffs democut's test_scan --json against the vendored UDT oracle over a corpus.
set -u
NEW=/root/cutdev/democut/test_scan
OLD=/root/cutdev/udt_json
ok=0; bad=0; skipped=0
mkdir -p /root/cutdev/diffout
: > /root/cutdev/diffout/failures.txt
for f in "$@"; do
  b=$(basename "$f")
  $OLD "$f" > /root/cutdev/diffout/old.json 2>/root/cutdev/diffout/old.err
  orc=$?
  $NEW --json "$f" > /root/cutdev/diffout/new.json 2>/root/cutdev/diffout/new.err
  nrc=$?
  if [ $orc -ne 0 ] && [ $nrc -ne 0 ]; then skipped=$((skipped+1)); continue; fi
  if [ $orc -ne 0 ] || [ $nrc -ne 0 ]; then
    bad=$((bad+1)); echo "RC-MISMATCH $b old=$orc new=$nrc" >> /root/cutdev/diffout/failures.txt; continue
  fi
  if cmp -s /root/cutdev/diffout/old.json /root/cutdev/diffout/new.json; then ok=$((ok+1));
  else
    bad=$((bad+1))
    echo "DIFF $b" >> /root/cutdev/diffout/failures.txt
    cp /root/cutdev/diffout/old.json /root/cutdev/diffout/$b.old.json
    cp /root/cutdev/diffout/new.json /root/cutdev/diffout/$b.new.json
  fi
done
echo "identical=$ok differing=$bad both_failed=$skipped"
