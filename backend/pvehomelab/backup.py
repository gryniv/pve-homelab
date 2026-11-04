"""A copy of the menu's settings, and putting one back.

What lives in /etc/pve-homelab is outside /etc/pve, so neither vzdump nor Proxmox Backup Server takes
it. A copy is a .tar.gz with a manifest; it has parts that can be put back on their own:

  users   every person's settings (users/*.yaml)
  looks   designs and widgets installed in the menu (designs/, widgets/)
  host    the sign-in screen, what was changed in Settings → System, what VirGL kept of VMs
  config  config.yaml itself (seats, monitors: this host's hardware)

Before anything is put back, the current state is saved to backups/pre-import-<time>.tar.gz (the
last five are kept), so a restore can itself be undone.

    python3 -m pvehomelab.backup export [-o FILE]
    python3 -m pvehomelab.backup inspect FILE
    python3 -m pvehomelab.backup import FILE [--only users,looks,host,config]
"""

import argparse
import hashlib
import io
import json
import os
import re
import socket
import sys
import tarfile
import time

import yaml

from . import config

FORMAT = 1
PARTS = ("users", "looks", "host", "config")
MAX_FILES, MAX_BYTES, MAX_FILE = 500, 20 * 1024 * 1024, 4 * 1024 * 1024
KEEP_SNAPSHOTS = 5
NAME = re.compile(r"^[A-Za-z0-9@._-]{1,128}$")
LOOK_EXT = (".css", ".js", ".json", ".md", ".txt", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".woff", ".woff2")
# a key like these in config.yaml is never put in a copy
SECRET_KEY = re.compile(r"(token|password|passwd|secret|api_?key)", re.I)


class BadCopy(ValueError):
    pass


def _roots():
    """Archive prefix -> folder on this host."""
    st = config.STATE_DIR
    return {"users/": os.path.join(st, "users"), "designs/": config.USER_DESIGNS_DIR,
            "widgets/": config.USER_WIDGETS_DIR, "launch/": os.path.join(st, "launch")}


def part_of(name):
    """Which part a file of a copy belongs to, or None if a copy has no business holding it."""
    segs = name.split("/")
    if any(s in ("", ".", "..") or not NAME.match(s) for s in segs):
        return None
    if name == "config.yaml":
        return "config"
    if name in ("login.yaml", "settings.yaml"):
        return "host"
    if segs[0] == "users" and len(segs) == 2 and name.endswith(".yaml"):
        return "users"
    if segs[0] == "launch" and len(segs) == 2 and re.fullmatch(r"\d{3,9}\.json", segs[1]):
        return "host"
    if segs[0] in ("designs", "widgets") and 2 <= len(segs) <= 6 and name.lower().endswith(LOOK_EXT):
        return "looks"
    return None


def _host_path(name):
    for prefix, root in _roots().items():
        if name.startswith(prefix):
            return os.path.join(root, name[len(prefix):])
    return os.path.join(config.STATE_DIR, name)


def _scrub_config(data):
    """config.yaml without anything that looks like a secret (none should be there, but just in case)."""
    try:
        d = yaml.safe_load(data) or {}
    except yaml.YAMLError:
        return data
    def clean(x):
        if isinstance(x, dict):
            return {k: ("" if isinstance(k, str) and SECRET_KEY.search(k) else clean(v)) for k, v in x.items()}
        if isinstance(x, list):
            return [clean(v) for v in x]
        return x
    cleaned = clean(d)
    return data if cleaned == d else yaml.safe_dump(cleaned, allow_unicode=True, sort_keys=False).encode()


def current_files(parts=PARTS):
    """{archive name: bytes} of what this host has now, for `parts`."""
    out = {}
    st = config.STATE_DIR
    singles = {"config.yaml": config.CONFIG_PATH, "login.yaml": os.path.join(st, "login.yaml"),
               "settings.yaml": os.path.join(st, "settings.yaml")}
    for name, path in singles.items():
        if part_of(name) in parts and os.path.isfile(path):
            with open(path, "rb") as f:
                out[name] = f.read()
    for prefix, root in _roots().items():
        if not os.path.isdir(root):
            continue
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fn in files:
                full = os.path.join(dirpath, fn)
                if os.path.islink(full) or not os.path.isfile(full):
                    continue
                name = prefix + os.path.relpath(full, root).replace(os.sep, "/")
                if part_of(name) in parts and os.path.getsize(full) <= MAX_FILE:
                    with open(full, "rb") as f:
                        out[name] = f.read()
    if "config.yaml" in out:
        out["config.yaml"] = _scrub_config(out["config.yaml"])
    return out


def export(parts=PARTS, version=""):
    files = current_files(parts)
    manifest = {"format": FORMAT, "app": "pve-homelab", "version": version, "node": socket.gethostname().split(".")[0],
                "created": int(time.time()), "parts": list(parts),
                "files": {n: hashlib.sha256(b).hexdigest() for n, b in sorted(files.items())}}
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in [("manifest.json", json.dumps(manifest, indent=1).encode())] + sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(data), manifest["created"], 0o600
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def read(blob):
    """(manifest, {name: bytes}) of a copy, after every check; BadCopy says what is wrong."""
    if len(blob) > MAX_BYTES:
        raise BadCopy("too big")
    try:
        tar = tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz")
    except (tarfile.TarError, OSError, EOFError):
        raise BadCopy("not a .tar.gz")
    files, total, manifest = {}, 0, None
    with tar:
        for m in tar:
            if len(files) >= MAX_FILES:
                raise BadCopy("too many files")
            if not m.isfile():
                raise BadCopy(f"{m.name}: not a plain file")
            if m.name != "manifest.json" and part_of(m.name) is None:
                raise BadCopy(f"{m.name}: not a settings file")
            if m.size > MAX_FILE:
                raise BadCopy(f"{m.name}: too big")
            total += m.size
            if total > MAX_BYTES:
                raise BadCopy("too big")
            data = tar.extractfile(m).read()
            if m.name == "manifest.json":
                try:
                    manifest = json.loads(data)
                except ValueError:
                    raise BadCopy("manifest.json is broken")
            else:
                files[m.name] = data
    if not isinstance(manifest, dict) or manifest.get("app") != "pve-homelab" or manifest.get("format") != FORMAT:
        raise BadCopy("not a PVE Homelab settings copy")
    listed = manifest.get("files") or {}
    for name, data in files.items():
        if listed.get(name) != hashlib.sha256(data).hexdigest():
            raise BadCopy(f"{name}: does not match the manifest")
    for name, data in files.items():
        if name.endswith((".yaml", ".yml")):
            try:
                if not isinstance(yaml.safe_load(data) or {}, dict):
                    raise BadCopy(f"{name}: not a YAML mapping")
            except yaml.YAMLError:
                raise BadCopy(f"{name}: broken YAML")
        elif name.endswith(".json"):
            try:
                json.loads(data)
            except ValueError:
                raise BadCopy(f"{name}: broken JSON")
    return manifest, files


def plan(blob):
    """What putting this copy back would do, part by part: new, changed and same files."""
    manifest, files = read(blob)
    have = current_files()
    out = {p: {"new": 0, "changed": 0, "same": 0} for p in PARTS}
    for name, data in files.items():
        p = part_of(name)
        out[p]["new" if name not in have else "same" if have[name] == data else "changed"] += 1
    here = socket.gethostname().split(".")[0]
    return {"manifest": {k: manifest.get(k) for k in ("version", "node", "created", "parts")},
            "parts": {p: v for p, v in out.items() if sum(v.values())},
            "other_node": manifest.get("node") not in (None, "", here)}


def _snapshot():
    folder = os.path.join(config.STATE_DIR, "backups")
    os.makedirs(folder, mode=0o700, exist_ok=True)
    path = os.path.join(folder, time.strftime("pre-import-%Y%m%d-%H%M%S.tar.gz"))
    with open(path, "wb") as f:
        f.write(export())
    old = sorted(n for n in os.listdir(folder) if n.startswith("pre-import-"))
    for n in old[:-KEEP_SNAPSHOTS]:
        os.remove(os.path.join(folder, n))
    return path


def apply(blob, parts=PARTS):
    """Put back `parts` of a copy; the current state is saved first. Returns (snapshot, names written)."""
    _, files = read(blob)
    chosen = {n: d for n, d in files.items() if part_of(n) in parts}
    snap = _snapshot()
    written = []
    for name, data in sorted(chosen.items()):
        path = config.CONFIG_PATH if name == "config.yaml" else _host_path(name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        written.append(name)
    return snap, written


def _cli(argv):
    from . import update
    ap = argparse.ArgumentParser(prog="python3 -m pvehomelab.backup", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("-o", "--output")
    i = sub.add_parser("inspect")
    i.add_argument("file")
    m = sub.add_parser("import")
    m.add_argument("file")
    m.add_argument("--only", default=",".join(PARTS))
    a = ap.parse_args(argv)
    if a.cmd == "export":
        out = a.output or time.strftime(f"pve-homelab-{socket.gethostname().split('.')[0]}-%Y%m%d.tar.gz")
        with open(out, "wb") as f:
            f.write(export(version=update.installed()["version"]))
        os.chmod(out, 0o600)
        print(out)
        return 0
    with open(a.file, "rb") as f:
        blob = f.read()
    try:
        if a.cmd == "inspect":
            print(json.dumps(plan(blob), indent=1))
            return 0
        parts = [p for p in a.only.split(",") if p in PARTS]
        snap, written = apply(blob, parts)
        print(f"{len(written)} files back ({', '.join(parts)}); the state before is in {snap}")
        print("restart to use them: systemctl restart pve-homelab 'pve-homelab-kiosk@*'")
        return 0
    except BadCopy as e:
        print(f"not used: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
