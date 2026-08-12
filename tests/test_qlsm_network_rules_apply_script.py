"""Regression guard for the 'helper' firewall mode NAT script.

Standalone and self-hosts (uses_helper_firewall() in self_host_network.py)
apply LAN-rate DNAT-to-loopback rules via this script, not the ansible 'full'
mode tasks. It must enable route_localnet on the actual external interface,
not just conf.all/default/lo -- conf.all is only a template applied to
interfaces created *after* the sysctl write, so an already-up NIC keeps
route_localnet=0 and the kernel silently drops the post-DNAT 127.0.0.1
packets. This black-holed all inbound game traffic on Slaughterhouse
(2026-08-12) even though iptables itself had already accepted the packets.
"""

from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "ansible" / "files" / "qlsm-network-rules-apply"


def test_script_enables_route_localnet_on_the_detected_default_interface():
    content = SCRIPT.read_text()

    assert "ip route" in content, "script must detect the real default interface"
    assert 'route_localnet=1' in content

    all_idx = content.index("net.ipv4.conf.all.route_localnet")
    iface_idx = content.index("route_localnet=1", content.index("DEFAULT_IFACE"))
    assert iface_idx > all_idx, (
        "per-interface route_localnet must be set (in addition to all/default/lo), "
        "otherwise DNAT-to-loopback silently drops on the real NIC"
    )
