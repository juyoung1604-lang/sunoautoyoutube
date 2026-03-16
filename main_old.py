#!/usr/bin/env python3
"""
Suno → YouTube 자동 업로더
Suno에서 다운로드한 MP3를 썸네일 자동생성 후 YouTube에 업로드합니다.
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path

from config import Config
from thumbnail_generator import ThumbnailGenerator
from youtube_uploader import YouTubeUploader
from metadata_generator import MetadataGenerator


def process_song(mp3_path: str, persona: str = None, config: Config = None):
    """단일 MP3 파일을 처리하여 YouTube에 업로드"""
    
    mp3_path = Path(mp3_path)
    if not mp3_path.exists():
        print(f"❌ 파일을 찾을 수 없습니다: {mp3_path}")
        return False

    print(f"\n{'='*60}")
    print(f"🎵 처리 중: {mp3_path.name}")
    print(f"{'='*60}")

    # 1. 메타데이터 생성 (Claude API)
    print("\n📝 [1/4] Claude API로 메타데이터 생성 중...")
    meta_gen = MetadataGenerator(config.anthropic_api_key)
    song_name = mp3_path.stem
    metadata = meta_gen.generate(song_name, persona)
    
    print(f"   제목: {metadata['title']}")
    print(f"   태그: {', '.join(metadata['tags'][:5])}...")

    # 2. 썸네일 생성
    print("\n🎨 [2/4] 썸네일 생성 중...")
    thumb_gen = ThumbnailGenerator(config.anthropic_api_key)
    thumbnail_path = mp3_path.parent / f"{mp3_path.stem}_thumbnail.jpg"
    thumb_gen.generate(
        title=metadata['title'],
        style_prompt=metadata['thumbnail_style'],
        output_path=str(thumbnail_path)
    )
    print(f"   저장됨: {thumbnail_path.name}")

    # 3. MP3 → MP4 변환 (YouTube는 동영상 파일 필요)
    print("\n🎬 [3/4] 동영상 파일 변환 중...")
    video_path = convert_audio_to_video(mp3_path, thumbnail_path)
    print(f"   변환됨: {video_path.name}")

    # 4. YouTube 업로드
    print("\n🚀 [4/4] YouTube 업로드 중...")
    uploader = YouTubeUploader(config.youtube_credentials_file)
    video_id = uploader.upload(
        video_path=str(video_path),
        title=metadata['title'],
        description=metadata['description'],
        tags=metadata['tags'],
        thumbnail_path=str(thumbnail_path),
        category_id="10",  # Music
        privacy_status=config.default_privacy
    )

    if video_id:
        print(f"\n✅ 업로드 완료!")
        print(f"   🔗 https://www.youtube.com/watch?v={video_id}")
        
        # 처리 완료 기록
        log_upload(mp3_path, video_id, metadata, config.log_file)
        
        # 임시 동영상 파일 삭제
        if video_path.exists():
            video_path.unlink()
        
        return True
    else:
        print("❌ 업로드 실패")
        return False


def convert_audio_to_video(mp3_path: Path, thumbnail_path: Path) -> Path:
    """ffmpeg으로 MP3 + 썸네일 → MP4 변환"""
    import subprocess
    
    output_path = mp3_path.parent / f"{mp3_path.stem}_video.mp4"
    
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(thumbnail_path),
        "-i", str(mp3_path),
        "-c:v", "libx264",
        "-tune", "stillimage",
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
        str(output_path)
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 오류:\n{result.stderr}")
    
    return output_path


def watch_folder(folder: str, persona: str, config: Config, interval: int = 30):
    """폴더를 감시하여 새 MP3 파일 자동 처리"""
    folder = Path(folder)
    processed = set()
    
    # 이미 처리된 파일 로드
    if config.log_file and Path(config.log_file).exists():
        with open(config.log_file) as f:
            for line in f:
                try:
                    data = json.loads(line)
                    processed.add(data.get('file'))
                except:
                    pass
    
    print(f"👀 폴더 감시 중: {folder}")
    print(f"⏱️  확인 간격: {interval}초 | Ctrl+C로 종료\n")
    
    while True:
        try:
            mp3_files = list(folder.glob("*.mp3"))
            new_files = [f for f in mp3_files if str(f) not in processed]
            
            if new_files:
                for mp3_file in new_files:
                    success = process_song(str(mp3_file), persona, config)
                    if success:
                        processed.add(str(mp3_file))
            else:
                print(f"  대기 중... ({time.strftime('%H:%M:%S')})", end='\r')
            
            time.sleep(interval)
            
        except KeyboardInterrupt:
            print("\n\n👋 감시 종료")
            break


def log_upload(mp3_path: Path, video_id: str, metadata: dict, log_file: str):
    """업로드 기록 저장"""
    if not log_file:
        return
    
    record = {
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "file": str(mp3_path),
        "video_id": video_id,
        "title": metadata['title'],
        "url": f"https://www.youtube.com/watch?v={video_id}"
    }
    
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')


def main():
    parser = argparse.ArgumentParser(
        description='Suno AI 노래를 YouTube에 자동 업로드',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  # 단일 파일 업로드
  python main.py upload "my_song.mp3" --persona "감성 발라드 가수"

  # 폴더 자동 감시 (새 파일 자동 업로드)
  python main.py watch "./suno_downloads" --persona "K-POP 아티스트"
        """
    )
    
    subparsers = parser.add_subparsers(dest='command')
    
    # upload 명령
    upload_parser = subparsers.add_parser('upload', help='단일 MP3 파일 업로드')
    upload_parser.add_argument('file', help='MP3 파일 경로')
    upload_parser.add_argument('--persona', '-p', help='아티스트 페르소나 설명')
    upload_parser.add_argument('--privacy', choices=['public', 'private', 'unlisted'], 
                               default='private', help='공개 설정 (기본: private)')
    
    # watch 명령
    watch_parser = subparsers.add_parser('watch', help='폴더 자동 감시')
    watch_parser.add_argument('folder', help='감시할 폴더 경로')
    watch_parser.add_argument('--persona', '-p', help='아티스트 페르소나 설명')
    watch_parser.add_argument('--interval', type=int, default=30, help='감시 간격 (초, 기본: 30)')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    config = Config()
    
    if args.command == 'upload':
        config.default_privacy = args.privacy
        process_song(args.file, args.persona, config)
    
    elif args.command == 'watch':
        watch_folder(args.folder, args.persona, config, args.interval)


if __name__ == '__main__':
    main()
