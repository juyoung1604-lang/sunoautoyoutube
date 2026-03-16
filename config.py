import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

class Config:
    def __init__(self):
        self.anthropic_api_key = os.getenv('GROQ_API_KEY', '')
        self.youtube_credentials_file = os.getenv('YOUTUBE_CREDENTIALS_FILE', 'credentials/client_secrets.json')
        self.default_privacy = os.getenv('DEFAULT_PRIVACY', 'private')
        self.log_file = os.getenv('LOG_FILE', 'upload_log.jsonl')
        self._validate()

    def _validate(self):
        errors = []
        if not self.anthropic_api_key:
            errors.append("GROQ_API_KEY 없음 → .env 파일에 추가하세요")
        if not Path(self.youtube_credentials_file).exists():
            errors.append(f"YouTube credentials 없음: {self.youtube_credentials_file}")
        if errors:
            print("⚠️  설정 오류:")
            for e in errors: print(f"   • {e}")
            raise SystemExit(1)
