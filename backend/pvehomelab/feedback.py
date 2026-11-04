"""Writing to the author: a GitHub issue filled in from the menu.

The menu composes the issue (what the person typed, and if they want, the versions and the latest
errors with names and addresses taken out), shows all of it before anything leaves the host, and
hands over a link: as a QR code to finish on a phone, or to open in a tab. Nothing is sent from the
host itself: the person submits the issue on GitHub, signed in as themselves.
"""

import platform
import re
import time
from urllib.parse import quote

from . import qr

KINDS = {"bug": "Bug", "idea": "Idea", "question": "Question"}
QR_MAX = 1200     # a longer link makes a QR code too dense for a phone to read off a screen
LINK_MAX = 7000   # GitHub turns away longer new-issue links
JOURNAL_MAX = 10  # entries at most, newest first
MSG_MAX = 240     # characters of each entry's message


# ---------------- taking names and addresses out ----------------
_EMAIL_OR_USER = re.compile(r"\b[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\b")
_URL_HOST = re.compile(r"\b((?:https?|wss?)://)[^/\s\"'<>()]+")
_MAC = re.compile(r"\b[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}\b")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b")
_IPV6 = re.compile(r"(?<![\w:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:])")
_LOCAL_NAME = re.compile(r"\b[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.(?:lan|local|home|internal|localdomain|home\.arpa|example)\b", re.I)
_HOME = re.compile(r"/home/[^/\s]+")


def _ipv6(m):
    s = m.group(0)
    # times (10:20:30) and the like are not addresses: an address has a hex letter or "::"
    return "<ip>" if "::" in s or re.search(r"[A-Fa-f]", s) else s


def scrub(text, known=()):
    """`text` without user names, host and guest names, addresses and home folders.
    `known`: [(name, placeholder)] this host knows of (its node, users, guests, services)."""
    out = text or ""
    for name, label in sorted(known, key=lambda x: -len(x[0])):
        if name and len(name) >= 3:
            out = re.sub(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", label, out, flags=re.I)
    out = _URL_HOST.sub(r"\1<host>", out)
    out = _EMAIL_OR_USER.sub("<user>", out)
    out = _MAC.sub("<mac>", out)
    out = _IPV4.sub("<ip>", out)
    out = _IPV6.sub(_ipv6, out)
    out = _LOCAL_NAME.sub("<host>", out)
    out = _HOME.sub("/home/<user>", out)
    return out


def journal_lines(entries, known=()):
    """The error journal, newest first, as short scrubbed lines."""
    lines = []
    for e in entries[:JOURNAL_MAX]:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(e.get("last") or e.get("time") or 0))
        msg = " ".join(str(e.get("msg") or "").split())
        if len(msg) > MSG_MAX:
            msg = msg[:MSG_MAX - 1] + "…"
        where = f" ({e['where']})" if e.get("where") else ""
        count = f" ×{e['count']}" if (e.get("count") or 1) > 1 else ""
        lines.append(scrub(f"{when} {e.get('level', 'error')} {e.get('source', '')}{count}: {msg}{where}", known))
    return lines


def browser(ua):
    """'Chrome 142 on Linux' from a user agent string (nothing more of it is sent)."""
    ua = ua or ""
    name = next((f"{n} {m.group(1)}" for n, pat in (("Firefox", r"Firefox/(\d+)"), ("Edge", r"Edg/(\d+)"),
                                                    ("Chrome", r"Chrom(?:e|ium)/(\d+)"), ("Safari", r"Version/(\d+).*Safari"))
                 if (m := re.search(pat, ua))), "")
    os_name = next((o for o in ("Android", "iPhone", "iPad", "Windows", "Mac OS X", "CrOS", "Linux") if o in ua), "")
    return " on ".join(x for x in (name, os_name.replace("Mac OS X", "macOS")) if x) or "unknown"


def environment(code, pve_version, client, demo=False):
    """What runs where, without names: versions, browser, screen, language."""
    client = client or {}
    ver = code.get("version") or "?"
    commit = (code.get("commit") or "")[:7]
    lines = [f"PVE Homelab {ver}" + (f" ({commit})" if commit else "") + (" — demo" if demo else ""),
             f"Proxmox VE {pve_version or '?'}",
             f"Python {platform.python_version()}",
             f"Browser: {browser(client.get('ua'))}"]
    screen = str(client.get("screen") or "")
    if re.fullmatch(r"\d{2,5}x\d{2,5}(@[\d.]+)?", screen):
        lines.append(f"Screen: {screen.replace('x', '×')}")
    lang = str(client.get("lang") or "")
    if re.fullmatch(r"[a-z]{2,3}(-[A-Za-z0-9]{2,8})?", lang):
        lines.append(f"Language: {lang}")
    return lines


def compose(repo, kind, title, text, env=None, journal=None, journal_total=0):
    """{title, body, url, qr, ...}: the issue as the person will see it on GitHub. The journal is
    cut from the oldest end until the link fits in a QR code."""
    kind = kind if kind in KINDS else "bug"
    title = " ".join(str(title or "").split())[:120]
    text = str(text or "").strip()[:4000]
    full_title = f"{KINDS[kind]}: {title}" if title else f"{KINDS[kind]}: "
    asked = journal is not None  # asked for, even if there is nothing in it
    journal = list(journal or [])
    total = max(journal_total, len(journal))

    def build(lines):
        parts = [text or "<!-- What happened, what you expected, or your idea. -->"]
        if env:
            parts.append("**Environment**\n" + "\n".join(f"- {x}" for x in env))
        if asked and not total:
            parts.append("**Error journal**: no errors recorded")
        elif lines:
            more = f"; {total - len(lines)} more in Settings → About" if total > len(lines) else ""
            parts.append(f"**Error journal** (newest first, names and addresses removed{more})\n```\n"
                         + "\n".join(lines) + "\n```")
        parts.append("<sub>Sent from PVE Homelab: Settings → About → Write to the author</sub>")
        body = "\n\n".join(parts)
        return body, f"https://github.com/{repo}/issues/new?title={quote(full_title)}&body={quote(body)}"

    body, url = build(journal)
    while journal and len(url) > QR_MAX:
        journal.pop()
        body, url = build(journal)
    fits = len(url) <= QR_MAX
    return {"title": full_title, "body": body, "url": url if len(url) <= LINK_MAX else None,
            "qr": qr.svg(qr.encode(url)) if fits else None, "too_long": len(url) > LINK_MAX,
            "journal_shown": len(journal), "journal_total": total}
