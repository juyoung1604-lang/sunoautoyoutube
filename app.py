#!/usr/bin/env python3
"""
🎵 Suno YouTube Uploader - Web UI
Flask 기반 브라우저 인터페이스
"""
import os, sys, json, time, threading, queue
from pathlib import Path
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
import werkzeug.utils

# 현재 디렉토리를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent))

from config import Config
from thumbnail_generator import ThumbnailGenerator
from youtube_uploader import YouTubeUploader
from metadata_generator import MetadataGenerator

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB

UPLOAD_FOLDER = Path('./suno_downloads')
UPLOAD_FOLDER.mkdir(exist_ok=True)

# 상태 관리
state = {
    'is_processing': False,
    'watch_mode': False,
    'current_file': None,
    'progress_step': 0,  # 0~3
    'log_messages': [],
    'watch_thread': None,
}
sse_clients = []  # SSE 구독자 큐 목록
state_lock = threading.Lock()


def push_event(event_type: str, data: dict):
    """모든 SSE 클라이언트에 이벤트 전송"""
    msg = f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    dead = []
    for q in list(sse_clients):
        try:
            q.put_nowait(msg)
        except Exception:
            dead.append(q)
    for q in dead:
        if q in sse_clients:
            sse_clients.remove(q)


def log(msg: str):
    ts = time.strftime('%H:%M:%S')
    entry = {'time': ts, 'msg': msg}
    state['log_messages'].append(entry)
    if len(state['log_messages']) > 200:
        state['log_messages'] = state['log_messages'][-200:]
    push_event('log', entry)


def convert_audio_to_video(mp3_path, thumbnail_path):
    import subprocess
    output_path = mp3_path.parent / f"{mp3_path.stem}_video.mp4"
    cmd = ["ffmpeg", "-y", "-loop", "1", "-i", str(thumbnail_path), "-i", str(mp3_path),
           "-c:v", "libx264", "-tune", "stillimage", "-c:a", "aac", "-b:a", "192k",
           "-pix_fmt", "yuv420p", "-shortest",
           "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
           str(output_path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 오류: {r.stderr[-500:]}")
    return output_path


def log_upload(mp3_path, video_id, metadata):
    config = Config()
    if not config.log_file:
        return
    record = {
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "file": str(mp3_path),
        "video_id": video_id,
        "title": metadata['title'],
        "url": f"https://www.youtube.com/watch?v={video_id}"
    }
    with open(config.log_file, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')


def process_file(mp3_path: Path, persona: str, privacy: str):
    """단일 파일 처리 (백그라운드 스레드에서 실행)"""
    config = Config()
    config.default_privacy = privacy

    with state_lock:
        state['is_processing'] = True
        state['current_file'] = mp3_path.name
        state['progress_step'] = 0

    push_event('status', {'is_processing': True, 'current_file': mp3_path.name, 'step': 0})

    try:
        # 1단계: 메타데이터 생성
        log(f"📝 [1/3] 메타데이터 생성 중... ({mp3_path.name})")
        push_event('progress', {'step': 1, 'label': '메타데이터 생성 중'})
        meta_gen = MetadataGenerator(config.anthropic_api_key)
        metadata = meta_gen.generate(mp3_path.stem, persona)
        log(f"   ✅ 제목: {metadata['title']}")

        # 2단계: 썸네일 생성
        log("🎨 [2/3] 썸네일 생성 중...")
        push_event('progress', {'step': 2, 'label': '썸네일 생성 중'})
        thumb_gen = ThumbnailGenerator(config.anthropic_api_key)
        thumbnail_path = mp3_path.parent / f"{mp3_path.stem}_thumb.jpg"
        thumb_gen.generate(metadata['title'], metadata['thumbnail_style'], str(thumbnail_path))
        log(f"   ✅ 썸네일 저장: {thumbnail_path.name}")

        # 3단계: 동영상 변환 + 업로드
        log("🎬 [3/3] 동영상 변환 및 YouTube 업로드 중...")
        push_event('progress', {'step': 3, 'label': 'YouTube 업로드 중'})
        video_path = convert_audio_to_video(mp3_path, thumbnail_path)
        uploader = YouTubeUploader(config.youtube_credentials_file)
        video_id = uploader.upload(
            video_path=str(video_path),
            title=metadata['title'],
            description=metadata['description'],
            tags=metadata['tags'],
            thumbnail_path=str(thumbnail_path),
            category_id="10",
            privacy_status=privacy
        )
        if video_path.exists():
            video_path.unlink()

        if video_id:
            url = f"https://www.youtube.com/watch?v={video_id}"
            log(f"✅ 업로드 완료! {url}")
            log_upload(mp3_path, video_id, metadata)
            push_event('done', {
                'success': True,
                'file': mp3_path.name,
                'title': metadata['title'],
                'video_id': video_id,
                'url': url
            })
        else:
            log("❌ 업로드 실패")
            push_event('done', {'success': False, 'file': mp3_path.name})

    except Exception as e:
        log(f"❌ 오류: {e}")
        push_event('done', {'success': False, 'file': mp3_path.name, 'error': str(e)})

    finally:
        with state_lock:
            state['is_processing'] = False
            state['current_file'] = None
            state['progress_step'] = 0
        push_event('status', {'is_processing': False, 'current_file': None, 'step': 0})


def watch_folder_thread(folder: Path, persona: str, privacy: str, interval: int):
    """폴더 감시 스레드"""
    processed = set()
    config = Config()

    if config.log_file and Path(config.log_file).exists():
        with open(config.log_file) as f:
            for line in f:
                try:
                    processed.add(json.loads(line).get('file'))
                except Exception:
                    pass

    log(f"👀 폴더 감시 시작: {folder.resolve()}")
    push_event('watch', {'active': True, 'folder': str(folder.resolve())})

    while state['watch_mode']:
        new_files = [
            f for f in list(folder.glob("*.mp3")) + list(folder.glob("*.wav"))
            if str(f.resolve()) not in processed
        ]
        if new_files and not state['is_processing']:
            for mp3 in sorted(new_files):
                if not state['watch_mode']:
                    break
                process_file(mp3, persona, privacy)
                processed.add(str(mp3.resolve()))
        time.sleep(interval)

    log("👋 폴더 감시 종료")
    push_event('watch', {'active': False})


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/upload', methods=['POST'])
def upload_file():
    if state['is_processing']:
        return jsonify({'error': '현재 다른 파일 처리 중입니다. 잠시 후 시도하세요.'}), 409

    file = request.files.get('file')
    if not file or file.filename == '':
        return jsonify({'error': '파일이 없습니다.'}), 400

    filename = werkzeug.utils.secure_filename(file.filename)
    if not filename.lower().endswith(('.mp3', '.wav')):
        return jsonify({'error': 'MP3 또는 WAV 파일만 업로드 가능합니다.'}), 400

    save_path = UPLOAD_FOLDER / filename
    file.save(save_path)
    log(f"📁 파일 업로드됨: {filename}")

    persona = request.form.get('persona', '감성 인디 음악 아티스트')
    privacy = request.form.get('privacy', 'private')

    t = threading.Thread(target=process_file, args=(save_path, persona, privacy), daemon=True)
    t.start()

    return jsonify({'ok': True, 'file': filename})


@app.route('/api/watch/start', methods=['POST'])
def start_watch():
    if state['watch_mode']:
        return jsonify({'error': '이미 감시 중입니다.'}), 409

    data = request.json or {}
    persona = data.get('persona', '감성 인디 음악 아티스트')
    privacy = data.get('privacy', 'private')
    interval = int(data.get('interval', 15))
    folder = Path(data.get('folder', './suno_downloads'))
    folder.mkdir(parents=True, exist_ok=True)

    state['watch_mode'] = True
    t = threading.Thread(
        target=watch_folder_thread,
        args=(folder, persona, privacy, interval),
        daemon=True
    )
    state['watch_thread'] = t
    t.start()

    return jsonify({'ok': True})


@app.route('/api/watch/stop', methods=['POST'])
def stop_watch():
    state['watch_mode'] = False
    return jsonify({'ok': True})


@app.route('/api/status')
def get_status():
    return jsonify({
        'is_processing': state['is_processing'],
        'watch_mode': state['watch_mode'],
        'current_file': state['current_file'],
        'step': state['progress_step'],
    })


@app.route('/api/logs')
def get_logs():
    """업로드 히스토리"""
    records = []
    log_file = Path('upload_log.jsonl')
    if log_file.exists():
        with open(log_file, encoding='utf-8') as f:
            for line in f:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
    return jsonify(list(reversed(records[-50:])))


@app.route('/api/console')
def get_console():
    return jsonify(state['log_messages'][-100:])


@app.route('/events')
def sse():
    """Server-Sent Events 스트림"""
    q = queue.Queue()
    sse_clients.append(q)

    def stream():
        # 연결 즉시 현재 상태 전송
        init = json.dumps({
            'is_processing': state['is_processing'],
            'watch_mode': state['watch_mode'],
            'current_file': state['current_file'],
        }, ensure_ascii=False)
        yield f"event: init\ndata: {init}\n\n"
        try:
            while True:
                try:
                    msg = q.get(timeout=25)
                    yield msg
                except queue.Empty:
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass
        finally:
            if q in sse_clients:
                sse_clients.remove(q)

    return Response(
        stream_with_context(stream()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )


if __name__ == '__main__':
    print("🌐 브라우저에서 열기: http://localhost:5001")
    app.run(host='0.0.0.0', port=5001, debug=False, threaded=True)
