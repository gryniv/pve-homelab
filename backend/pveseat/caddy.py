"""Web services discovered from Caddy's admin API and matched to PVE guests by IP."""

import json

from .util import pvesh, run


def _walk(handlers, acc):
    for h in handlers:
        if h.get("handler") == "reverse_proxy":
            acc += [u.get("dial", "") for u in h.get("upstreams", [])]
        for r in h.get("routes", []):
            _walk(r.get("handle", []), acc)


async def routes(cfg):
    c = cfg["caddy"]
    if not c.get("ct"):
        return []
    out = await run("pct", "exec", str(c["ct"]), "--", "curl", "-s", "-m", "5",
                    f"{c['admin']}/config/apps/http/servers", timeout=20)
    servers = json.loads(out or "{}")
    found = {}
    for srv in servers.values():
        for r in srv.get("routes", []):
            hosts = [h for m in r.get("match", []) for h in m.get("host", [])]
            ups = []
            _walk(r.get("handle", []), ups)
            for host in hosts:
                key = host.split(".")[0]
                if key in c.get("hide", []) or "*" in host:
                    continue
                prev = found.get(key)
                pref = c.get("prefer_suffix") or ""
                if prev and pref and prev["host"].endswith(pref) and not host.endswith(pref):
                    continue
                found[key] = {"key": key, "host": host, "upstream": ups[0] if ups else None}
    return list(found.values())


async def guest_ips(node, resources):
    """{ip: (type, vmid, name)} for running guests (all addresses, docker bridges skipped)."""
    ips = {}
    for g in resources:
        if g.get("status") != "running":
            continue
        vmid, typ = g["vmid"], g["type"]
        try:
            if typ == "lxc":
                ifs = await pvesh(f"/nodes/{node}/lxc/{vmid}/interfaces")
                addrs = [i.get("inet", "").split("/")[0] for i in ifs or []]
            else:
                res = await pvesh(f"/nodes/{node}/qemu/{vmid}/agent/network-get-interfaces")
                addrs = [a["ip-address"] for i in (res or {}).get("result", [])
                         for a in i.get("ip-addresses", []) if a.get("ip-address-type") == "ipv4"]
        except Exception:
            continue
        for a in addrs:
            if a and not a.startswith(("127.", "172.17.", "172.18.")):
                ips[a] = (typ, vmid, g.get("name"))
    return ips


def build(cfg, rts, ips, host_ip):
    meta = cfg.get("services", {})
    out = []
    for r in rts:
        m = meta.get(r["key"], {})
        up_ip = (r["upstream"] or "").rsplit(":", 1)[0]
        guest = ips.get(up_ip)
        if up_ip == host_ip:
            guest = ("node", 0, "host")
        out.append({
            "key": r["key"],
            "name": m.get("name") or r["key"].capitalize(),
            "desc": m.get("desc", ""),
            "icon": m.get("icon", r["key"]),
            "url": "https://" + r["host"],
            "host": r["host"],
            "upstream": r["upstream"],
            "guest": {"type": guest[0], "vmid": guest[1], "name": guest[2]} if guest else None,
        })
    return sorted(out, key=lambda s: s["name"].lower())
