import logging

from aiohttp import web

from .app import make_app

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = make_app()
host, port = app["cfg"]["listen"].rsplit(":", 1)
web.run_app(app, host=host, port=int(port), access_log=None, print=None)
