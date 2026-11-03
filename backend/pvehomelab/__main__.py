import logging

from aiohttp import web

from .app import make_app

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = make_app()
host, port = app["cfg"]["listen"].rsplit(":", 1)
if host.strip("[]") not in ("127.0.0.1", "localhost", "::1"):
    logging.getLogger("pvehomelab").warning(
        "listening on %s: the menu has no TLS and is meant for this machine only; "
        "keep it on 127.0.0.1 unless you know why", host)
web.run_app(app, host=host, port=int(port), access_log=None, print=None)
