import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RESUMES_DIR = DATA_DIR / "resumes"
# Keep Chromium profile outside OneDrive to prevent file-locking issues
_local_app_data = os.environ.get("LOCALAPPDATA")
BROWSER_PROFILE_DIR = (
    Path(_local_app_data) / "JobHunterAI" / "browser_profile"
    if _local_app_data
    else DATA_DIR / "browser_profile"
)
DB_PATH = DATA_DIR / "job_hunter.db"
VAULT_KEY_PATH = DATA_DIR / ".vault.key"
STATIC_DIR = BASE_DIR / "static"

for _d in (DATA_DIR, RESUMES_DIR, BROWSER_PROFILE_DIR):
    _d.mkdir(parents=True, exist_ok=True)
