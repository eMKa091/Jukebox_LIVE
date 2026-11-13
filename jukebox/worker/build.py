"""Put the app where wrangler bundles it. Run by wrangler before dev and deploy.

Wrangler bundles every Python file under the entry module's folder, so the
entry cannot sit in jukebox/ next to .venv/ and the tests, and it does not
follow a symlink. The app is copied in instead, fresh each time, so there is
still one copy of it to edit: ../app. Its static files are copied to
public/static, which Cloudflare serves as /static/* before the Worker runs.
"""

import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent / "app"

shutil.rmtree(HERE / "src" / "app", ignore_errors=True)
shutil.copytree(APP, HERE / "src" / "app", ignore=shutil.ignore_patterns("__pycache__"))
shutil.rmtree(HERE / "public", ignore_errors=True)
shutil.copytree(APP / "static", HERE / "public" / "static")
