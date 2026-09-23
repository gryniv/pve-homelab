"""Development backend: real host data, fake login, every action is a no-op.

Run ON the Proxmox host (never expose it):
    python3 tools/dryrun.py [--port 8901]
Log in with any listed user and the password "test". Starting VMs, switching
monitor inputs and changing VM configs are only logged.
"""

import argparse
import logging
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# Must be set before pveseat is imported: it reads these paths at import time.
# Per-user settings written during a dry run go to /tmp, never to /etc/pve-seat/users.
os.environ["PVESEAT_STATE"] = "/tmp/pve-seat-dryrun"
os.environ.setdefault("PVESEAT_WEB", os.path.join(HERE, "..", "web"))
for p in (os.path.join(HERE, "..", "backend"), "/opt/pve-seat/backend"):
    if os.path.isdir(p):
        sys.path.insert(0, p)
        break

from aiohttp import web  # noqa: E402

from pveseat import app as A, ddc as D, launch as L, pve as P  # noqa: E402
from pveseat.util import pvesh  # noqa: E402


class DryPVE(P.PVE):
    async def login(self, username, password):
        if password != "test":
            raise P.PVEError(401, "dry-run: the password is 'test'")
        return P.Ticket(username or "root@pam", "dry", "dry")

    async def renew(self, t):
        return t

    async def get(self, t, endpoint, **params):
        if endpoint == "/access/permissions":
            return {params["path"]: {"VM.PowerMgmt": 1, "VM.Config.HWType": 1}}
        return await pvesh(endpoint, **params)

    async def post(self, t, endpoint, **data):
        logging.warning("DRY-RUN POST %s %s", endpoint, data)
        return "UPID:dry"

    async def wait_task(self, *a, **k):
        return


async def _noop(*a, **k):
    logging.warning("DRY-RUN %s", a[1:])
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8901)
    a = ap.parse_args()
    L.Launcher._assign_gpu = _noop
    L.Launcher._to_virgl = _noop
    D.DDC.switch_to_gpu = _noop
    A.PVE = DryPVE
    logging.basicConfig(level=logging.INFO)
    web.run_app(A.make_app(), host="127.0.0.1", port=a.port, print=None, access_log=None)


if __name__ == "__main__":
    main()
