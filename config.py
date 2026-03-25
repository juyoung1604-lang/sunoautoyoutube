import json
import os
from pathlib import Path

from runtime_paths import get_credentials_dir, get_log_file, get_settings_file, iter_env_files

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


def _load_environment():
    if load_dotenv is None:
        return
    for env_file in iter_env_files():
        if env_file.exists():
            load_dotenv(env_file, override=False)


def _load_saved_settings() -> dict:
    settings_file = get_settings_file()
    if not settings_file.exists():
        return {}
    try:
        return json.loads(settings_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


_load_environment()


class Config:
    def __init__(self, validate_ai: bool = True, validate_youtube: bool = True):
        settings = _load_saved_settings()
        self.ai_provider = os.getenv("AI_PROVIDER") or settings.get("ai_provider", "groq")
        self.groq_api_key = os.getenv("GROQ_API_KEY") or settings.get("groq_api_key", "")
        self.gemini_api_key = os.getenv("GEMINI_API_KEY") or settings.get("gemini_api_key", "")
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY") or settings.get("anthropic_api_key", "")
        self.youtube_credentials_file = (
            os.getenv("YOUTUBE_CREDENTIALS_FILE")
            or settings.get("youtube_credentials_file")
            or str(get_credentials_dir() / "client_secrets.json")
        )
        self.default_privacy = os.getenv("DEFAULT_PRIVACY") or settings.get("privacy", "private")
        self.log_file = os.getenv("LOG_FILE") or settings.get("log_file") or str(get_log_file())
        self.ai_api_key = self.get_ai_key(self.ai_provider)
        self._validate(validate_ai=validate_ai, validate_youtube=validate_youtube)

    def get_ai_key(self, provider: str) -> str:
        if provider == "claude":
            return self.anthropic_api_key
        if provider == "gemini":
            return self.gemini_api_key
        return self.groq_api_key

    def _validate(self, validate_ai: bool = True, validate_youtube: bool = True):
        errors = []
        if self.ai_provider not in {"groq", "gemini", "claude"}:
            self.ai_provider = "groq"

        self.ai_api_key = self.get_ai_key(self.ai_provider)
        if validate_ai and not self.ai_api_key:
            if self.ai_provider == "claude":
                provider_label = "ANTHROPIC_API_KEY"
            elif self.ai_provider == "gemini":
                provider_label = "GEMINI_API_KEY"
            else:
                provider_label = "GROQ_API_KEY"
            errors.append(f"{provider_label} 필요 → 설정 또는 .env 파일에 추가하세요")

        if validate_youtube and not Path(self.youtube_credentials_file).expanduser().exists():
            errors.append(f"YouTube credentials 없음: {self.youtube_credentials_file}")

        if errors:
            print("⚠️  설정 오류:")
            for error in errors:
                print(f"   • {error}")
            raise ValueError("설정 오류: " + " | ".join(errors))
