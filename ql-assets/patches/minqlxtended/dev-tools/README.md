# dev-tools - the uberdemotools differential oracle

Not part of the patch chain. Nothing here is copied into a build tree, compiled
into `minqlxtended.so`, or run in production. These four files exist so the one
claim that matters about `minqlxtended-patches/democut/` can be re-checked by
anyone, at any time, instead of being taken on trust:

> the C cutter that replaced the vendored uberdemotools produces the same
> answers on real demos.

## What was measured, and what came out

Against 125 real `.dm_91` files from the test server's own demo directory
(`/home/ql/qlds-27960/demos`, a mix of shipped per-POV files and raw
upstream-named captures, several with a mid-file server-clock reset):

| comparison | cases | result |
|---|---|---|
| `demo_scan` + `demo_index`, `arm_seq = -1` | 125 files | JSON identical, including every one of the ~24 000 index rows per file (`t`/`off`/`len`/`delta`) |
| `demo_scan`, `arm_seq` ∈ {0, 1, 5, 100, 1000, 5000, 20000, 100000} | 1000 runs | identical, including `arm_ms` / `live_ms` / `clock_resets_since_arm` |
| `demo_cut`, 5 windows derived from each file's own range | 545 cuts | **output files byte-for-byte identical**, same chosen filename |
| `demo_cut` on the 4 negative-span (clock-reset) files, 5 hand-picked windows | 20 cuts | byte-for-byte identical |

Byte identity was not the goal - the acceptance criterion was only semantic
agreement on `first_ms`/`last_ms`/`snapshot_count`/`deltaNum` - but it is what
happened, on every single case. It follows that a demo cut by democut is the
same file the vendored cutter would have produced, so anything that played
before still plays.

## Reproducing it

The oracle needs the vendored `udt/` tree, which this commit deletes. Recover it
from git first:

```bash
git show <commit-before-this-one>:ql-assets/patches/minqlxtended/minqlxtended-patches/udt > /dev/null  # sanity
git worktree add /tmp/pre-democut <commit-before-this-one>
cp -r /tmp/pre-democut/ql-assets/patches/minqlxtended/minqlxtended-patches/udt .
```

Then, on a machine with gcc/g++ and a demo corpus (the test server has both):

```bash
# 1. the oracle: vendored UDT + the two harnesses here
mkdir udtbuild && cd udtbuild
ls ../udt/src/*.cpp ../udt/bridge.cpp | xargs -P "$(nproc)" -I{} \
    sh -c 'g++ -std=c++14 -O2 -fPIC -Wno-invalid-offsetof -I../udt/include -I../udt/src -c {} -o $(basename {} .cpp).o'
gcc -std=gnu11 -O2 -I../udt -c ../udt_json.c -o udt_json_main.o
gcc -std=gnu11 -O2 -I../udt -c ../udt_cut.c  -o udt_cut_main.o
g++ $(ls *.o | grep -v udt_cut_main.o)  -o ../udt_json -lstdc++ -lpthread
g++ $(ls *.o | grep -v udt_json_main.o) -o ../udt_cut  -lstdc++ -lpthread
cd ..

# 2. the new cutter's own harnesses
cd democut
gcc -std=gnu11 -O2 -Wall -Wextra -o test_scan \
    test_scan.c democut.c dc_parser.c dc_msg_read.c dc_msg_write.c dc_fields.c dc_huffman.c
gcc -std=gnu11 -O2 -Wall -Wextra -o test_cut \
    test_cut.c  democut.c dc_parser.c dc_msg_read.c dc_msg_write.c dc_fields.c dc_huffman.c
cd ..

# 3. the diffs (both scripts expect ./udt_json, ./udt_cut and ./democut/test_*)
./diff_scan.sh /path/to/demos/*.dm_91
./diff_cut.sh  /path/to/demos/*.dm_91
```

`diff_scan.sh` compares one line of JSON per file; `diff_cut.sh` cuts each file
with both cutters over five windows derived from its own server-time range and
compares the outputs with `cmp`. Both print a one-line tally and append details
to `diffout/failures.txt` / `diffout/cut_failures.txt`.

## Files

| file | what it is |
|---|---|
| `udt_json.c` | prints `demo_scan` + `demo_index` results through the vendored bridge, in exactly the JSON `democut/test_scan --json` prints |
| `udt_cut.c` | `demo_cut` through the vendored bridge, same CLI as `democut/test_cut` |
| `diff_scan.sh` | reading-side differ over a corpus |
| `diff_cut.sh` | cutting-side differ over a corpus |
