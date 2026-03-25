#!/usr/bin/env python3
import argparse
import json
import os
import queue as q_module
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from pathlib import Path

from runtime_paths import (
    executable_dir,
    get_app_data_dir,
    get_log_file,
    get_template_dir,
    get_upload_dir,
    project_root,
    resource_root,
)


def resolve_ffmpeg_binary() -> str:
    candidates = []
    env_path = os.getenv("FFMPEG_PATH")
    if env_path:
        candidates.append(Path(env_path).expanduser())

    for base in (executable_dir(), resource_root(), project_root()):
        for name in ("ffmpeg.exe", "ffmpeg"):
            candidate = base / name
            if candidate not in candidates:
                candidates.append(candidate)

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    resolved = shutil.which("ffmpeg")
    if resolved:
        return resolved

    if sys.platform == "darwin":
        homebrew_ffmpeg = Path("/opt/homebrew/bin/ffmpeg")
        if homebrew_ffmpeg.exists():
            return str(homebrew_ffmpeg)

    return "ffmpeg"


FFMPEG = resolve_ffmpeg_binary()

from flask import Flask, Response, jsonify, render_template, request, send_file, stream_with_context
import werkzeug.utils

from config import Config
from metadata_generator import MetadataGenerator
from settings_store import load_settings, save_settings
from thumbnail_generator import ThumbnailGenerator
from youtube_uploader import YouTubeUploader
from audio_mixer import mix_tracks


app = Flask(__name__, template_folder=str(get_template_dir()))
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024
SERVER_START_TIME = time.time()
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 5001

state = {
    "is_processing": False,
    "is_mixing": False,
    "watch_mode": False,
    "current_file": None,
    "current_step": 0,
    "current_title": None,
    "current_mix_file": None,
    "current_mix_label": None,
    "log_messages": [],
    "upload_queue": [],
    "watch_thread": None,
}
sse_clients = []
state_lock = threading.Lock()
AUDIO_EXTENSIONS = (".mp3", ".wav")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
DEFAULT_THUMBNAIL_STYLE = "dark atmospheric background with glowing text, cinematic mood"
DEFAULT_TAGS = ["인디음악", "감성", "AIMusic", "음악", "뮤직"]


def get_media_folder() -> Path:
    folder = Path(load_settings()["folder"]).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def set_processing_state(*, active: bool, file_name=None, step: int = 0, title=None):
    with state_lock:
        state["is_processing"] = active
        state["current_file"] = file_name
        state["current_step"] = step
        state["current_title"] = title


def set_mix_state(*, active: bool, file_name=None, label=None):
    with state_lock:
        state["is_mixing"] = active
        state["current_mix_file"] = file_name
        state["current_mix_label"] = label


def current_status_payload(label=None):
    return {
        "is_processing": state["is_processing"],
        "is_mixing": state["is_mixing"],
        "watch_mode": state["watch_mode"],
        "current_file": state["current_file"],
        "current_title": state["current_title"],
        "current_mix_file": state["current_mix_file"],
        "current_mix_label": label if label is not None else state["current_mix_label"],
        "step": state["current_step"],
        "queue_pending": sum(1 for item in state["upload_queue"] if item["status"] == "pending"),
    }


def push_event(event_type: str, data: dict):
    msg = f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    dead_clients = []
    for client in list(sse_clients):
        try:
            client.put_nowait(msg)
        except Exception:
            dead_clients.append(client)
    for client in dead_clients:
        if client in sse_clients:
            sse_clients.remove(client)


def log(message: str):
    entry = {"time": time.strftime("%H:%M:%S"), "msg": message}
    state["log_messages"].append(entry)
    if len(state["log_messages"]) > 300:
        state["log_messages"] = state["log_messages"][-300:]
    push_event("log", entry)


def publish_status(step: int, label: str, title=None):
    with state_lock:
        state["current_step"] = step
        if title is not None:
            state["current_title"] = title
    payload = current_status_payload(label=label)
    push_event("status", payload)
    push_event("progress", payload)


def build_generators(config: Config):
    provider = config.ai_provider
    api_key = config.get_ai_key(provider)
    return (
        MetadataGenerator(api_key, provider),
        ThumbnailGenerator(api_key, provider),
    )


def normalize_metadata(metadata, fallback_title: str, privacy: str | None = None) -> dict:
    base_title = str(fallback_title or "Untitled").strip() or "Untitled"
    normalized = dict(metadata) if isinstance(metadata, dict) else {}

    title = str(normalized.get("title") or base_title).strip() or base_title
    description = str(normalized.get("description") or f"{title}\n\n#인디음악 #AIMusic #감성음악").strip()

    raw_tags = normalized.get("tags")
    if isinstance(raw_tags, str):
        tags = [tag.strip() for tag in raw_tags.split(",") if tag.strip()]
    elif isinstance(raw_tags, list):
        tags = [str(tag).strip() for tag in raw_tags if str(tag).strip()]
    else:
        tags = []
    if not tags:
        tags = DEFAULT_TAGS[:]

    thumbnail_style = str(normalized.get("thumbnail_style") or DEFAULT_THUMBNAIL_STYLE).strip()

    normalized["title"] = title
    normalized["description"] = description
    normalized["tags"] = tags
    normalized["thumbnail_style"] = thumbnail_style
    if privacy is not None:
        normalized["privacy"] = str(normalized.get("privacy") or privacy)
    return normalized


def normalize_title_key(value: str) -> str:
    text = str(value or "")
    text = re.sub(r'[\\/:*?"<>|]+', " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.casefold()


def get_existing_generated_thumbnail(mp3_path: Path) -> Path | None:
    for ext in IMAGE_EXTENSIONS:
        candidate = mp3_path.parent / f"{mp3_path.stem}_thumb{ext}"
        if candidate.exists():
            return candidate
    return None


def find_title_matched_image(folder: Path, *title_candidates: str) -> Path | None:
    candidate_keys = {normalize_title_key(title) for title in title_candidates if normalize_title_key(title)}
    if not candidate_keys or not folder.exists():
        return None

    matched = []
    for file_path in folder.iterdir():
        if not file_path.is_file() or file_path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        if normalize_title_key(file_path.stem) in candidate_keys:
            matched.append(file_path)

    if not matched:
        return None

    ext_priority = {".jpg": 0, ".jpeg": 1, ".png": 2, ".webp": 3, ".gif": 4}
    matched.sort(key=lambda path: (ext_priority.get(path.suffix.lower(), 99), path.name.casefold()))
    return matched[0]


def resolve_thumbnail_source(mp3_path: Path, *title_candidates: str) -> tuple[Path | None, str | None]:
    title_image = find_title_matched_image(mp3_path.parent, *title_candidates, mp3_path.stem)
    if title_image:
        return title_image, "title_matched_image"

    thumbnail = get_existing_generated_thumbnail(mp3_path)
    if thumbnail:
        return thumbnail, "existing_thumbnail"

    return None, None


def get_audio_file_by_stem(stem: str) -> Path | None:
    media_folder = get_media_folder()
    for ext in AUDIO_EXTENSIONS:
        file_path = media_folder / f"{stem}{ext}"
        if file_path.exists():
            return file_path
    return None


def resolve_audio_file(filename: str) -> Path:
    safe_name = Path(str(filename or "")).name
    if not safe_name:
        raise ValueError("filename 필요")

    media_folder = get_media_folder()
    media_root = media_folder.resolve()
    candidate = (media_folder / safe_name).resolve()
    if candidate.parent != media_root:
        raise ValueError(f"허용되지 않는 파일 경로: {safe_name}")
    if candidate.suffix.lower() not in AUDIO_EXTENSIONS:
        raise ValueError(f"지원하지 않는 파일 형식: {safe_name}")
    return candidate


def queue_item_path(item: dict) -> str:
    raw_path = str(item.get("path") or "").strip()
    if not raw_path:
        return ""
    return str(Path(raw_path).expanduser().resolve())


def is_file_being_processed(file_path: Path) -> bool:
    resolved = str(file_path.resolve())
    if state["is_processing"] and state.get("current_file") == file_path.name:
        return True
    for item in state["upload_queue"]:
        if item.get("status") == "processing" and queue_item_path(item) == resolved:
            return True
    return False


def remove_queue_items_for_paths(paths: set[str]) -> int:
    kept = []
    removed = 0
    for item in state["upload_queue"]:
        item_path = queue_item_path(item)
        if item_path in paths and item.get("status") != "processing":
            removed += 1
            continue
        kept.append(item)

    if removed:
        state["upload_queue"] = kept
        push_event("queue", {"queue": _queue_summary()})
    return removed


def related_cleanup_paths(file_path: Path) -> list[Path]:
    candidates = [file_path, file_path.parent / f"{file_path.stem}_video.mp4"]
    for ext in IMAGE_EXTENSIONS:
        candidates.append(file_path.parent / f"{file_path.stem}{ext}")
        candidates.append(file_path.parent / f"{file_path.stem}_thumb{ext}")

    unique = []
    seen = set()
    for candidate in candidates:
        resolved = str(candidate.resolve())
        if resolved in seen or not candidate.exists():
            continue
        seen.add(resolved)
        unique.append(candidate)
    return unique


def resolve_upload_log_file() -> Path:
    config = Config(validate_ai=False, validate_youtube=False)
    raw_path = str(config.log_file or "").strip()
    if not raw_path:
        return get_log_file()

    log_file = Path(raw_path).expanduser()
    if not log_file.is_absolute():
        log_file = (get_app_data_dir() / log_file).resolve()
    return log_file


def get_legacy_upload_log_file() -> Path | None:
    legacy = project_root() / "upload_log.jsonl"
    active = resolve_upload_log_file()
    try:
        if legacy.resolve() == active.resolve():
            return None
    except FileNotFoundError:
        pass
    return legacy


def ensure_upload_log_migrated():
    active = resolve_upload_log_file()
    legacy = get_legacy_upload_log_file()
    if active.exists() or not legacy or not legacy.exists():
        return

    try:
        active.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy, active)
    except OSError:
        # 쓰기 권한이 없는 환경에서는 기존 로그를 그대로 fallback 읽기 대상으로 둔다.
        return


def iter_upload_log_files():
    ensure_upload_log_migrated()

    seen = set()
    for path in (resolve_upload_log_file(), get_legacy_upload_log_file()):
        if not path or not path.exists():
            continue
        resolved = str(path.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        yield path


def iter_upload_log_write_targets():
    seen = set()
    for path in (resolve_upload_log_file(), get_legacy_upload_log_file()):
        if not path:
            continue
        resolved = str(path.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        yield path


def normalize_logged_file_path(file_path: str) -> str:
    raw_path = str(file_path or "").strip()
    if not raw_path:
        return ""

    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return str(path.resolve())
    return str((project_root() / path).resolve())


def load_upload_log_records():
    records = []
    seen = set()
    for log_file in iter_upload_log_files():
        with open(log_file, encoding="utf-8") as file_obj:
            for line in file_obj:
                try:
                    record = json.loads(line)
                except Exception:
                    continue

                record.setdefault("privacy", "private")
                record_key = (
                    record.get("timestamp", ""),
                    record.get("video_id", ""),
                    record.get("url", ""),
                    record.get("title", ""),
                    record.get("file", ""),
                )
                if record_key in seen:
                    continue
                seen.add(record_key)
                record["_resolved_file"] = normalize_logged_file_path(record.get("file", ""))
                records.append(record)
    return records


def convert_audio_to_video(mp3_path: Path, thumbnail_path: Path, is_shorts: bool = False) -> Path:
    output_path = mp3_path.parent / f"{mp3_path.stem}_video.mp4"
    is_gif = thumbnail_path.suffix.lower() == ".gif"
    
    # 일반 영상은 1920x1080, 쇼츠는 1080x1920
    resolution = "1080:1920" if is_shorts else "1920:1080"
    
    cmd = [FFMPEG, "-y"]

    if is_gif:
        cmd.extend(["-stream_loop", "-1", "-i", str(thumbnail_path)])
    else:
        cmd.extend(["-loop", "1", "-i", str(thumbnail_path)])

    cmd.extend(
        [
            "-i",
            str(mp3_path),
            "-c:v",
            "libx264",
        ]
    )
    if not is_gif:
        cmd.extend(["-tune", "stillimage"])

    # 비디오 필터 설정: 가로/세로 비율에 맞게 스케일링 후 잘라내기(crop)
    vf = f"scale={resolution}:force_original_aspect_ratio=increase,crop={resolution.replace(':', ':')}"
    
    cmd.extend(
        [
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-pix_fmt",
            "yuv420p",
            "-shortest",
            "-vf",
            vf,
            str(output_path),
        ]
    )
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 오류: {result.stderr[-500:]}")
    return output_path


def write_upload_log(mp3_path: Path, video_id: str, metadata: dict) -> bool:
    ensure_upload_log_migrated()

    record = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "file": str(mp3_path.resolve()),
        "video_id": video_id,
        "title": metadata["title"],
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "privacy": metadata.get("privacy", "private"),
    }
    for log_file in iter_upload_log_write_targets():
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(log_file, "a", encoding="utf-8") as file_obj:
                file_obj.write(json.dumps(record, ensure_ascii=False) + "\n")
            return True
        except OSError:
            continue
    return False


def _queue_summary():
    return [
        {
            "id": item["id"],
            "name": item["name"],
            "status": item["status"],
            "title": item.get("title"),
            "url": item.get("url"),
            "error": item.get("error"),
        }
        for item in state["upload_queue"]
    ]


def _update_queue_item(item_id: str, **changes):
    for item in state["upload_queue"]:
        if item["id"] == item_id:
            item.update(changes)
            break
    push_event("queue", {"queue": _queue_summary()})


def process_file(mp3_path: Path, persona: str, privacy: str, metadata_override=None, queue_id=None, is_shorts: bool = False):
    mp3_path = Path(mp3_path).expanduser().resolve()
    config = Config()
    config.default_privacy = privacy

    set_processing_state(active=True, file_name=mp3_path.name, step=0, title=None)
    push_event("status", current_status_payload())

    video_path = None
    try:
        metadata_generator, thumbnail_generator = build_generators(config)

        if metadata_override:
            metadata = normalize_metadata(metadata_override, mp3_path.stem, privacy)
            log(f"📝 [1/3] 메타데이터 사용: {metadata['title']}")
            publish_status(1, "메타데이터 적용", title=metadata["title"])
        else:
            log(f"📝 [1/3] 메타데이터 생성 중... ({mp3_path.name})")
            publish_status(1, "메타데이터 생성 중")
            metadata = normalize_metadata(metadata_generator.generate(mp3_path.stem, persona), mp3_path.stem, privacy)
            log(f"   ✅ 제목: {metadata['title']}")
            publish_status(1, "메타데이터 완료", title=metadata["title"])

        # 쇼츠인 경우 제목에 #Shorts 추가
        if is_shorts and "#Shorts" not in metadata["title"]:
            metadata["title"] = f"{metadata['title']} #Shorts"

        thumbnail_path, thumbnail_source = resolve_thumbnail_source(mp3_path, metadata["title"])
        if thumbnail_path:
            if thumbnail_source == "title_matched_image":
                log(f"🖼️ [2/3] 제목 일치 이미지 사용: {thumbnail_path.name}")
                publish_status(2, "매칭 이미지 적용", title=metadata["title"])
            else:
                log(f"🖼️ [2/3] 기존 썸네일 재사용: {thumbnail_path.name}")
                publish_status(2, "기존 썸네일 적용", title=metadata["title"])
        else:
            log("🎨 [2/3] 썸네일 생성 중...")
            publish_status(2, "썸네일 생성 중", title=metadata["title"])
            thumbnail_path = mp3_path.parent / f"{mp3_path.stem}_thumb.jpg"
            thumbnail_generator.generate(metadata["title"], metadata["thumbnail_style"], str(thumbnail_path))
            log(f"   ✅ 썸네일 저장: {thumbnail_path.name}")
        push_event("thumbnail", {"stem": mp3_path.stem})

        log(f"🎬 [3/3] 동영상 변환({'Shorts' if is_shorts else '일반'}) 및 YouTube 업로드 중...")
        publish_status(3, "YouTube 업로드 중", title=metadata["title"])
        video_path = convert_audio_to_video(mp3_path, thumbnail_path, is_shorts=is_shorts)
        uploader = YouTubeUploader(config.youtube_credentials_file)
        video_id = uploader.upload(
            video_path=str(video_path),
            title=metadata["title"],
            description=metadata["description"],
            tags=metadata["tags"],
            thumbnail_path=str(thumbnail_path),
            category_id="10",
            privacy_status=privacy,
        )

        if video_id:
            metadata["privacy"] = privacy
            url = f"https://www.youtube.com/watch?v={video_id}"
            if not write_upload_log(mp3_path, video_id, metadata):
                log("⚠️ 업로드 기록 저장 실패: 로그 파일 쓰기 권한을 확인하세요")
            log(f"✅ 업로드 완료! {url}")
            if queue_id:
                _update_queue_item(queue_id, status="done", title=metadata["title"], url=url)
            push_event(
                "done",
                {
                    "success": True,
                    "file": mp3_path.name,
                    "title": metadata["title"],
                    "video_id": video_id,
                    "url": url,
                },
            )
        else:
            log("❌ 업로드 실패 (video_id 없음)")
            if queue_id:
                _update_queue_item(queue_id, status="failed", error="업로드 실패")
            push_event("done", {"success": False, "file": mp3_path.name})

    except Exception as exc:
        log(f"❌ 오류: {exc}")
        if queue_id:
            _update_queue_item(queue_id, status="failed", error=str(exc)[:120])
        push_event("done", {"success": False, "file": mp3_path.name, "error": str(exc)[:200]})
    finally:
        if video_path and video_path.exists():
            video_path.unlink()
        set_processing_state(active=False, file_name=None, step=0, title=None)
        push_event("status", current_status_payload())


def queue_processor():
    while True:
        pending = [item for item in state["upload_queue"] if item["status"] == "pending"]
        if pending and not state["is_processing"] and not state["is_mixing"]:
            item = pending[0]
            _update_queue_item(item["id"], status="processing")
            process_file(
                Path(item["path"]),
                item.get("persona", "감성 인디 음악 아티스트"),
                item.get("privacy", "private"),
                metadata_override=item.get("metadata_override"),
                queue_id=item["id"],
                is_shorts=item.get("is_shorts", False),
            )
        time.sleep(2)


def watch_folder_thread(folder: Path, persona: str, privacy: str, interval: int):
    processed = set()
    for record in load_upload_log_records():
        resolved_file = record.get("_resolved_file")
        if resolved_file:
            processed.add(resolved_file)

    log(f"👀 폴더 감시 시작: {folder.resolve()}")
    push_event("watch", {"active": True, "folder": str(folder.resolve())})

    while state["watch_mode"]:
        new_files = [
            file_path
            for file_path in sorted(list(folder.glob("*.mp3")) + list(folder.glob("*.wav")))
            if str(file_path.resolve()) not in processed
        ]

        for mp3_path in new_files:
            if not state["watch_mode"]:
                break

            item = {
                "id": str(uuid.uuid4())[:8],
                "name": mp3_path.name,
                "path": str(mp3_path.resolve()),
                "persona": persona,
                "privacy": privacy,
                "status": "pending",
            }
            state["upload_queue"].append(item)
            processed.add(str(mp3_path.resolve()))
            log(f"📂 새 파일 감지: {mp3_path.name}")
            push_event("queue", {"queue": _queue_summary()})

        time.sleep(interval)

    log("👋 폴더 감시 종료")
    push_event("watch", {"active": False})


def _load_log_records():
    return load_upload_log_records()


def start_queue_worker():
    worker = threading.Thread(target=queue_processor, daemon=True)
    worker.start()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/files")
def list_files():
    files = []
    uploaded_paths = {record.get("_resolved_file", "") for record in _load_log_records()}
    media_folder = get_media_folder()
    all_files = sorted(
        list(media_folder.glob("*.mp3")) + list(media_folder.glob("*.wav")),
        key=lambda file_path: file_path.stat().st_mtime,
        reverse=True,
    )

    for file_path in all_files:
        thumbnail, thumbnail_source = resolve_thumbnail_source(file_path, file_path.stem)
        files.append(
            {
                "name": file_path.name,
                "stem": file_path.stem,
                "ext": file_path.suffix.lower(),
                "size_mb": round(file_path.stat().st_size / 1024 / 1024, 1),
                "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(file_path.stat().st_mtime)),
                "has_thumbnail": thumbnail is not None,
                "thumbnail_source": thumbnail_source,
                "can_reupload": thumbnail is not None,
                "uploaded": str(file_path.resolve()) in uploaded_paths,
            }
        )
    return jsonify(files)


@app.route("/api/thumbnail/<path:stem>")
def get_thumbnail(stem):
    audio_file = get_audio_file_by_stem(stem)
    if not audio_file:
        return "", 404

    thumbnail, _ = resolve_thumbnail_source(audio_file, stem)
    if thumbnail and thumbnail.exists():
        return send_file(str(thumbnail))
    return "", 404


@app.route("/api/metadata/preview", methods=["POST"])
def preview_metadata():
    data = request.json or {}
    stem = data.get("stem", "unknown")
    persona = data.get("persona", "감성 인디 음악 아티스트")
    song_title = data.get("song_title", "")
    tags_hint = data.get("tags_hint", "")
    lyrics_hint = data.get("lyrics_hint", "")

    try:
        config = Config(validate_youtube=False)
        metadata_generator, _ = build_generators(config)
        if song_title or tags_hint or lyrics_hint:
            metadata = metadata_generator.generate_with_context(stem, song_title, tags_hint, lyrics_hint)
        else:
            metadata = metadata_generator.generate(stem, persona)
        metadata = normalize_metadata(metadata, song_title or stem)
        return jsonify({"ok": True, "metadata": metadata})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/upload", methods=["POST"])
def upload_file():
    file_obj = request.files.get("file")
    if not file_obj or file_obj.filename == "":
        return jsonify({"error": "파일이 없습니다."}), 400

    original_name = Path(file_obj.filename).name
    filename = werkzeug.utils.secure_filename(original_name) or original_name.replace("/", "_").replace("\\", "_")
    if not filename.lower().endswith((".mp3", ".wav")):
        return jsonify({"error": "MP3 또는 WAV만 가능합니다."}), 400

    save_path = get_media_folder() / filename
    file_obj.save(save_path)
    log(f"📁 파일 저장됨: {filename}")

    # 사용자 지정 썸네일 처리
    thumb_obj = request.files.get("thumbnail")
    if thumb_obj and thumb_obj.filename != "":
        thumb_ext = Path(thumb_obj.filename).suffix.lower()
        if thumb_ext in IMAGE_EXTENSIONS:
            thumb_name = f"{save_path.stem}_thumb{thumb_ext}"
            thumb_save_path = get_media_folder() / thumb_name
            thumb_obj.save(thumb_save_path)
            log(f"🖼️ 사용자 지정 썸네일 저장됨: {thumb_name}")

    settings = load_settings()
    metadata_json = request.form.get("metadata")
    metadata_override = json.loads(metadata_json) if metadata_json else None

    item = {
        "id": str(uuid.uuid4())[:8],
        "name": filename,
        "path": str(save_path.resolve()),
        "persona": request.form.get("persona", settings["persona"]),
        "privacy": request.form.get("privacy", settings["privacy"]),
        "is_shorts": request.form.get("is_shorts") == "true",
        "status": "pending",
        "metadata_override": metadata_override,
    }
    state["upload_queue"].append(item)
    push_event("queue", {"queue": _queue_summary()})
    log(f"📋 큐에 추가됨: {filename} {'(Shorts)' if item['is_shorts'] else ''}")
    return jsonify({"ok": True, "queue_id": item["id"], "file": filename})


@app.route("/api/upload/local", methods=["POST"])
def upload_local():
    data = request.json or {}
    filename = data.get("filename")
    if not filename:
        return jsonify({"error": "filename 필요"}), 400

    try:
        file_path = resolve_audio_file(filename)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if not file_path.exists():
        return jsonify({"error": "파일 없음"}), 404

    thumbnail_path, _ = resolve_thumbnail_source(file_path, file_path.stem)
    if data.get("require_thumbnail") and not thumbnail_path:
        return jsonify({"error": "폴더 안에 기존 썸네일 이미지가 있을 때만 재업로드할 수 있습니다."}), 400

    settings = load_settings()
    item = {
        "id": str(uuid.uuid4())[:8],
        "name": file_path.name,
        "path": str(file_path.resolve()),
        "persona": data.get("persona", settings["persona"]),
        "privacy": data.get("privacy", settings["privacy"]),
        "is_shorts": data.get("is_shorts", False),
        "status": "pending",
        "metadata_override": data.get("metadata_override"),
    }
    state["upload_queue"].append(item)
    push_event("queue", {"queue": _queue_summary()})
    if data.get("is_shorts"):
        log(f"📋 로컬 파일 큐 추가(Shorts): {file_path.name}")
    elif data.get("require_thumbnail"):
        log(f"🖼️ 썸네일 재업로드 큐 추가: {file_path.name}")
    else:
        log(f"📋 로컬 파일 큐 추가: {file_path.name}")
    return jsonify({"ok": True, "queue_id": item["id"]})


@app.route("/api/files/delete", methods=["POST"])
def delete_files():
    data = request.json or {}
    filenames = data.get("filenames") or []
    if not isinstance(filenames, list) or not filenames:
        return jsonify({"error": "삭제할 파일을 선택하세요."}), 400

    deleted = []
    skipped = []
    deleted_paths = set()

    for raw_name in filenames:
        try:
            file_path = resolve_audio_file(raw_name)
        except ValueError as exc:
            skipped.append({"file": str(raw_name), "error": str(exc)})
            continue

        if not file_path.exists():
            skipped.append({"file": file_path.name, "error": "파일이 없습니다."})
            continue

        if is_file_being_processed(file_path):
            skipped.append({"file": file_path.name, "error": "현재 처리 중인 파일은 삭제할 수 없습니다."})
            continue

        removed_count = 0
        for candidate in related_cleanup_paths(file_path):
            try:
                candidate.unlink()
                removed_count += 1
            except OSError as exc:
                skipped.append({"file": file_path.name, "error": f"삭제 실패: {exc}"})
                break

        if removed_count == 0:
            continue

        deleted.append(file_path.name)
        deleted_paths.add(str(file_path.resolve()))
        extra_count = max(removed_count - 1, 0)
        if extra_count:
            log(f"🗑️ 파일 삭제: {file_path.name} (+관련 파일 {extra_count}개)")
        else:
            log(f"🗑️ 파일 삭제: {file_path.name}")

    if deleted_paths:
        remove_queue_items_for_paths(deleted_paths)

    status = 200 if deleted else 400
    return jsonify({"ok": bool(deleted), "deleted": deleted, "skipped": skipped}), status


@app.route("/api/mix", methods=["POST"])
def mix_audio():
    data = request.json or {}
    filenames = data.get("filenames", [])
    if not filenames:
        return jsonify({"error": "믹스할 파일이 선택되지 않았습니다."}), 400
    if state["is_processing"]:
        return jsonify({"error": "업로드 처리 중에는 새 믹싱을 시작할 수 없습니다."}), 409
    if state["is_mixing"]:
        return jsonify({"error": "이미 다른 믹싱 작업이 진행 중입니다."}), 409

    try:
        target_minutes = int(data.get("minutes", 60))
        crossfade_sec = int(data.get("crossfade", 4))
    except (TypeError, ValueError):
        return jsonify({"error": "믹스 설정 값이 올바르지 않습니다."}), 400

    if target_minutes <= 0:
        return jsonify({"error": "목표 길이는 1분 이상이어야 합니다."}), 400
    if crossfade_sec < 0:
        return jsonify({"error": "크로스페이드는 0초 이상이어야 합니다."}), 400

    persona = data.get("persona", load_settings()["persona"])
    privacy = data.get("privacy", load_settings()["privacy"])
    auto_upload = data.get("auto_upload", False)

    media_folder = get_media_folder()
    media_root = media_folder.resolve()
    input_paths = []
    safe_names = []
    for raw_name in filenames:
        file_name = Path(str(raw_name)).name
        if file_name in safe_names:
            continue

        candidate = (media_folder / file_name).resolve()
        if candidate.parent != media_root:
            return jsonify({"error": f"허용되지 않는 파일 경로: {file_name}"}), 400
        if candidate.suffix.lower() not in {".mp3", ".wav"}:
            return jsonify({"error": f"지원하지 않는 파일 형식: {file_name}"}), 400
        if not candidate.exists():
            return jsonify({"error": f"파일을 찾을 수 없습니다: {file_name}"}), 404

        safe_names.append(file_name)
        input_paths.append(str(candidate))

    if not input_paths:
        return jsonify({"error": "유효한 오디오 파일이 없습니다."}), 400
    
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    custom_title = data.get("title", "").strip()
    
    if custom_title:
        # 파일명으로 안전한 문자열로 변환
        safe_title = werkzeug.utils.secure_filename(custom_title) or f"Mix_{timestamp}"
        output_filename = f"{safe_title}.mp3"
    else:
        output_filename = f"Mix_{timestamp}.mp3"
        
    output_path = media_folder / output_filename

    def do_mix():
        try:
            set_mix_state(active=True, file_name=output_filename, label="오디오 믹싱 중")
            push_event("status", current_status_payload())
            push_event(
                "mix",
                {
                    "phase": "started",
                    "filename": output_filename,
                    "count": len(input_paths),
                    "minutes": target_minutes,
                    "crossfade": crossfade_sec,
                    "auto_upload": auto_upload,
                },
            )
            log(f"🎚️  믹싱 시작: {output_filename} (파일 {len(input_paths)}개)")
            mix_tracks(
                input_files=input_paths,
                output_path=str(output_path),
                target_minutes=target_minutes,
                crossfade_sec=crossfade_sec,
                logger=log,
            )
            log(f"✅ 믹싱 완료: {output_filename}")
            
            queued = False
            if auto_upload:
                # 커스텀 제목이 있다면 메타데이터 오버라이드로 활용 (AI 힌트)
                metadata_hint = None
                if custom_title:
                    metadata_hint = {"title": custom_title}

                item = {
                    "id": str(uuid.uuid4())[:8],
                    "name": output_filename,
                    "path": str(output_path.resolve()),
                    "persona": persona,
                    "privacy": privacy,
                    "status": "pending",
                    "metadata_override": metadata_hint
                }
                state["upload_queue"].append(item)
                push_event("queue", {"queue": _queue_summary()})
                log(f"📋 믹스 파일 큐 추가: {output_filename}")
                queued = True

            push_event(
                "mix",
                {
                    "phase": "completed",
                    "filename": output_filename,
                    "queued": queued,
                    "auto_upload": auto_upload,
                },
            )
        except Exception as e:
            log(f"❌ 믹싱 오류: {e}")
            push_event(
                "mix",
                {
                    "phase": "failed",
                    "filename": output_filename,
                    "error": str(e)[:200],
                },
            )
        finally:
            set_mix_state(active=False, file_name=None, label=None)
            push_event("status", current_status_payload())

    threading.Thread(target=do_mix, daemon=True).start()
    return jsonify({"ok": True, "filename": output_filename})


@app.route("/api/queue")
def get_queue():
    return jsonify(_queue_summary())


@app.route("/api/queue/<item_id>/cancel", methods=["POST"])
def cancel_queue_item(item_id):
    for item in state["upload_queue"]:
        if item["id"] == item_id and item["status"] == "pending":
            item["status"] = "cancelled"
            push_event("queue", {"queue": _queue_summary()})
            return jsonify({"ok": True})
    return jsonify({"error": "취소 불가 (처리 중 또는 없음)"}), 400


@app.route("/api/queue/clear", methods=["POST"])
def clear_queue():
    state["upload_queue"] = [item for item in state["upload_queue"] if item["status"] == "processing"]
    push_event("queue", {"queue": _queue_summary()})
    return jsonify({"ok": True})


@app.route("/api/watch/start", methods=["POST"])
def start_watch():
    if state["watch_mode"]:
        return jsonify({"error": "이미 감시 중"}), 409

    data = request.json or {}
    settings = load_settings()
    folder = Path(data.get("folder", settings["folder"])).expanduser()
    folder.mkdir(parents=True, exist_ok=True)

    state["watch_mode"] = True
    thread = threading.Thread(
        target=watch_folder_thread,
        args=(
            folder,
            data.get("persona", settings["persona"]),
            data.get("privacy", settings["privacy"]),
            int(data.get("interval", settings["interval"])),
        ),
        daemon=True,
    )
    state["watch_thread"] = thread
    thread.start()
    return jsonify({"ok": True})


@app.route("/api/watch/stop", methods=["POST"])
def stop_watch():
    state["watch_mode"] = False
    return jsonify({"ok": True})


@app.route("/api/status")
def get_status():
    return jsonify(current_status_payload())


@app.route("/api/stats")
def get_stats():
    records = _load_log_records()
    today = time.strftime("%Y-%m-%d")
    privacies = {}
    for record in records:
        privacy = record.get("privacy", "private")
        privacies[privacy] = privacies.get(privacy, 0) + 1
    return jsonify(
        {
            "total": len(records),
            "today": sum(1 for record in records if record.get("timestamp", "").startswith(today)),
            "privacies": privacies,
            "recent": list(reversed(records[-3:])),
        }
    )


@app.route("/api/logs")
def get_logs():
    query = request.args.get("q", "").lower()
    records = _load_log_records()
    if query:
        records = [
            record
            for record in records
            if query in record.get("title", "").lower() or query in record.get("file", "").lower()
        ]
    return jsonify(list(reversed(records[-100:])))


@app.route("/api/console")
def get_console():
    return jsonify(state["log_messages"][-150:])


@app.route("/api/settings", methods=["GET"])
def get_settings():
    return jsonify(load_settings())


@app.route("/api/settings", methods=["POST"])
def post_settings():
    data = request.json or {}
    settings = save_settings(data)
    return jsonify({"ok": True, "settings": settings})


@app.route("/api/settings/ai", methods=["POST"])
def post_ai_settings():
    data = request.json or {}
    payload = {
        "ai_provider": data.get("provider", "groq"),
        "groq_api_key": data.get("groq_key", ""),
        "gemini_api_key": data.get("gemini_key", ""),
        "anthropic_api_key": data.get("anthropic_key", ""),
    }
    settings = save_settings(payload)
    return jsonify({"ok": True, "settings": settings})


@app.route("/events")
def sse():
    queue = q_module.Queue()
    sse_clients.append(queue)

    def stream():
        init_payload = json.dumps(
            {
                "is_processing": state["is_processing"],
                "is_mixing": state["is_mixing"],
                "watch_mode": state["watch_mode"],
                "current_file": state["current_file"],
                "current_title": state["current_title"],
                "current_mix_file": state["current_mix_file"],
                "current_mix_label": state["current_mix_label"],
                "step": state["current_step"],
            },
            ensure_ascii=False,
        )
        yield f"event: init\ndata: {init_payload}\n\n"
        yield f"event: queue\ndata: {json.dumps({'queue': _queue_summary()}, ensure_ascii=False)}\n\n"
        try:
            while True:
                try:
                    yield queue.get(timeout=25)
                except q_module.Empty:
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass
        finally:
            if queue in sse_clients:
                sse_clients.remove(queue)

    return Response(
        stream_with_context(stream()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/server/info")
def server_info():
    elapsed = int(time.time() - SERVER_START_TIME)
    hours, remainder = divmod(elapsed, 3600)
    minutes, seconds = divmod(remainder, 60)
    records = _load_log_records()
    today = time.strftime("%Y-%m-%d")
    return jsonify(
        {
            "uptime": f"{hours:02d}:{minutes:02d}:{seconds:02d}",
            "uptime_sec": elapsed,
            "port": SERVER_PORT,
            "host": SERVER_HOST,
            "pid": os.getpid(),
            "total_uploads": len(records),
            "today_uploads": sum(1 for record in records if record.get("timestamp", "").startswith(today)),
            "watch_mode": state["watch_mode"],
            "is_processing": state["is_processing"],
            "is_mixing": state["is_mixing"],
            "current_mix_file": state["current_mix_file"],
            "queue_pending": sum(1 for item in state["upload_queue"] if item["status"] == "pending"),
            "data_dir": str(get_app_data_dir()),
        }
    )


@app.route("/api/server/shutdown", methods=["POST"])
def server_shutdown():
    log("🛑 서버 종료 요청됨")
    push_event("shutdown", {"msg": "서버가 종료됩니다..."})

    def shutdown_later():
        time.sleep(0.8)
        if os.name == "nt":
            os._exit(0)
        os.kill(os.getpid(), signal.SIGINT)

    threading.Thread(target=shutdown_later, daemon=True).start()
    return jsonify({"ok": True, "msg": "서버를 종료합니다"})


def open_browser_when_ready(host: str, port: int):
    url_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url = f"http://{url_host}:{port}"

    def worker():
        for _ in range(60):
            try:
                with socket.create_connection((url_host, port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.5)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    threading.Thread(target=worker, daemon=True).start()


def find_menu_bar_runner():
    candidates = []

    for base in [Path(__file__).resolve().parent, Path(sys.executable).resolve().parent]:
        for candidate in [base, *base.parents[:6]]:
            if candidate not in candidates:
                candidates.append(candidate)

    for root in candidates:
        menu_script = root / "menu_bar_app.py"
        python_bin = root / "venv" / "bin" / "python"
        if menu_script.exists() and python_bin.exists():
            return root, python_bin, menu_script

    return None, None, None


def start_menu_bar_if_available():
    if sys.platform != "darwin":
        return
    if os.getenv("SUNO_DISABLE_MENU_BAR_AUTOSTART") == "1":
        return

    root, python_bin, menu_script = find_menu_bar_runner()
    if menu_script and python_bin:
        existing = subprocess.run(
            ["pgrep", "-f", str(menu_script)],
            capture_output=True,
            text=True,
        )
        if existing.returncode == 0 and existing.stdout.strip():
            return
        try:
            subprocess.Popen(
                [str(python_bin), str(menu_script)],
                cwd=str(root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            print("🎛️ 메뉴바 실행 요청")
        except Exception:
            pass
        return

    login_launcher = Path.home() / "Library" / "Application Support" / "SunoUploader" / "login-menu-bar.command"
    if login_launcher.exists():
        try:
            subprocess.Popen(
                ["/usr/bin/open", "-gj", "-a", "Terminal", str(login_launcher)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            print("🎛️ 메뉴바 런처 실행 요청")
        except Exception:
            pass


def parse_args():
    parser = argparse.ArgumentParser(description="Suno Uploader Web App")
    parser.add_argument("--host", default="127.0.0.1", help="서버 바인드 주소")
    parser.add_argument("--port", type=int, default=5001, help="서버 포트")
    parser.add_argument("--no-browser", action="store_true", help="자동 브라우저 열기 비활성화")
    return parser.parse_args()


def main():
    global SERVER_HOST, SERVER_PORT
    args = parse_args()
    SERVER_HOST = args.host
    SERVER_PORT = args.port
    get_media_folder()
    start_menu_bar_if_available()
    print(f"🌐 브라우저에서 열기: http://127.0.0.1:{args.port}")
    if not args.no_browser:
        open_browser_when_ready(args.host, args.port)
    app.run(host=args.host, port=args.port, debug=False, threaded=True, use_reloader=False)


start_queue_worker()


if __name__ == "__main__":
    main()
