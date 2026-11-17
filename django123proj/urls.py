"""
URL configuration for django123proj project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include, re_path
from django.views.static import serve
from django.http import HttpResponseServerError, HttpResponse
import sys
import traceback
import logging

def health_debug(request):
    import os, django
    from django.db import connection
    db_status = "UNKNOWN"
    db_error = ""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            db_status = "CONNECTED"
    except Exception as e:
        db_status = "ERROR"
        db_error = str(e)
    
    html = f"""<!DOCTYPE html>
<html>
<body style="font-family: monospace; background: #08080a; color: #fff; padding: 24px;">
    <h2>System Health & Diagnostics</h2>
    <p><strong>Build Version:</strong> v6-resilient-sqlite-ready</p>
    <p><strong>Django:</strong> {django.get_version()}</p>
    <p><strong>Database Status:</strong> <span style="color: {'#4ade80' if db_status == 'CONNECTED' else '#f43f5e'}; font-weight: bold;">{db_status}</span></p>
    <p><strong>Database Error:</strong> {db_error or 'None'}</p>
    <p><strong>Database Engine:</strong> {connection.settings_dict.get('ENGINE')}</p>
    <p><strong>Database Host:</strong> {connection.settings_dict.get('HOST')}</p>
    <p><strong>Database Name:</strong> {connection.settings_dict.get('NAME')}</p>
    <p><strong>VERCEL Env:</strong> {os.environ.get('VERCEL')}</p>
</body>
</html>"""
    return HttpResponse(html, content_type="text/html")

def custom_500_view(request):
    exc_type, exc_value, exc_traceback = sys.exc_info()
    tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback)) if exc_type else "No traceback available."
    logging.getLogger("django.request").error("500 Server Error on %s: %s\n%s", getattr(request, "path", "/"), exc_value, tb_str)
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Server Error (500)</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace; background: #08080a; color: #f1f5f9; padding: 28px; line-height: 1.6; }}
        .box {{ max-width: 900px; margin: 0 auto; background: #121217; border: 1px solid #272733; border-radius: 12px; padding: 24px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }}
        h2 {{ color: #ff1040; margin-top: 0; font-size: 22px; }}
        pre {{ background: #08080a; border: 1px solid #1f1f28; padding: 16px; border-radius: 8px; color: #00f5ff; font-size: 13px; overflow-x: auto; line-height: 1.5; }}
        .badge {{ display: inline-block; padding: 4px 10px; border-radius: 6px; background: rgba(255,16,64,0.15); color: #ff1040; font-weight: bold; font-size: 13px; }}
        a {{ color: #00f5ff; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <div class="box">
        <span class="badge">SERVER ERROR 500</span>
        <h2>Exception Encountered</h2>
        <p><strong>Path:</strong> {getattr(request, "path", "/")}</p>
        <p><strong>Exception Type:</strong> {exc_type.__name__ if exc_type else "Unknown"}</p>
        <p><strong>Details:</strong> {exc_value}</p>
        <h3>Stack Trace:</h3>
        <pre>{tb_str}</pre>
        <p style="margin-top: 20px;"><a href="/">← Return to Homepage</a></p>
    </div>
</body>
</html>"""
    return HttpResponseServerError(html, content_type="text/html; charset=utf-8")

handler500 = custom_500_view

urlpatterns = [
    path("health/", health_debug, name="health_debug"),
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("", include("main.urls")),
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)