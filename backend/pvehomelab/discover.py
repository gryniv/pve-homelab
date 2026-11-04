"""Web UIs found without Caddy.

Three sources, merged with the Caddy list in app.build_services (Caddy wins on duplicates):
  ports  listening TCP sockets of every running container, read from the host
         (/proc/<container init>/net/tcp*): no exec into the guest, no network scan;
         VMs (IP from the guest agent) are probed on common web ports instead
  probe  each candidate gets GET /; only HTML answers count. The page title, the port
         and the guest name decide the app name and its logo
  notes  links written in a guest's Notes in Proxmox (plain or [text](url) markdown)
"""

import asyncio
import re
import ssl
from urllib.parse import unquote

import aiohttp

from .util import log, run

NOT_WEB = {21, 22, 23, 25, 53, 110, 111, 123, 139, 143, 389, 445, 465, 514, 587, 631, 636, 993, 995, 1883, 2049,
           3306, 3389, 5353, 5432, 5672, 5900, 6379, 8883, 9100, 11211, 27017}
VM_PORTS = [80, 443, 3000, 5000, 5001, 8000, 8006, 8007, 8080, 8081, 8096, 8123, 8443, 8888, 9000, 9090, 9443, 32400]
TLS_PORTS = {443, 5001, 8006, 8007, 8443, 9443}

# (pattern matched against "title guest-name", display name, dashboard-icons slug)
APPS = [
    (r"jellyfin", "Jellyfin", "jellyfin"), (r"\bplex\b", "Plex", "plex"), (r"immich", "Immich", "immich"),
    (r"nextcloud", "Nextcloud", "nextcloud"), (r"opencloud", "OpenCloud", "opencloud"),
    (r"vaultwarden|bitwarden", "Vaultwarden", "vaultwarden"), (r"home.?assistant", "Home Assistant", "home-assistant"),
    (r"adguard", "AdGuard Home", "adguard-home"), (r"pi-?hole", "Pi-hole", "pi-hole"), (r"grafana", "Grafana", "grafana"),
    (r"prometheus", "Prometheus", "prometheus"), (r"forgejo", "Forgejo", "forgejo"), (r"gitea", "Gitea", "gitea"),
    (r"gitlab", "GitLab", "gitlab"), (r"portainer", "Portainer", "portainer"), (r"uptime.?kuma", "Uptime Kuma", "uptime-kuma"),
    (r"proxmox backup|\bpbs\b", "Proxmox Backup Server", "proxmox"), (r"proxmox", "Proxmox", "proxmox"),
    (r"audiobookshelf", "Audiobookshelf", "audiobookshelf"), (r"calibre", "Calibre-Web", "calibre-web"),
    (r"komga", "Komga", "komga"), (r"paperless", "Paperless-ngx", "paperless-ngx"), (r"frigate", "Frigate", "frigate"),
    (r"\bn8n\b", "n8n", "n8n"), (r"open.?webui", "Open WebUI", "open-webui"), (r"sonarr", "Sonarr", "sonarr"),
    (r"radarr", "Radarr", "radarr"), (r"prowlarr", "Prowlarr", "prowlarr"), (r"lidarr", "Lidarr", "lidarr"),
    (r"jellyseerr", "Jellyseerr", "jellyseerr"), (r"overseerr", "Overseerr", "overseerr"), (r"qbittorrent", "qBittorrent", "qbittorrent"),
    (r"transmission", "Transmission", "transmission"), (r"syncthing", "Syncthing", "syncthing"), (r"netdata", "Netdata", "netdata"),
    (r"nginx proxy manager", "Nginx Proxy Manager", "nginx-proxy-manager"), (r"traefik", "Traefik", "traefik"),
    (r"zigbee2mqtt", "Zigbee2MQTT", "zigbee2mqtt"), (r"node-?red", "Node-RED", "node-red"), (r"mealie", "Mealie", "mealie"),
    (r"openclaw", "OpenClaw", "openclaw"), (r"bambu", "Bambu", "bambu-lab"), (r"langgraph", "LangGraph", ""),
    (r"cockpit", "Cockpit", "cockpit"), (r"webmin", "Webmin", "webmin"), (r"code-server|vs ?code", "code-server", "code-server"),
]
PORT_HINT = {8096: "jellyfin", 32400: "plex", 2283: "immich", 8123: "home assistant", 8006: "proxmox", 8007: "proxmox backup",
             13378: "audiobookshelf", 8083: "calibre", 25600: "komga", 9000: "portainer", 9443: "portainer",
             3001: "uptime kuma", 8989: "sonarr", 7878: "radarr", 9696: "prowlarr", 8686: "lidarr", 5055: "jellyseerr",
             8384: "syncthing", 19999: "netdata", 81: "nginx proxy manager", 1880: "node-red", 9090: "cockpit"}
LOOPBACK = {"0100007F", "00000000000000000000000001000000"}


NOT_A_UI = re.compile(r"^\s*(error|404|not found|forbidden|directory listing|index of /|welcome to nginx|it works)", re.I)


def identify(title, guest_name, port):
    """Name and logo. The page title is trusted first, then the guest's name, and only then the port number."""
    for hay in (title or "", guest_name or "", PORT_HINT.get(port, "")):
        for pat, name, icon in APPS:
            if hay and re.search(pat, hay.lower()):
                return name, icon
    clean = re.split(r"\s[|·\-–—:]\s", title or "")[0].strip()
    return (clean[:40] or guest_name or f"port {port}"), re.sub(r"[^a-z0-9-]+", "-", (guest_name or "").lower()).strip("-")


def parse_proc_net(text):
    """Ports listening on a non-loopback address in a /proc/net/tcp(6) table."""
    ports = set()
    for line in text.splitlines()[1:]:
        p = line.split()
        if len(p) < 4 or p[3] != "0A":  # LISTEN
            continue
        addr, port = p[1].split(":")
        if addr not in LOOPBACK:
            ports.add(int(port, 16))
    return ports


def _listening(pid):
    ports = set()
    for fam in ("tcp", "tcp6"):
        try:
            with open(f"/proc/{pid}/net/{fam}") as f:
                ports |= parse_proc_net(f.read())
        except OSError:
            pass
    return ports - NOT_WEB


async def _ct_ports(vmid):
    try:
        pid = (await run("lxc-info", "-n", str(vmid), "-pH", timeout=5)).strip()
        return _listening(pid) if pid.isdigit() else set()
    except Exception:
        return set()


_insecure = ssl.create_default_context()
_insecure.check_hostname = False
_insecure.verify_mode = ssl.CERT_NONE


async def _open(ip, port):
    """Cheap TCP check first: firewalled VMs drop packets and would stall every HTTP attempt."""
    try:
        _, w = await asyncio.wait_for(asyncio.open_connection(ip, port), 0.8)
        w.close()
        return True
    except (OSError, asyncio.TimeoutError):
        return False


async def probe(session, ip, port):
    """{'url', 'title'} if something on ip:port answers with an HTML page."""
    if not await _open(ip, port):
        return None
    schemes = ["https", "http"] if port in TLS_PORTS else ["http", "https"]
    for scheme in schemes:
        url = f"{scheme}://{ip}:{port}/"
        try:
            async with session.get(url, ssl=_insecure if scheme == "https" else None, allow_redirects=True,
                                   max_redirects=4, timeout=aiohttp.ClientTimeout(total=3)) as r:
                if r.status >= 500:
                    continue
                body = (await r.content.read(65536)).decode(errors="ignore")
                if "html" not in r.headers.get("Content-Type", "") and "<html" not in body[:2000].lower():
                    return None
                m = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
                title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
                if NOT_A_UI.match(title):
                    return None
                return {"url": url.rstrip("/"), "title": title}
        except (aiohttp.ClientError, asyncio.TimeoutError, UnicodeError, ValueError):
            continue
    return None


def _notes(typ, vmid):
    """A guest's Notes straight from its config in /etc/pve (the leading '#' lines, percent-encoded)."""
    path = f"/etc/pve/{'lxc' if typ == 'lxc' else 'qemu-server'}/{vmid}.conf"
    lines = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.startswith("#"):
                    break
                lines.append(unquote(line[1:].rstrip("\n")))
    except OSError:
        return ""
    return "\n".join(lines)


def _notes_links(desc):
    """[(text, url)] from a guest's Notes; markdown links keep their text."""
    out, seen = [], set()
    for text, url in re.findall(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", desc or ""):
        out.append((text.strip(), url)); seen.add(url)
    for url in re.findall(r"https?://[^\s)<>\"']+", desc or ""):
        url = url.rstrip(".,;")
        if url not in seen:
            out.append(("", url)); seen.add(url)
    return out


async def discover(cfg, resources, ips, host_ip=None):
    """Services found on guests. `ips` maps ip -> (type, vmid, name) for running guests."""
    d = cfg.get("discovery") or {}
    ignore = set(d.get("ignore") or [])
    by_guest = {}
    for ip, (typ, vmid, name) in ips.items():
        by_guest.setdefault((typ, vmid, name), []).append(ip)

    candidates = []  # (guest, ip, port)
    if d.get("ports", True):
        for (typ, vmid, name), addrs in by_guest.items():
            if typ == "lxc":
                ports = await _ct_ports(vmid)
            elif d.get("vms", True):
                ports = set(VM_PORTS)
            else:
                continue
            ip = sorted(addrs)[0]
            for port in sorted(ports):
                tag = f"{'ct' if typ == 'lxc' else 'vm'}{vmid}"
                if tag in ignore or f"{tag}:{port}" in ignore:
                    continue
                candidates.append(((typ, vmid, name), ip, port))
        if host_ip and "node" not in ignore:
            candidates.append((("node", 0, "proxmox"), host_ip, 8006))

    found = []
    sem = asyncio.Semaphore(24)
    async with aiohttp.ClientSession(headers={"User-Agent": "pve-homelab-discovery"}) as s:
        async def one(guest, ip, port):
            async with sem:
                hit = await probe(s, ip, port)
            if hit:
                name, icon = identify(hit["title"], guest[2], port)
                prefix = {"lxc": "ct", "qemu": "vm"}.get(guest[0], guest[0])
                found.append({"key": f"{prefix}{guest[1]}-{port}", "name": name, "icon": icon,
                              "desc": hit["title"], "url": hit["url"], "host": f"{ip}:{port}", "upstream": f"{ip}:{port}",
                              "guest": {"type": guest[0], "vmid": guest[1], "name": guest[2]}, "source": "port", "port": port})
        await asyncio.gather(*(one(*c) for c in candidates))

    if d.get("notes", True):
        for g in resources:
            if g.get("template"):
                continue
            for i, (text, url) in enumerate(_notes_links(_notes(g["type"], g["vmid"]))):
                host = re.sub(r"^\w+://", "", url).split("/")[0]
                name, icon = identify(text or host, g.get("name"), 0)
                found.append({"key": f"{'ct' if g['type'] == 'lxc' else 'vm'}{g['vmid']}-note{i}", "name": text or name,
                              "icon": icon, "desc": url, "url": url, "host": host, "upstream": None,
                              "guest": {"type": g["type"], "vmid": g["vmid"], "name": g.get("name")}, "source": "notes"})
    log.info("discovery: %d web UIs from %d candidates", len(found), len(candidates))
    return found


def _guest_port(s):
    g, up = s.get("guest"), s.get("upstream") or ""
    port = s.get("port") or (up.rsplit(":", 1)[1] if ":" in up else None)
    return (g["type"], g["vmid"], int(port)) if g and port and str(port).isdigit() else None


def merge(caddy_list, found):
    """Caddy entries first; a discovered UI is dropped if Caddy already proxies that guest's port
    (a guest may have several IPs) or the same URL."""
    covered = {_guest_port(s) for s in caddy_list} | {s["url"] for s in caddy_list}
    out = [dict(s, source=s.get("source") or ("link" if not s.get("upstream") else "caddy")) for s in caddy_list]
    for s in found:
        gp = _guest_port(s)
        if (gp and gp in covered) or s["url"] in covered:
            continue
        covered |= {gp, s["url"]}
        out.append(s)
    return sorted(out, key=lambda s: (s["source"] != "caddy", s["name"].lower()))
