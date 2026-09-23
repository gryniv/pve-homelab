"""Service logos from homarr-labs/dashboard-icons, cached on disk."""

import os
import re

import aiohttp

from .config import CACHE_DIR

SRC = "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/svg/{}.svg"
_miss = set()


async def get(slug):
    if not re.fullmatch(r"[a-z0-9-]{1,60}", slug or ""):
        return None
    path = os.path.join(CACHE_DIR, "icons", slug + ".svg")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    if slug in _miss:
        return None
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as s:
            async with s.get(SRC.format(slug)) as r:
                if r.status != 200:
                    _miss.add(slug)
                    return None
                data = await r.read()
    except Exception:
        return None
    if b"<script" in data.lower():
        _miss.add(slug)
        return None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return data
