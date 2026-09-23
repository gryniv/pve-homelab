"""Error journal: warnings and errors from the backend and from the screens' browsers.

Everything logged at WARNING or above on the "pvehomelab" logger lands here, and so do reports
the browser sends to /api/client-log (JS errors, failed widgets, server errors it saw).
Entries go to a small in-memory ring (shown in Settings → About) and to a rotating file,
one JSON object per line: /var/log/pve-homelab/errors.log (in demo: <state>/logs/errors.log).
The same messages also reach the systemd journal through the normal logging setup.
"""

import collections
import json
import logging
import logging.handlers
import os
import threading
import time
import traceback

from .config import STATE_DIR

LOG_DIR = os.environ.get("PVEHOMELAB_LOGS") or ("/var/log/pve-homelab" if STATE_DIR == "/etc/pve-homelab" else os.path.join(STATE_DIR, "logs"))
LOG_FILE = os.path.join(LOG_DIR, "errors.log")

RING = collections.deque(maxlen=300)
_lock = threading.Lock()
_file = None
_rate = {}                 # seat -> [window start, count] for browser reports
DEDUPE_S = 60              # the same message again within a minute only bumps its counter
CLIENT_PER_MIN = 30


def _open_file():
    global _file
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        h = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(message)s"))
        _file = h
    except OSError as e:
        logging.getLogger("pvehomelab").info("error log file unavailable: %s", e)


def _write(entry):
    if _file:
        _file.emit(logging.makeLogRecord({"msg": json.dumps(entry, ensure_ascii=False), "levelno": logging.ERROR}))


def add(level, source, msg, detail="", seat="", user="", where=""):
    msg = (msg or "").strip()[:500] or "(empty)"
    now = time.time()
    with _lock:
        for e in reversed(RING):
            if now - e["last"] > DEDUPE_S:
                break
            if e["source"] == source and e["msg"] == msg and e["seat"] == seat:
                e["count"] += 1
                e["last"] = now
                return e
        entry = {"time": now, "last": now, "count": 1, "level": level, "source": source, "msg": msg,
                 "detail": (detail or "")[:4000], "seat": seat, "user": user, "where": (where or "")[:300]}
        RING.append(entry)
    _write(entry)
    return entry


class _Handler(logging.Handler):
    """Collects the backend's own warnings and errors."""

    def emit(self, record):
        if getattr(record, "from_client", False):
            return
        try:
            detail = "".join(traceback.format_exception(*record.exc_info)) if record.exc_info else ""
            add(record.levelname.lower(), "server", record.getMessage(), detail, where=f"{record.module}:{record.lineno}")
        except Exception:
            pass


def _load_tail():
    """Keep the journal across restarts: read the end of the file back into the ring."""
    try:
        with open(LOG_FILE, "rb") as f:
            f.seek(0, os.SEEK_END)
            start = max(0, f.tell() - 200_000)
            f.seek(start)
            lines = f.read().decode("utf-8", "replace").splitlines()
            if start:
                lines = lines[1:]      # the first line was cut in the middle
    except OSError:
        return
    for line in lines[-RING.maxlen:]:
        try:
            RING.append(json.loads(line))
        except ValueError:
            pass


def setup():
    _open_file()
    _load_tail()
    h = _Handler(level=logging.WARNING)
    logging.getLogger("pvehomelab").addHandler(h)


def client(report, seat, user):
    """A report from a screen's browser; rate-limited per seat."""
    now = time.time()
    win = _rate.setdefault(seat, [now, 0])
    if now - win[0] > 60:
        win[:] = [now, 0]
    win[1] += 1
    if win[1] > CLIENT_PER_MIN:
        return None
    kind = str(report.get("kind") or "js")[:20]
    e = add("error", "client:" + kind, str(report.get("msg") or ""), str(report.get("stack") or ""),
            seat=seat, user=user or "", where=str(report.get("where") or ""))
    logging.getLogger("pvehomelab").warning("browser %s on %s: %s", kind, seat, e["msg"], extra={"from_client": True})
    return e


def entries(limit=200):
    with _lock:
        return list(RING)[-limit:][::-1]


def clear():
    with _lock:
        RING.clear()
    try:
        open(LOG_FILE, "w").close()
    except OSError:
        pass
