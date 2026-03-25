import json
from pathlib import Path

from runtime_paths import get_app_data_dir, get_settings_file, get_upload_dir


DEFAULT_SETTINGS = {
    "persona": "감성 인디 음악 아티스트",
    "privacy": "private",
    "interval": 15,
    "folder": str(get_upload_dir()),
    "ai_provider": "groq",
    "groq_api_key": "",
    "gemini_api_key": "",
    "anthropic_api_key": "",
}


def _normalize_folder(value) -> str:
    if not value:
        return str(get_upload_dir())

    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = (get_app_data_dir() / path).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def normalize_settings(raw) -> dict:
    settings = dict(DEFAULT_SETTINGS)

    if isinstance(raw, dict):
        for key in DEFAULT_SETTINGS:
            if key in raw:
                settings[key] = raw[key]

    settings["persona"] = str(settings.get("persona") or DEFAULT_SETTINGS["persona"])
    settings["privacy"] = str(settings.get("privacy") or "private")
    if settings["privacy"] not in {"public", "private", "unlisted"}:
        settings["privacy"] = "private"

    try:
        settings["interval"] = max(5, int(settings.get("interval", 15)))
    except (TypeError, ValueError):
        settings["interval"] = 15

    provider = str(settings.get("ai_provider") or "groq").lower()
    if provider not in {"groq", "gemini", "claude"}:
        provider = "groq"
    settings["ai_provider"] = provider

    settings["groq_api_key"] = str(settings.get("groq_api_key") or "")
    settings["gemini_api_key"] = str(settings.get("gemini_api_key") or "")
    settings["anthropic_api_key"] = str(settings.get("anthropic_api_key") or "")
    settings["folder"] = _normalize_folder(settings.get("folder"))
    return settings


def load_settings() -> dict:
    path = get_settings_file()
    raw = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
    return normalize_settings(raw)


def save_settings(partial: dict) -> dict:
    current = load_settings()
    if isinstance(partial, dict):
        current.update(partial)

    normalized = normalize_settings(current)
    path = get_settings_file()
    path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return normalized
