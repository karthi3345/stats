"""
WSGI config for status_project project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os
import shutil
from pathlib import Path
from django.core.wsgi import get_wsgi_application

# On Vercel serverless functions, the root filesystem is read-only (/var/task).
# Only /tmp is writable. If running on Vercel and db.sqlite3 exists, ensure a writable copy in /tmp.
if os.environ.get('VERCEL'):
    source_db = Path(__file__).resolve().parent.parent / 'db.sqlite3'
    tmp_db = Path('/tmp/db.sqlite3')
    if source_db.exists() and not tmp_db.exists():
        try:
            shutil.copy2(source_db, tmp_db)
        except Exception:
            pass

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'status_project.settings')

application = get_wsgi_application()
app = application

