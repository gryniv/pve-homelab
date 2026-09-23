"""Proxmox API client. Every user action goes through the user's own ticket,
so PVE permissions decide what they can see and do."""

import asyncio
import ssl
import time
from urllib.parse import quote

import aiohttp

from .i18n import _

API = "https://127.0.0.1:8006/api2/json"


class PVEError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class Ticket:
    def __init__(self, user, ticket, csrf):
        self.user, self.ticket, self.csrf = user, ticket, csrf
        self.issued = time.time()


class PVE:
    def __init__(self):
        # Loopback only; the node certificate is self-signed.
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        self._ssl = ctx
        self._http = None

    async def http(self):
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                connector=aiohttp.TCPConnector(ssl=self._ssl),
            )
        return self._http

    async def close(self):
        if self._http:
            await self._http.close()

    async def login(self, username, password):
        s = await self.http()
        async with s.post(f"{API}/access/ticket", data={"username": username, "password": password}) as r:
            if r.status != 200:
                raise PVEError(401, _("bad_login"))
            d = (await r.json())["data"]
        return Ticket(d["username"], d["ticket"], d["CSRFPreventionToken"])

    async def renew(self, t: Ticket):
        """Tickets live 2 h; a valid ticket can be exchanged for a fresh one."""
        if time.time() - t.issued < 3600:
            return t
        fresh = await self.login(t.user, t.ticket)
        t.ticket, t.csrf, t.issued = fresh.ticket, fresh.csrf, fresh.issued
        return t

    async def req(self, t: Ticket, method, path, data=None):
        s = await self.http()
        headers = {"Cookie": f"PVEAuthCookie={quote(t.ticket, safe='')}"}
        if method != "GET":
            headers["CSRFPreventionToken"] = t.csrf
        kw = {"params": data} if method == "GET" else {"data": data or {}}
        async with s.request(method, API + path, headers=headers, **kw) as r:
            body = await r.json(content_type=None) if r.content_length != 0 else {}
            if r.status >= 400:
                msg = (body or {}).get("message") or r.reason
                if r.status == 403:
                    msg = _("forbidden")
                raise PVEError(r.status, msg.strip())
            return (body or {}).get("data")

    # `endpoint`, not `path`: PVE itself has a query parameter called "path" (/access/permissions).
    async def get(self, t, endpoint, **params):
        return await self.req(t, "GET", endpoint, params or None)

    async def post(self, t, endpoint, **data):
        return await self.req(t, "POST", endpoint, data)

    async def wait_task(self, t, node, upid, timeout=120):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            st = await self.get(t, f"/nodes/{node}/tasks/{quote(upid, safe='')}/status")
            if st.get("status") == "stopped":
                if st.get("exitstatus") != "OK":
                    raise PVEError(500, st.get("exitstatus") or _("task_failed"))
                return
            await asyncio.sleep(0.7)
        raise PVEError(504, _("task_slow"))

    async def can(self, t, path, priv):
        perms = await self.get(t, "/access/permissions", path=path)
        return bool((perms or {}).get(path, {}).get(priv))
