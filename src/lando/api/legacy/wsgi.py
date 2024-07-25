"""
Construct an application instance that can be referenced by a WSGI server.
"""

from .app import SUBSYSTEMS, construct_app, load_config

config = load_config()
app = construct_app(config)
for system in SUBSYSTEMS:
    system.init_app(app.app)

# No need to ready check since that should have already been done by
# lando-cli before execing to uwsgi.
