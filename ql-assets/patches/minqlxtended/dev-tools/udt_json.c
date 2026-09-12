// Development-only oracle: prints the SAME JSON as democut's test_scan --json,
// but produced by the vendored uberdemotools bridge this work replaces.
//
// Not part of the shipped patch set and not referenced by any build: it exists
// so "does the new cutter agree with the old one" can be answered by diffing
// two lines of text over a real demo corpus, instead of by reading code. Build
// it against a checkout that still has minqlxtended-patches/udt/:
//
//     g++ -std=c++14 -O2 -Iudt/include -Iudt/src -c udt/src/*.cpp udt/bridge.cpp
//     gcc -std=gnu11 -O2 -Iudt -c udt_json.c -o udt_json.o
//     g++ *.o -o udt_json -lstdc++ -lpthread
//
// Usage: ./udt_json <demo.dm_91> [arm_seq]

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bridge.h"

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: %s <demo.dm_91> [arm_seq]\n", argv[0]);
        return 2;
    }
    const char *path  = argv[1];
    const int arm_seq = (argc > 2) ? atoi(argv[2]) : -1;

    char err[512];

    // demo_scan is run with the caller's arm_seq (arm_ms/live_ms only exist
    // there); demo_index always runs with -1 internally, exactly like the new
    // implementation, so the two JSON lines line up field for field.
    demo_scan_t scan;
    if (demo_scan(path, arm_seq, &scan, err, (int)sizeof(err)) != 0) {
        fprintf(stderr, "demo_scan failed: %s\n", err);
        return 1;
    }

    demo_index_result_t idx;
    if (demo_index(path, &idx, err, (int)sizeof(err)) != 0) {
        fprintf(stderr, "demo_index failed: %s\n", err);
        return 1;
    }

    printf("{\"file\":\"%s\",\"arm_seq\":%d,", path, arm_seq);
    printf("\"first_ms\":%d,\"last_ms\":%d,\"arm_ms\":%d,\"live_ms\":%d,", scan.first_ms, scan.last_ms,
           scan.arm_ms, scan.live_ms);
    printf("\"gamestate_count\":%d,\"clock_resets\":%d,\"clock_resets_since_arm\":%d,",
           scan.gamestate_count, scan.clock_resets, scan.clock_resets_since_arm);
    printf("\"snapshot_count\":%d,\"message_count\":%d,\"client_num\":%d,", scan.snapshot_count,
           scan.message_count, scan.client_num);
    printf("\"delta_unknown\":%d,\"snapshots\":[", idx.delta_unknown);
    for (int i = 0; i < idx.count; i++) {
        const demo_snap_t *r = &idx.snaps[i];
        printf("%s{\"t\":%d,\"off\":%lld,\"len\":%d,\"delta\":%d}", i ? "," : "", r->t, r->off, r->len,
               r->delta);
    }
    printf("]}\n");

    demo_index_free(&idx);
    return 0;
}
