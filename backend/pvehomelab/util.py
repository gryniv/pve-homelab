import asyncio
import json
import logging
import time

log = logging.getLogger("pvehomelab")


async def run(*args, timeout=30, check=True):
    """Run a command, return stdout as text."""
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"{args[0]}: timeout")
    if check and proc.returncode != 0:
        raise RuntimeError(f"{' '.join(args)}: {err.decode(errors='replace').strip()}")
    return out.decode(errors="replace")


async def pvesh(endpoint, /, **params):
    """`pvesh get` as root. The endpoint is positional only: Proxmox has a parameter called
    "path" of its own (/access/permissions), which goes in **params."""
    args = ["pvesh", "get", endpoint, "--output-format", "json"]
    for k, v in params.items():
        args += [f"--{k}", str(v)]
    return json.loads(await run(*args, timeout=20) or "null")


async def pvesh_create(endpoint, /, **params):
    """`pvesh create` as root (POST), e.g. a command to a VM's QEMU monitor."""
    args = ["pvesh", "create", endpoint, "--output-format", "json"]
    for k, v in params.items():
        args += [f"--{k}", str(v)]
    return json.loads(await run(*args, timeout=20) or "null")


class Cached:
    """Async value refreshed at most every `ttl` seconds; failures keep the old value.
    With stale=True an expired value is returned at once and refreshed in the background."""

    # "Never" is -inf, not 0: monotonic() counts from boot, so on a machine up for less than `ttl`
    # (a fresh CI runner, a host just rebooted) 0 would still look recent.
    NEVER = float("-inf")

    def __init__(self, fn, ttl, stale=False):
        self.fn, self.ttl, self.stale = fn, ttl, stale
        self.value, self.at, self.lock = None, self.NEVER, asyncio.Lock()

    async def get(self):
        if time.monotonic() - self.at < self.ttl and self.value is not None:
            return self.value
        if self.stale and self.value is not None:
            if not self.lock.locked():
                asyncio.create_task(self._refresh())
            return self.value
        return await self._refresh()

    async def _refresh(self):
        async with self.lock:
            if time.monotonic() - self.at < self.ttl and self.value is not None:
                return self.value
            try:
                self.value = await self.fn()
            except Exception as e:  # keep serving stale data
                log.warning("refresh %s failed: %s", getattr(self.fn, "__name__", self.fn), e)
                if self.value is None:
                    raise
            self.at = time.monotonic()
            return self.value

    def invalidate(self):
        self.at = self.NEVER

    async def fresh(self):
        """The value worked out now, whatever the age of the one held (stale or not)."""
        self.at = self.NEVER
        return await self._refresh()
