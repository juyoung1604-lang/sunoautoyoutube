import os
import sys
from pathlib import Path


APP_NAME = "SunoUploader"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    return Path(__file__).resolve().parent


def resource_root() -> Path:
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return project_root()


def executable_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return project_root()


def get_app_data_dir() -> Path:
    override = os.getenv("SUNO_UPLOADER_HOME")
    if override:
        base = Path(override).expanduser()
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    elif os.name == "nt":
        roaming = os.getenv("APPDATA")
        base = Path(roaming) if roaming else (Path.home() / "AppData" / "Roaming")
        base = base / APP_NAME
    else:
        config_home = os.getenv("XDG_CONFIG_HOME")
        base = Path(config_home) if config_home else (Path.home() / ".config")
        base = base / APP_NAME

    base.mkdir(parents=True, exist_ok=True)
    (base / "credentials").mkdir(parents=True, exist_ok=True)
    (base / "suno_downloads").mkdir(parents=True, exist_ok=True)
    return base


def get_credentials_dir() -> Path:
    path = get_app_data_dir() / "credentials"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_upload_dir() -> Path:
    path = get_app_data_dir() / "suno_downloads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_settings_file() -> Path:
    return get_app_data_dir() / "web_settings.json"


def get_log_file() -> Path:
    return get_app_data_dir() / "upload_log.jsonl"


def get_template_dir() -> Path:
    template_dir = resource_root() / "templates"
    if template_dir.exists():
        return template_dir
    return project_root() / "templates"


def iter_env_files():
    seen = set()
    for path in (
        get_app_data_dir() / ".env",
        executable_dir() / ".env",
        project_root() / ".env",
    ):
        resolved = str(path.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        yield path
