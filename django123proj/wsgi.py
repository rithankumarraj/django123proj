"""
WSGI config for django123proj project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/wsgi/
"""

import os
import sys
import traceback
import logging

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django123proj.settings')

_raw_application = get_wsgi_application()

def application(environ, start_response):
    try:
        return _raw_application(environ, start_response)
    except Exception as e:
        tb = traceback.format_exc()
        logging.getLogger("django.request").critical("WSGI FATAL ERROR: %s\n%s", e, tb)
        start_response("500 Internal Server Error", [("Content-Type", "text/html; charset=utf-8")])
        body = f"""<!DOCTYPE html>
<html>
<head><title>WSGI Server Error (500)</title></head>
<body style="font-family: monospace; background: #08080a; color: #fff; padding: 24px;">
<h2 style="color: #ff1040;">Fatal WSGI Exception: {type(e).__name__}</h2>
<p>{e}</p>
<h3>Traceback:</h3>
<pre style="background: #121217; padding: 16px; border-radius: 8px; color: #00f5ff; overflow-x: auto;">{tb}</pre>
</body></html>"""
        return [body.encode("utf-8")]

app = application

