"""Updates from GitHub.

    python3 -m pvehomelab.update check          # print installed vs latest
    python3 -m pvehomelab.update apply          # download and install the latest version
    python3 -m pvehomelab.update auto           # apply only if automatic updates are on (systemd timer)

Channel "release": the latest GitHub release (tag vX.Y.Z). Channel "main": the newest commit
of a branch. Git is not needed on the host: the source archive comes from codeload.github.com
and install.sh runs from it; /etc/pve-homelab is never touched.

Safety: a tag is resolved to its commit first and the archive of exactly that commit is installed
(a moved tag can't swap the code in between). install.sh puts the new version next to the old one
and keeps the old one as /opt/pve-homelab.prev; if the menu does not come back with the new version
within a minute, the old one is put back. The outcome is kept in /etc/pve-homelab/update-result.json.
Automatic updates follow releases only, unless update.auto_main allows any commit of the branch.
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

import urllib.request

import aiohttp

from . import config

INSTALL_DIR = os.environ.get("PVEHOMELAB_INSTALL", "/opt/pve-homelab")
API = "https://api.github.com/repos/{repo}"
# Where new versions come from unless config.yaml (update.repo) or the git clone says otherwise.
DEFAULT_REPO = "gryniv/pve-homelab"
UA = {"User-Agent": "pve-homelab-updater", "Accept": "application/vnd.github+json"}


def _read(name, default=""):
    try:
        with open(os.path.join(INSTALL_DIR, name), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return default


def installed():
    return {"version": _read("VERSION", "0.0.0"), "commit": _read("COMMIT"), "repo": _read("REPO")}


# Automatic updates can be switched in the menu (Settings → About, admins): the switch is kept here,
# next to config.yaml, and wins over its update.auto (config.yaml stays the admin's hand-written file).
MENU_FILE = "update-settings.json"


def _menu():
    try:
        with open(os.path.join(config.STATE_DIR, MENU_FILE), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    return {"auto": d["auto"]} if isinstance(d, dict) and isinstance(d.get("auto"), bool) else {}


def set_auto(on):
    """The menu's switch: install new releases by night (the pve-homelab-update timer), or not."""
    os.makedirs(config.STATE_DIR, exist_ok=True)
    p = os.path.join(config.STATE_DIR, MENU_FILE)
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump({"auto": bool(on)}, f)
    os.replace(p + ".tmp", p)


def settings(cfg):
    u = dict(cfg.get("update") or {})
    u.setdefault("channel", "release")
    u.setdefault("branch", "main")
    u.setdefault("auto", False)
    u.setdefault("auto_main", False)  # nightly install of whatever was pushed to the branch: opt-in only
    u.setdefault("check_hours", 6)
    u.update(_menu())
    u["repo"] = _repo_slug(u.get("repo") or installed()["repo"] or DEFAULT_REPO)
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
                async with s.get(API.format(repo=u["repo"]) + f"/commits/{rel['tag_name']}") as rc:
                    rc.raise_for_status()
                    sha = (await rc.json())["sha"]
                return {"ref": rel["tag_name"], "commit": sha, "version": rel["tag_name"].lstrip("v"),
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


RESULT_FILE = "update-result.json"


def last_result():
    try:
        with open(os.path.join(config.STATE_DIR, RESULT_FILE), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _save_result(**r):
    r["time"] = int(time.time())
    os.makedirs(config.STATE_DIR, exist_ok=True)
    p = os.path.join(config.STATE_DIR, RESULT_FILE)
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(r, f)
    os.replace(p + ".tmp", p)
    return r


async def status(cfg):
    u = settings(cfg)
    cur = installed()
    out = {"enabled": bool(u["repo"]), "repo": u["repo"], "channel": u["channel"], "auto": u["auto"],
           "installed": cur, "available": False, "latest": None, "checked": int(time.time()), "last": last_result()}
    if not u["repo"]:
        return out
    new = await latest(u)
    out["latest"] = new
    if u["channel"] == "main":
        out["available"] = bool(new["commit"]) and not new["commit"].startswith(cur["commit"] or "-")
    else:
        out["available"] = _ver(new["version"]) > _ver(cur["version"])
    return out


def archive_root(work, commit):
    """The single top directory of a codeload archive, checked to be of `commit`
    (codeload names it <repo>-<sha of the ref>)."""
    dirs = [d for d in os.listdir(work) if os.path.isdir(os.path.join(work, d))]
    if len(dirs) != 1:
        raise RuntimeError(f"unexpected archive layout: {dirs}")
    if commit and not dirs[0].endswith("-" + commit) and not dirs[0].endswith("-" + commit[:7]):
        raise RuntimeError(f"archive is {dirs[0]}, not commit {commit}")
    return os.path.join(work, dirs[0])


def _download(repo, commit, work):
    archive = os.path.join(work, "src.tar.gz")
    url = f"https://codeload.github.com/{repo}/tar.gz/{commit}"
    print(f"downloading {url}")
    subprocess.run(["curl", "-fsSL", "-o", archive, url], check=True)
    with tarfile.open(archive) as t:
        try:
            t.extractall(work, filter="data")
        except TypeError:  # Python < 3.11.4 (PVE 8): no extraction filters
            t.extractall(work)
    os.remove(archive)
    return archive_root(work, commit)


def _install(src, env):
    subprocess.run(["bash", os.path.join(src, "install.sh")], check=True, env=env, cwd=src)


def _healthy(cfg, want, timeout=60, interval=3):
    """The menu answers again, running the commit just installed (as /api/health reports it)."""
    port = cfg["listen"].rsplit(":", 1)[1]
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        time.sleep(interval)
        try:
            req = urllib.request.Request(config.menu_url(cfg) + "api/health", headers={"Host": f"127.0.0.1:{port}"})
            with urllib.request.urlopen(req, timeout=5) as r:
                if (json.load(r).get("commit") or "")[:7] == want[:7]:
                    return True
        except Exception:
            pass
    return False


def _restart():
    subprocess.run(["systemctl", "restart", "--no-block", "pve-homelab.service"], check=False)


def rollback():
    """Put /opt/pve-homelab.prev back in place; the failed version is kept as .failed."""
    prev, failed = INSTALL_DIR + ".prev", INSTALL_DIR + ".failed"
    if not os.path.isdir(prev):
        return False
    shutil.rmtree(failed, ignore_errors=True)
    if os.path.isdir(INSTALL_DIR):
        os.rename(INSTALL_DIR, failed)
    os.rename(prev, INSTALL_DIR)
    _restart()
    return True


def apply(cfg, ref=None):
    """Install `ref` (or the latest) and keep it only if the menu comes back with it. Blocking; runs as root."""
    u = settings(cfg)
    if not u["repo"]:
        sys.exit("update.repo is not set and the installation does not know its GitHub repository")
    st = asyncio.run(status(cfg))
    new = st["latest"] or {}
    ref = ref or new.get("ref")
    if not ref:
        sys.exit("nothing to install")
    commit = new.get("commit") if ref == new.get("ref") else None
    if not commit:  # an explicit --ref: pin it to a commit as well
        commit = asyncio.run(_commit_of(u["repo"], ref))
    before = installed()["commit"]
    work = tempfile.mkdtemp(prefix="pve-homelab-update-")
    try:
        try:
            src = _download(u["repo"], commit, work)
            env = dict(os.environ, PVEHOMELAB_COMMIT=commit, PVEHOMELAB_REPO=u["repo"])
            print(f"installing {ref} ({commit[:7]}) from {src}")
            _install(src, env)
        except Exception as e:
            swapped = installed()["commit"] == commit and before != commit
            back = rollback() if swapped else False
            _save_result(ref=ref, commit=commit, ok=False, rolled_back=back, error=str(e)[:500])
            raise
        if not _healthy(cfg, commit):
            back = rollback()
            _save_result(ref=ref, commit=commit, ok=False, rolled_back=back,
                         error="the menu did not come back with the new version")
            sys.exit(f"{ref}: the menu did not come back; " + ("previous version restored" if back else "no previous version to restore"))
        _save_result(ref=ref, commit=commit, ok=True, rolled_back=False, error="")
        print(f"{ref} installed")
    finally:
        shutil.rmtree(work, ignore_errors=True)


async def _commit_of(repo, ref):
    async with aiohttp.ClientSession(headers=UA, timeout=aiohttp.ClientTimeout(total=15)) as s:
        async with s.get(API.format(repo=repo) + f"/commits/{ref}") as r:
            r.raise_for_status()
            return (await r.json())["sha"]


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
            print("automatic updates are off (Settings → About, or update.auto in config.yaml)")
            return
        if u["channel"] == "main" and not u["auto_main"]:
            print("channel main: automatic install of any pushed commit needs update.auto_main: true")
            return
        st = asyncio.run(status(cfg))
        if st["available"]:
            apply(cfg)
        else:
            print("up to date")


if __name__ == "__main__":
    main()
