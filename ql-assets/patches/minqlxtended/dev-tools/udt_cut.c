// Development-only oracle: the vendored UDT bridge's demo_cut, same CLI as
// democut's test_cut, so the two outputs can be produced side by side.
// Usage: ./udt_cut <in.dm_91> <out_folder> <start_ms> <end_ms>
#include <stdio.h>
#include <stdlib.h>
#include "bridge.h"
int main(int argc, char **argv) {
    if (argc != 5) { fprintf(stderr, "usage: %s <in> <dir> <start> <end>\n", argv[0]); return 2; }
    char err[512];
    if (demo_cut(argv[1], argv[2], atoi(argv[3]), atoi(argv[4]), err, (int)sizeof(err)) != 0) {
        fprintf(stderr, "demo_cut failed: %s\n", err); return 1;
    }
    return 0;
}
