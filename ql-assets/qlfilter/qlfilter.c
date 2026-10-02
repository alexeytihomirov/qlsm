#include <linux/bpf.h>
#include <linux/if_ether.h>
#include <linux/in.h>
#include <linux/ip.h>
#include <linux/ipv6.h>
#include <linux/udp.h>

#include <stdint.h>

#define SEC(NAME) __attribute__((section(NAME), used))

#define htons(x) ((__be16)___constant_swab16((x)))
#define htonl(x) ((__be32)___constant_swab32((x)))

#define QL_PORT_MIN 27960
#define QL_PORT_MAX 27979

SEC("prog")
int xdp_drop_q3ql_udp_reflections(struct xdp_md *ctx)
{
	void *data_end = (void *)(long)ctx->data_end;
	void *data = (void *)(long)ctx->data;
	struct ethhdr *eth = data;

	uint64_t nh_off = sizeof(*eth);
	if (data + nh_off > data_end) {
		return XDP_PASS;
	}

	uint16_t h_proto = eth->h_proto;

	// IPv4 Inspection
	if (h_proto == htons(ETH_P_IP)) {
		struct iphdr *iph = data + nh_off;
		if ((void *)(iph + 1) > data_end) {
			return XDP_PASS;
		}
		if (iph->version != 4 || iph->ihl < 5) {
			return XDP_PASS;
		}
		uint32_t ip_header_len = (uint32_t)iph->ihl * 4;
		if ((void *)iph + ip_header_len > data_end) {
			return XDP_PASS;
		}
		struct udphdr *udph = (void *)iph + ip_header_len;
		if (udph + 1 > (struct udphdr *)data_end) {
			return XDP_PASS;
		}
		// Drop reflected traffic sent to QL ports. Source/A2S queries must pass:
		// Steam and in-game server browsers use them to list the server (#228).
		uint16_t dest_port = __be16_to_cpu(udph->dest);
		uint16_t src_port = __be16_to_cpu(udph->source);
		if (iph->protocol == IPPROTO_UDP &&
			dest_port >= QL_PORT_MIN && dest_port <= QL_PORT_MAX) {
			if (src_port <= 1024 || src_port == 1900) {
				return XDP_DROP;
			} else {
				return XDP_PASS;
			}
		}
		// If UDP packet is fragmented, drop it.
		if (iph->protocol == IPPROTO_UDP && iph->frag_off != 0) {
			return XDP_DROP;
		}
		// Pass all other traffic.
		return XDP_PASS;
	}
	// Pass anything else out of the above scope.
	return XDP_PASS;
}

char _license[] SEC("license") = "GPL";
