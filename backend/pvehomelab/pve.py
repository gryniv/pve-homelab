"""Proxmox API client. Every user action goes through the user's own ticket,
so PVE permissions decide what they can see and do."""

import asyncio
import json
import ssl
import time
from urllib.parse import quote, unquote

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


class TfaChallenge:
    """The password was right; Proxmox wants a second factor. `partial` is the half ticket that
    carries the challenge, `methods` what this account can answer with."""
    def __init__(self, user, partial, methods):
        self.user, self.partial, self.methods = user, partial, methods


# What the menu can take: codes typed on a keypad. WebAuthn (security keys) is bound to the Proxmox
# web UI's own origin and can only be answered there.
TFA_KINDS = ("totp", "recovery", "yubico")


def parse_challenge(partial):
    """Methods offered by a half ticket "PVE:<user>:!tfa!<url-encoded JSON>:..." (PVE 7.2+), e.g.
    {"totp": true, "recovery": "available", "webauthn": {...}}. Unknown shapes offer TOTP and a
    recovery key, the usual pair."""
    try:
        body = partial.split("!tfa!", 1)[1].split(":", 1)[0]
        d = json.loads(unquote(body))
        out = [k for k in ("totp", "yubico") if d.get(k)]
        if d.get("recovery") and d.get("recovery") != "unavailable":
            out.append("recovery")
        if d.get("webauthn") or d.get("u2f"):
            out.append("webauthn")
        return out or ["totp", "recovery"]
    except (IndexError, ValueError, AttributeError):
        return ["totp", "recovery"]


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
        """A Ticket, or a TfaChallenge when the account has a second factor."""
        s = await self.http()
        async with s.post(f"{API}/access/ticket", data={"username": username, "password": password}) as r:
            if r.status != 200:
                raise PVEError(401, _("bad_login"))
            d = (await r.json())["data"]
        if d.get("NeedTFA"):
            return TfaChallenge(d["username"], d["ticket"], parse_challenge(d["ticket"]))
        return Ticket(d["username"], d["ticket"], d["CSRFPreventionToken"])

    async def finish_tfa(self, ch, kind, code):
        """Answer the challenge with a code: "totp:123456", "recovery:<key>", "yubico:<otp>"."""
        s = await self.http()
        data = {"username": ch.user, "tfa-challenge": ch.partial, "password": f"{kind}:{code}"}
        async with s.post(f"{API}/access/ticket", data=data) as r:
            if r.status != 200:
                raise PVEError(401, _("bad_tfa"))
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
