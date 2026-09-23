"""Updates from GitHub.

    python3 -m pveseat.update check          # print installed vs latest
    python3 -m pveseat.update apply          # download and install the latest version
    python3 -m pveseat.update auto           # apply only if update.auto is true (systemd timer)

Channel "release": the latest GitHub release (tag vX.Y.Z). Channel "main": the newest commit
of a branch. Git is not needed on the host: the source archive comes from codeload.github.com
and install.sh runs from it; /etc/pve-seat is never touched.
"""

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

import aiohttp

from . import config

INSTALL_DIR = os.environ.get("PVESEAT_INSTALL", "/opt/pve-seat")
API = "https://api.github.com/repos/{repo}"
UA = {"User-Agent": "pve-seat-updater", "Accept": "application/vnd.github+json"}


def _read(name, default=""):
    try:
        with open(os.path.join(INSTALL_DIR, name), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return default


def installed():
    return {"version": _read("VERSION", "0.0.0"), "commit": _read("COMMIT"), "repo": _read("REPO")}


def settings(cfg):
    u = dict(cfg.get("update") or {})
    u.setdefault("channel", "release")
    u.setdefault("branch", "main")
    u.setdefault("auto", False)
    u.setdefault("check_hours", 6)
    u["repo"] = _repo_slug(u.get("repo") or installed()["repo"])
    return u


def _repo_slug(repo):
    """'https://github.com/owner/name(.git)' or 'owner/name' -> 'owner/name'."""
    m = re.search(r"github\.com[/:]([^/]+/[^/.]+)", repo or "") or re.fullmatch(r"([\w.-]+/[\w.-]+)", repo or "")
    return m.group(1) if m else ""


def _ver(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "0")[:3])


async def latest(u):
    """{'ref', 'version', 'commit', 'url', 'notes', 'date'} of the newest available build."""
    async with aiohttp.ClientSession(headers=UA, timeout=aiohttp.ClientTimeout(total=15)) as s:
        if u["channel"] == "main":
            async with s.get(API.format(repo=u["repo"]) + f"/commits/{u['branch']}") as r:
                r.raise_for_status()
                c = await r.json()
            return {"ref": c["sha"], "commit": c["sha"], "version": None, "url": c["html_url"],
                    "notes": c["commit"]["message"].split("\n")[0], "date": c["commit"]["committer"]["date"]}
        async with s.get(API.format(repo=u["repo"]) + "/releases/latest") as r:
            if r.status == 200:
                rel = await r.json()
                return {"ref": rel["tag_name"], "commit": None, "version": rel["tag_name"].lstrip("v"),
                        "url": rel["html_url"], "notes": (rel.get("name") or rel["tag_name"]), "date": rel.get("published_at")}
            if r.status != 404:
                r.raise_for_status()
        # No GitHub release yet: a pushed tag vX.Y.Z is enough.
        async with s.get(API.format(repo=u["repo"]) + "/tags", params={"per_page": 100}) as r:
            r.raise_for_status()
            tags = [t for t in await r.json() if re.fullmatch(r"v?\d+(\.\d+){1,2}", t["name"])]
        if not tags:
            raise RuntimeError(f"{u['repo']}: no releases or version tags yet")
        best = max(tags, key=lambda t: _ver(t["name"]))
        return {"ref": best["name"], "commit": best["commit"]["sha"], "version": best["name"].lstrip("v"),
                "url": f"https://github.com/{u['repo']}/releases/tag/{best['name']}", "notes": best["name"], "date": None}


async def status(cfg):
    u = settings(cfg)
    cur = installed()
    out = {"enabled": bool(u["repo"]), "repo": u["repo"], "channel": u["channel"], "auto": u["auto"],
           "installed": cur, "available": False, "latest": None, "checked": int(time.time())}
    if not u["repo"]:
        return out
    new = await latest(u)
    out["latest"] = new
    if u["channel"] == "main":
        out["available"] = bool(new["commit"]) and not new["commit"].startswith(cur["commit"] or "-")
    else:
        out["available"] = _ver(new["version"]) > _ver(cur["version"])
    return out


def apply(cfg, ref=None):
    """Download the source for `ref` (or the latest) and run its install.sh. Blocking; runs as root."""
    u = settings(cfg)
    if not u["repo"]:
        sys.exit("update.repo is not set and the installation does not know its GitHub repository")
    st = asyncio.run(status(cfg))
    ref = ref or (st["latest"] or {}).get("ref")
    if not ref:
        sys.exit("nothing to install")
    work = tempfile.mkdtemp(prefix="pve-seat-update-")
    try:
        archive = os.path.join(work, "src.tar.gz")
        url = f"https://codeload.github.com/{u['repo']}/tar.gz/{ref}"
        print(f"downloading {url}")
        subprocess.run(["curl", "-fsSL", "-o", archive, url], check=True)
        with tarfile.open(archive) as t:
            try:
                t.extractall(work, filter="data")
            except TypeError:  # Python < 3.11.4 (PVE 8): no extraction filters
                t.extractall(work)
        src = next(os.path.join(work, d) for d in os.listdir(work) if os.path.isdir(os.path.join(work, d)))
        env = dict(os.environ, PVESEAT_COMMIT=(st["latest"] or {}).get("commit") or ref, PVESEAT_REPO=u["repo"])
        print(f"installing {ref} from {src}")
        subprocess.run(["bash", os.path.join(src, "install.sh")], check=True, env=env, cwd=src)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["check", "apply", "auto"])
    ap.add_argument("--ref", help="tag, branch or commit to install (apply only)")
    a = ap.parse_args()
    cfg = config.load()
    if a.action == "check":
        print(json.dumps(asyncio.run(status(cfg)), indent=1, ensure_ascii=False))
    elif a.action == "apply":
        apply(cfg, a.ref)
    else:
        u = settings(cfg)
        if not u["auto"]:
            print("update.auto is off")
            return
        st = asyncio.run(status(cfg))
        if st["available"]:
            apply(cfg)
        else:
            print("up to date")


if __name__ == "__main__":
    main()
