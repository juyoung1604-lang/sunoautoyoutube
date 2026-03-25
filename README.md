# 🎵 Suno AI → YouTube 자동 업로더

Suno AI에서 만든 노래를 **썸네일 자동 생성** 후 YouTube에 자동 업로드하는 Python 스크립트입니다.

---

## 전체 흐름

```
Suno AI 다운로드
      ↓
  MP3 파일
      ↓
Claude API → 제목/설명/태그/썸네일 스타일 자동 생성
      ↓
  Pillow  → 썸네일 이미지 (1280×720) 생성
      ↓
  ffmpeg  → MP3 + 썸네일 → MP4 변환
      ↓
YouTube API → 업로드 + 썸네일 설정
```

---

## ⚙️ 설치 방법

### 1단계: Python 패키지 설치

```bash
pip install -r requirements.txt
```

### 2단계: ffmpeg 설치

**macOS:**
```bash
brew install ffmpeg
```

**Windows:**
- https://ffmpeg.org/download.html 에서 다운로드
- 시스템 PATH에 추가

**Linux (Ubuntu):**
```bash
sudo apt install ffmpeg
```

### 3단계: Anthropic API 키 발급

1. https://console.anthropic.com 접속
2. API Keys → Create Key
3. 키 복사

### 4단계: YouTube API 설정 (중요!)

1. **Google Cloud Console** (https://console.cloud.google.com) 접속
2. 새 프로젝트 생성 또는 기존 프로젝트 선택
3. **API 및 서비스 → 라이브러리** → "YouTube Data API v3" 검색 → 활성화
4. **API 및 서비스 → OAuth 동의 화면** 설정:
   - 외부 선택
   - 앱 이름, 이메일 입력
   - 범위에 YouTube 추가
   - **테스트 사용자**에 본인 Google 계정 추가
5. **API 및 서비스 → 사용자 인증 정보** → OAuth 2.0 클라이언트 ID 만들기:
   - 애플리케이션 유형: **데스크톱 앱** 선택
   - JSON 다운로드 → `credentials/client_secrets.json`으로 저장

```
suno_youtube_uploader/
└── credentials/
    └── client_secrets.json  ← 여기에 저장
```

### 5단계: 환경변수 설정

```bash
cp .env.example .env
# .env 파일 열어서 API 키 입력
```

---

## 🚀 사용 방법

### Suno에서 노래 다운로드

1. [suno.com](https://suno.com) 에서 노래 생성
2. 완성된 노래 → **우측 메뉴(···)** → **Download** → MP3 다운로드
3. 파일을 원하는 폴더에 저장

---

### 단일 파일 업로드

```bash
python main.py upload "새벽감성_노래.mp3" --persona "감성 인디 싱어송라이터, 새벽 감성"
```

**옵션:**
```
--persona, -p   아티스트/채널 페르소나 설명 (메타데이터 품질에 영향)
--privacy       public / private / unlisted (기본: private)
```

---

### 폴더 자동 감시 (새 파일 자동 업로드)

```bash
python main.py watch "./suno_downloads" --persona "K-POP AI 아티스트, 밝고 에너지 넘치는"
```

폴더에 새 MP3 파일이 생기면 자동으로 처리합니다.

**옵션:**
```
--interval      감시 간격 (초, 기본: 30)
```

### 메뉴바 자동 실행

macOS에서는 로그인 시 메뉴바를 자동으로 띄울 수 있습니다.

```bash
./scripts/install-menu-bar-autostart.sh
```

해제:

```bash
./scripts/uninstall-menu-bar-autostart.sh
```

### Windows 배포 실행파일 빌드

Windows PC 또는 GitHub Actions의 `windows-latest` 러너에서 아래 스크립트를 실행합니다.

```bat
scripts\build-windows.bat
```

산출물:

```text
dist\windows\SunoUploader\SunoUploader.exe
dist\windows\SunoUploader\.env.example
dist\windows\SunoUploader\README-windows.txt
```

참고:
- PyInstaller는 macOS에서 Windows `.exe`를 직접 크로스빌드하지 못합니다.
- `ffmpeg.exe`를 실행파일 옆에 두거나, 시스템 PATH에 `ffmpeg`를 추가해야 합니다.

---

## 📁 파일 구조

```
suno_youtube_uploader/
├── main.py                 # 메인 실행 파일
├── config.py               # 설정 관리
├── metadata_generator.py   # Claude API로 메타데이터 생성
├── thumbnail_generator.py  # Claude API + Pillow로 썸네일 생성
├── youtube_uploader.py     # YouTube API 업로드
├── requirements.txt
├── .env.example
├── .env                    # 실제 환경변수 (git에 올리지 마세요!)
├── credentials/
│   ├── client_secrets.json # YouTube OAuth 키
│   └── youtube_token.pickle # 자동 생성되는 토큰 캐시
└── upload_log.jsonl        # 업로드 기록
```

---

## ❓ 자주 묻는 질문

**Q: 처음 실행시 브라우저가 열려요**
A: YouTube OAuth 인증입니다. 한 번만 하면 이후엔 자동으로 토큰을 재사용합니다.

**Q: ffmpeg 오류가 나요**
A: ffmpeg이 PATH에 없는 경우입니다. 설치 후 터미널을 재시작하세요.

**Q: 썸네일이 한글이 깨져요**
A: 한국어 폰트(나눔고딕 등)가 설치되어 있는지 확인하세요. Linux는 `sudo apt install fonts-nanum` 실행.

**Q: 업로드 한도가 있나요?**
A: YouTube API는 하루 10,000 유닛이 기본 할당량입니다. 동영상 1개 업로드에 약 1,600 유닛 소모됩니다 (하루 약 6개).

---

## ⚠️ 주의사항

- `.env` 파일과 `credentials/` 폴더는 절대 GitHub에 올리지 마세요
- 처음엔 `--privacy private` 으로 테스트 후 확인하세요
- Suno AI로 만든 노래의 저작권/수익화 정책은 Suno 약관을 확인하세요
