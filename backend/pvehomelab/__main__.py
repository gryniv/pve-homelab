import logging

from aiohttp import web

from .app import make_app

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = make_app()
host, port = app["cfg"]["listen"].rsplit(":", 1)
if host.strip("[]") not in ("127.0.0.1", "localhost", "::1"):
    w = app["cfg"]["web"]
    allow = (w.get("allow_from") or []) if w.get("enabled") else []
    if allow:
        logging.getLogger("pvehomelab").info(
            "listening on %s for the reverse proxy: beyond loopback only %s get in", host, ", ".join(map(str, allow)))
    else:
        logging.getLogger("pvehomelab").warning(
            "listening on %s, but web.allow_from is empty: nobody beyond loopback gets in "
            "(the menu has no TLS: name your reverse proxy there, or keep it on 127.0.0.1)", host)
web.run_app(app, host=host, port=int(port), access_log=None, print=None)
