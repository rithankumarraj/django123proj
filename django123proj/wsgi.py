"""
WSGI config for django123proj project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django123proj.settings')

application = get_wsgi_application()

if os.environ.get("VERCEL") == "1":
    try:
        from django.core.management import call_command
        call_command("migrate", interactive=False)
    except Exception as exc:
        import logging
        logging.getLogger("django").warning("Vercel auto-migration warning: %s", exc)
