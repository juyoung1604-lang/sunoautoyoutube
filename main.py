#!/usr/bin/env python3
"""
🎵 Suno MP3 → YouTube 자동 업로더
Suno에서 다운로드한 MP3를 폴더에 넣으면 자동으로 썸네일 생성 후 YouTube 업로드
"""
import os, sys, json, time, argparse
from pathlib import Path
from config import Config
from thumbnail_generator import ThumbnailGenerator
from youtube_uploader import YouTubeUploader
from metadata_generator import MetadataGenerator


def convert_audio_to_video(mp3_path, thumbnail_path):
    import subprocess
    output_path = mp3_path.parent / f"{mp3_path.stem}_video.mp4"
    cmd = ["ffmpeg","-y","-loop","1","-i",str(thumbnail_path),"-i",str(mp3_path),
           "-c:v","libx264","-tune","stillimage","-c:a","aac","-b:a","192k",
           "-pix_fmt","yuv420p","-shortest",
           "-vf","scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
           str(output_path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 오류:\n{r.stderr}")
    return output_path


def log_upload(mp3_path, video_id, metadata, log_file):
    if not log_file: return
    record = {"timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
              "file": str(mp3_path), "video_id": video_id,
              "title": metadata['title'],
              "url": f"https://www.youtube.com/watch?v={video_id}"}
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')


def process_one(mp3_path, persona, config):
    mp3_path = Path(mp3_path)
    print(f"\n{'='*55}")
    print(f"🎵 처리 중: {mp3_path.name}")
    print(f"{'='*55}")

    print("\n📝 [1/3] 메타데이터 생성 중...")
    meta_gen = MetadataGenerator(config.anthropic_api_key)
    metadata = meta_gen.generate(mp3_path.stem, persona)
    print(f"   제목: {metadata['title']}")

    print("\n🎨 [2/3] 썸네일 생성 중...")
    thumb_gen = ThumbnailGenerator(config.anthropic_api_key)
    thumbnail_path = mp3_path.parent / f"{mp3_path.stem}_thumb.jpg"
    thumb_gen.generate(metadata['title'], metadata['thumbnail_style'], str(thumbnail_path))
    print(f"   저장됨: {thumbnail_path.name}")

    print("\n🎬 [3/3] 동영상 변환 및 YouTube 업로드 중...")
    video_path = convert_audio_to_video(mp3_path, thumbnail_path)
    uploader = YouTubeUploader(config.youtube_credentials_file)
    video_id = uploader.upload(
        video_path=str(video_path), title=metadata['title'],
        description=metadata['description'], tags=metadata['tags'],
        thumbnail_path=str(thumbnail_path), category_id="10",
        privacy_status=config.default_privacy)
    if video_path.exists(): video_path.unlink()

    if video_id:
        log_upload(mp3_path, video_id, metadata, config.log_file)
        print(f"\n✅ 업로드 완료!")
        print(f"   🔗 https://www.youtube.com/watch?v={video_id}")

    return video_id


def watch_folder(folder, persona, config, interval=15):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    processed = set()

    # 이미 업로드된 파일 로드
    if config.log_file and Path(config.log_file).exists():
        with open(config.log_file) as f:
            for line in f:
                try: processed.add(json.loads(line).get('file'))
                except: pass

    print(f"\n👀 폴더 감시 시작: {folder.resolve()}")
    print(f"📂 Suno에서 MP3를 이 폴더에 넣으면 자동 업로드됩니다")
    print(f"⏱️  확인 간격: {interval}초 | 종료: Ctrl+C\n")

    while True:
        try:
            new_files = [f for f in list(folder.glob("*.mp3")) + list(folder.glob("*.wav")) if str(f.resolve()) not in processed]
            if new_files:
                for mp3 in sorted(new_files):
                    video_id = process_one(str(mp3), persona, config)
                    if video_id:
                        processed.add(str(mp3.resolve()))
                print(f"\n👀 계속 감시 중... | Ctrl+C로 종료")
            else:
                print(f"  대기 중... ({time.strftime('%H:%M:%S')}) — MP3를 폴더에 넣으세요", end='\r')
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\n\n👋 감시 종료")
            break


def main():
    parser = argparse.ArgumentParser(
        description='🎵 Suno MP3 → YouTube 자동 업로더',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  # 폴더 감시 (MP3 넣으면 자동 업로드)
  python main.py watch --persona "새벽 감성 인디 가수"

  # 단일 파일 업로드
  python main.py upload "노래.mp3" --persona "감성 발라드 가수"
        """)
    sub = parser.add_subparsers(dest='command')

    w = sub.add_parser('watch', help='폴더 감시 모드 (추천)')
    w.add_argument('--folder', '-f', default='./suno_downloads', help='감시할 폴더 (기본: ./suno_downloads)')
    w.add_argument('--persona', '-p', default='감성 인디 음악 아티스트', help='아티스트 페르소나')
    w.add_argument('--interval', type=int, default=15, help='감시 간격 초 (기본: 15)')
    w.add_argument('--privacy', choices=['public','private','unlisted'], default='private')

    u = sub.add_parser('upload', help='단일 MP3 파일 업로드')
    u.add_argument('file', help='MP3 파일 경로')
    u.add_argument('--persona', '-p', default='감성 인디 음악 아티스트')
    u.add_argument('--privacy', choices=['public','private','unlisted'], default='private')

    args = parser.parse_args()
    if not args.command:
        parser.print_help(); sys.exit(1)

    config = Config()
    config.default_privacy = args.privacy

    if args.command == 'watch':
        watch_folder(args.folder, args.persona, config, args.interval)
    elif args.command == 'upload':
        process_one(args.file, args.persona, config)


if __name__ == '__main__':
    main()
