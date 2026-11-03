"""Wake-on-LAN: the magic packet for machines listed under `wol:` in config.yaml."""

import re
import socket

MAC = re.compile(r"^([0-9a-f]{2})([:-]?)([0-9a-f]{2})(?:\2([0-9a-f]{2})){4}$", re.I)


def parse_mac(mac):
    """'aa:bb:cc:dd:ee:ff', 'AA-BB-…' or 'aabbccddeeff' -> 6 bytes; ValueError otherwise."""
    m = (mac or "").strip()
    if not MAC.match(m):
        raise ValueError(f"bad MAC address: {mac!r}")
    return bytes.fromhex(re.sub(r"[:-]", "", m))


def magic_packet(mac):
    return b"\xff" * 6 + parse_mac(mac) * 16


def targets(cfg):
    """The configured machines that have a valid MAC, in config order."""
    out = []
    for i, t in enumerate(cfg.get("wol") or []):
        try:
            parse_mac(t.get("mac"))
        except (ValueError, AttributeError):
            continue
        out.append({"id": i, "name": t.get("name") or t["mac"], "mac": t["mac"],
                    "broadcast": t.get("broadcast") or "255.255.255.255", "port": int(t.get("port") or 9)})
    return out


def send(target):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(magic_packet(target["mac"]), (target["broadcast"], target["port"]))
