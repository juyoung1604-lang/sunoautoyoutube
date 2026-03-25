"""
YouTube Data API v3을 사용하여 동영상 업로드
OAuth 2.0 인증 포함
"""

import os
import pickle
import tempfile
from pathlib import Path

import google.oauth2.credentials
import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request
from PIL import Image


SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube"
]
API_SERVICE_NAME = "youtube"
API_VERSION = "v3"


class YouTubeUploader:
    def __init__(self, credentials_file: str, token_file: str = None):
        self.credentials_file = credentials_file
        if token_file:
            self.token_file = Path(token_file)
        else:
            self.token_file = Path(credentials_file).expanduser().resolve().parent / "youtube_token.pickle"
        self.youtube = self._authenticate()
    
    def _authenticate(self):
        """OAuth 2.0 인증 (토큰 캐싱으로 재인증 불필요)"""
        credentials = None
        token_path = self.token_file
        
        # 저장된 토큰 불러오기
        if token_path.exists():
            with open(token_path, 'rb') as f:
                credentials = pickle.load(f)
        
        # 토큰 만료 시 갱신
        if credentials and credentials.expired and credentials.refresh_token:
            print("   🔄 YouTube 토큰 갱신 중...")
            credentials.refresh(Request())
        
        # 새 인증 필요
        elif not credentials or not credentials.valid:
            print("   🔑 YouTube 브라우저 인증이 필요합니다...")
            flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
                self.credentials_file,
                SCOPES
            )
            credentials = flow.run_local_server(port=0, open_browser=True)
            print("   ✅ 인증 완료!")
        
        # 토큰 저장
        token_path.parent.mkdir(parents=True, exist_ok=True)
        with open(token_path, 'wb') as f:
            pickle.dump(credentials, f)
        
        return googleapiclient.discovery.build(
            API_SERVICE_NAME,
            API_VERSION,
            credentials=credentials
        )
    
    def upload(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list,
        thumbnail_path: str = None,
        category_id: str = "10",
        privacy_status: str = "private"
    ) -> str:
        """
        YouTube에 동영상 업로드
        
        Returns:
            video_id (str) 또는 None (실패시)
        """
        video_path = Path(video_path)
        file_size = video_path.stat().st_size
        
        print(f"   파일 크기: {file_size / 1024 / 1024:.1f} MB")
        print(f"   공개 설정: {privacy_status}")
        
        body = {
            "snippet": {
                "title": title[:100],  # YouTube 제목 최대 100자
                "description": description[:5000],  # 최대 5000자
                "tags": tags[:500],  # 태그 제한
                "categoryId": category_id,
                "defaultLanguage": "ko",
                "defaultAudioLanguage": "ko"
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False,
            }
        }
        
        media = MediaFileUpload(
            str(video_path),
            chunksize=1024 * 1024,  # 1MB 청크
            resumable=True
        )
        
        request = self.youtube.videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=media
        )
        
        # 업로드 진행
        video_id = self._resumable_upload(request)
        
        # 썸네일 업로드
        if video_id and thumbnail_path and Path(thumbnail_path).exists():
            self._upload_thumbnail(video_id, thumbnail_path)
        
        return video_id
    
    def _resumable_upload(self, request) -> str:
        """재시도 가능한 업로드 실행"""
        response = None
        error = None
        retry = 0
        max_retries = 10
        
        while response is None:
            try:
                status, response = request.next_chunk()
                
                if status:
                    progress = int(status.progress() * 100)
                    print(f"   업로드 중: {progress}%", end='\r')
                
                if response is not None:
                    if 'id' in response:
                        print(f"   업로드 중: 100%")
                        return response['id']
                    else:
                        raise Exception(f"업로드 응답 오류: {response}")
            
            except googleapiclient.errors.HttpError as e:
                if e.resp.status in [500, 502, 503, 504]:
                    error = e
                    retry += 1
                    if retry > max_retries:
                        print(f"\n   ❌ 최대 재시도 횟수 초과")
                        raise
                    wait_time = 2 ** retry
                    print(f"\n   ⚠️  서버 오류, {wait_time}초 후 재시도... ({retry}/{max_retries})")
                    import time
                    time.sleep(wait_time)
                else:
                    raise
        
        return None
    
    def _upload_thumbnail(self, video_id: str, thumbnail_path: str):
        """썸네일 업로드"""
        upload_path = Path(thumbnail_path)
        temp_path = None
        try:
            if upload_path.suffix.lower() == ".gif":
                with Image.open(upload_path) as img:
                    frame = img.convert("RGB")
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                        temp_path = Path(tmp.name)
                    frame.save(temp_path, format="PNG")
                upload_path = temp_path

            self.youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(str(upload_path))
            ).execute()
            print("   🖼️  썸네일 업로드 완료")
        except googleapiclient.errors.HttpError as e:
            print(f"   ⚠️  썸네일 업로드 실패 (동영상은 정상 업로드됨): {e}")
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink(missing_ok=True)
