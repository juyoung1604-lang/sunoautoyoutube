Suno Uploader for Windows

1. Run SunoUploader.exe.
2. The app opens the local web UI in your browser.
3. Runtime data is stored in %APPDATA%\SunoUploader.

Before first upload:
- Put client_secrets.json in %APPDATA%\SunoUploader\credentials\client_secrets.json
- Add API keys in the web settings screen, or place a .env file next to SunoUploader.exe
- Install ffmpeg and add it to PATH, or place ffmpeg.exe next to SunoUploader.exe

Notes:
- The app shuts down from the "서버 종료" button in the web UI.
- The first Google OAuth login opens your browser.
- Audio downloads and logs are saved under %APPDATA%\SunoUploader.
