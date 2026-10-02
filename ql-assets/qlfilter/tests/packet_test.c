/* Host-side packet regression tests; not a BPF verifier test. */
#include <linux/bpf.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

/* Preserve host pointers instead of the kernel context's 32-bit addresses. */
struct test_xdp_md { uintptr_t data; uintptr_t data_end; };
#define xdp_md test_xdp_md
#include "../qlfilter.c"
#undef xdp_md

/* Source/A2S info query; browsers send it to the game port to list servers. */
static const uint8_t source_engine_query[] = {
    0xff, 0xff, 0xff, 0xff,
    'T', 'S', 'o', 'u', 'r', 'c', 'e', ' ',
    'E', 'n', 'g', 'i', 'n', 'e', ' ', 'Q', 'u', 'e', 'r', 'y',
};

static int failures;
static int checks;

static void check(const char *name, unsigned port, unsigned ihl,
                  unsigned source, int query, unsigned length, int expected)
{
    /* Offset Ethernet so the IPv4 and UDP headers are naturally aligned. */
    _Alignas(8) unsigned char storage[258] = {0};
    unsigned char *packet = storage + 2;
    struct ethhdr *eth = (void *)packet;
    struct iphdr *ip = (void *)(packet + sizeof(*eth));
    unsigned header_size = ihl >= 5 ? ihl * 4 : 20;
    struct udphdr *udp = (void *)((unsigned char *)ip + header_size);
    eth->h_proto = htons(ETH_P_IP);
    ip->version = 4;
    ip->ihl = ihl;
    ip->protocol = IPPROTO_UDP;
    ip->tot_len = htons(header_size + sizeof(*udp) + 25);
    udp->source = htons(source);
    udp->dest = htons(port);
    udp->len = htons(sizeof(*udp) + 25);
    if (query)
        memcpy(udp + 1, source_engine_query, sizeof(source_engine_query));
    else
        memcpy(udp + 1, "\xff\xff\xff\xffgetstatus", 13);
    struct test_xdp_md ctx = {
        .data = (uintptr_t)packet,
        .data_end = (uintptr_t)packet +
            (length ? length : sizeof(*eth) + header_size + sizeof(*udp) + 25),
    };
    int actual = xdp_drop_q3ql_udp_reflections(&ctx);
    checks++;
    if (actual != expected) {
        fprintf(stderr, "%s (port %u, IHL %u): expected %d, got %d\n",
                name, port, ihl, expected, actual);
        failures++;
    }
}

int main(void)
{
    for (unsigned port = 0; port <= 65535; port++)
        check("query port scope", port, 5, 45000, 1, 0, XDP_PASS);
    for (unsigned ihl = 5; ihl <= 15; ihl++) {
        check("query with options", 27960, ihl, 45000, 1, 0, XDP_PASS);
        check("query upper boundary", 27979, ihl, 45000, 1, 0, XDP_PASS);
        check("legitimate query", 27960, ihl, 45000, 0, 0, XDP_PASS);
        check("DNS reflection", 27960, ihl, 53, 0, 0, XDP_DROP);
        check("SSDP reflection", 27960, ihl, 1900, 0, 0, XDP_DROP);
        check("outside range", 40000, ihl, 45000, 1, 0, XDP_PASS);
    }
    for (unsigned ihl = 0; ihl < 5; ihl++)
        check("invalid IHL", 27960, ihl, 45000, 1, 0, XDP_PASS);
    for (unsigned length = 1; length < 42; length++)
        check("truncated headers", 27960, 5, 45000, 1, length, XDP_PASS);
    check("truncated IP options", 27960, 15, 45000, 1, 60, XDP_PASS);
    check("truncated UDP after options", 27960, 6, 45000, 1, 44, XDP_PASS);
    check("short signature", 27960, 5, 45000, 1, 65, XDP_PASS);
    printf("%d checks, %d failures\n", checks, failures);
    return failures != 0;
}
