"""Development backend: real host data, fake login, every action is a no-op.

Run ON the Proxmox host (never expose it):
    python3 tools/dryrun.py [--port 8901]
Trying the web seat (a browser behind the reverse proxy) needs an address beyond loopback; then
--allow must name exactly who may get in, since anyone signs in here with "test":
    python3 tools/dryrun.py --host 192.168.8.146 --allow 192.168.8.146
Log in with any listed user and the password "test": what that user may do comes from
Proxmox itself (root@pam: everything). Starting VMs, switching monitor inputs, changing
VM configs, the self-update and Wake-on-LAN are only logged.
"""

import argparse
import logging
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# Must be set before pvehomelab is imported: it reads these paths at import time.
# Per-user settings written during a dry run go to /tmp, never to /etc/pve-homelab/users.
os.environ["PVEHOMELAB_STATE"] = "/tmp/pve-homelab-dryrun"
os.environ.setdefault("PVEHOMELAB_WEB", os.path.join(HERE, "..", "web"))
os.environ.setdefault("PVEHOMELAB_DESIGNS", os.path.join(HERE, "..", "designs"))
for p in (os.path.join(HERE, "..", "backend"), "/opt/pve-homelab/backend"):
    if os.path.isdir(p):
        sys.path.insert(0, p)
        break

from aiohttp import web  # noqa: E402

from pvehomelab import app as A, ddc as D, launch as L, pve as P  # noqa: E402
from pvehomelab.util import pvesh  # noqa: E402


class DryPVE(P.PVE):
    async def login(self, username, password):
        if password != "test":
            raise P.PVEError(401, "dry-run: the password is 'test'")
        return P.Ticket(username or "root@pam", "dry", "dry")

    async def renew(self, t):
        return t

    async def get(self, t, endpoint, **params):
        if endpoint == "/access/permissions":
            # this user's real rights, so admin-only parts (updates, disks, the journal) show as they would
            try:
                return await pvesh(endpoint, path=params["path"], userid=t.user)
            except Exception as e:
                logging.warning("dry-run: no permissions for %s on %s: %s", t.user, params["path"], e)
                return {}
        return await pvesh(endpoint, **params)

    async def post(self, t, endpoint, **data):
        logging.warning("DRY-RUN POST %s %s", endpoint, data)
        if endpoint.endswith(("/vncproxy", "/termproxy")):   # nothing runs, so there is no screen to show
            raise P.PVEError(501, "dry run: a system's screen isn't available here")
        return "UPID:dry"

    async def wait_task(self, *a, **k):
        return


async def _noop(*a, **k):
    logging.warning("DRY-RUN %s", a[1:])
    return True


_real_run = A.run


async def _run(*args, **kw):
    if args and args[0] == "systemd-run":   # the self-update (POST /api/update/apply)
        logging.warning("DRY-RUN %s", " ".join(args))
        return ""
    return await _real_run(*args, **kw)


def _wake(target):
    logging.warning("DRY-RUN wake-on-lan %s (%s)", target.get("name"), target.get("mac"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8901)
    ap.add_argument("--host", default="127.0.0.1", help="where to listen; beyond loopback only with --allow")
    ap.add_argument("--allow", action="append", default=[], help="web.allow_from for this run (repeatable)")
    a = ap.parse_args()
    if a.host not in ("127.0.0.1", "localhost", "::1") and not a.allow:
        ap.error("--host beyond loopback needs --allow: in a dry run anyone signs in with \"test\"")
    L.Launcher._assign_gpu = _noop
    L.Launcher._to_virgl = _noop
    D.DDC.switch_to_gpu = _noop
    A.PVE = DryPVE
    A.run = _run
    A.wol.send = _wake
    logging.basicConfig(level=logging.INFO)
    app = A.make_app()
    if a.allow:
        app["cfg"]["web"] = {"enabled": True, "allow_from": a.allow}
    web.run_app(app, host=a.host, port=a.port, print=None, access_log=None)


if __name__ == "__main__":
    main()
