"""
🎚️  오디오 믹서
- 크로스페이드: 트랙 간 자연스러운 전환
- 자동 루프: 부족한 음원 반복해서 목표 시간 채우기
- 노말라이제이션: 전체 볼륨 일정하게
"""
from pydub import AudioSegment
from pydub.effects import normalize
from pathlib import Path
import shutil

# macOS Homebrew 등 시스템 PATH에 ffmpeg가 없을 때를 대비해 경로 명시
_ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
_ffprobe = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
AudioSegment.converter = _ffmpeg
AudioSegment.ffprobe = _ffprobe


SUPPORTED_FORMATS = {"mp3", "wav"}


def _emit(logger, message: str):
    if logger:
        logger(message)
    else:
        print(message)


def _safe_crossfade_ms(left: AudioSegment, right: AudioSegment, requested_ms: int) -> int:
    if requested_ms <= 0:
        return 0
    # 너무 긴 crossfade는 결과 길이를 거의 늘리지 못해 긴 루프를 만들 수 있다.
    shortest = min(len(left), len(right))
    conservative_limit = max(0, (shortest // 3) - 1)
    hard_limit = max(0, shortest - 1)
    return max(0, min(requested_ms, conservative_limit, hard_limit))


def load_audio(path: str) -> AudioSegment:
    """MP3/WAV 자동 감지 로드"""
    p = Path(path)
    fmt = p.suffix.lower().lstrip('.')
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(f"지원하지 않는 오디오 형식: {p.name}")
    if fmt == 'wav':
        return AudioSegment.from_wav(str(p))
    return AudioSegment.from_mp3(str(p))


def loop_to_duration(audio: AudioSegment, target_ms: int, crossfade_ms: int = 3000) -> AudioSegment:
    """
    음원을 반복해서 목표 시간(ms)까지 채우기
    크로스페이드로 루프 이음새 자연스럽게 처리
    """
    if len(audio) >= target_ms:
        return audio[:target_ms]

    result = audio
    while len(result) < target_ms + crossfade_ms:
        result = result.append(audio, crossfade=_safe_crossfade_ms(result, audio, crossfade_ms))

    return result[:target_ms]


def mix_tracks(
    input_files: list,
    output_path: str,
    target_minutes: int = 60,
    crossfade_sec: int = 4,
    normalize_audio: bool = True,
    logger=None,
) -> str:
    """
    여러 트랙을 믹싱하여 하나의 긴 오디오 파일 생성

    Args:
        input_files: MP3/WAV 파일 경로 리스트
        output_path: 출력 파일 경로 (.mp3 또는 .wav)
        target_minutes: 목표 길이 (분, 기본 60분)
        crossfade_sec: 크로스페이드 길이 (초, 기본 4초)
        normalize_audio: 노말라이제이션 적용 여부
    """
    if not input_files:
        raise ValueError("입력 파일이 없습니다")
    if target_minutes <= 0:
        raise ValueError("목표 길이는 1분 이상이어야 합니다")
    if crossfade_sec < 0:
        raise ValueError("크로스페이드 값은 0초 이상이어야 합니다")

    target_ms = target_minutes * 60 * 1000
    crossfade_ms = crossfade_sec * 1000
    output_path = Path(output_path)
    output_format = output_path.suffix.lower().lstrip('.')
    if output_format not in SUPPORTED_FORMATS:
        raise ValueError("출력 파일은 .mp3 또는 .wav 이어야 합니다")

    _emit(logger, f"🎚️  믹싱 시작 — 목표: {target_minutes}분")
    _emit(logger, f"   트랙 수: {len(input_files)}개 | 크로스페이드: {crossfade_sec}초")

    # 1. 트랙 로드 + 노말라이제이션
    tracks = []
    for i, f in enumerate(input_files):
        file_path = Path(f)
        if not file_path.exists():
            raise FileNotFoundError(f"파일 없음: {file_path.name}")
        _emit(logger, f"   📂 로딩 ({i+1}/{len(input_files)}): {file_path.name}")
        audio = load_audio(f)
        if normalize_audio:
            audio = normalize(audio)
        tracks.append(audio)
        _emit(logger, f"      길이: {len(audio)//1000}초 | 볼륨 정규화 완료")

    # 2. 트랙이 1개면 루프로 60분 채우기
    if len(tracks) == 1:
        _emit(logger, f"   🔁 단일 트랙 — 루프로 {target_minutes}분 채우는 중...")
        mixed = loop_to_duration(tracks[0], target_ms, crossfade_ms)

    else:
        # 3. 여러 트랙 크로스페이드로 이어붙이기
        _emit(logger, "   🔗 트랙 크로스페이드 연결 중...")
        mixed = tracks[0]
        for i, track in enumerate(tracks[1:], 1):
            effective_crossfade = _safe_crossfade_ms(mixed, track, crossfade_ms)
            _emit(logger, f"   ↔️  {i}/{len(tracks)-1} 크로스페이드 연결... ({effective_crossfade/1000:.1f}초)")
            mixed = mixed.append(track, crossfade=effective_crossfade)

        current_min = len(mixed) / 1000 / 60
        _emit(logger, f"   ⏱️  현재 길이: {current_min:.1f}분")

        # 4. 목표 시간에 못 미치면 루프로 채우기
        if len(mixed) < target_ms:
            remaining = target_ms - len(mixed)
            _emit(logger, f"   🔁 {remaining//1000//60}분 {remaining//1000%60}초 부족 — 루프로 채우는 중...")
            filler = mixed
            while len(mixed) < target_ms + crossfade_ms:
                mixed = mixed.append(filler, crossfade=_safe_crossfade_ms(mixed, filler, crossfade_ms))

        mixed = mixed[:target_ms]

    # 5. 최종 볼륨 정규화
    if normalize_audio:
        _emit(logger, "   🎚️  최종 노말라이제이션 적용 중...")
        mixed = normalize(mixed)

    # 6. 저장
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path_str = str(output_path)
    _emit(logger, f"   💾 저장 중: {output_path_str}")
    if output_format == 'wav':
        mixed.export(output_path_str, format='wav')
    else:
        mixed.export(output_path_str, format='mp3', bitrate='320k')

    final_min = len(mixed) / 1000 / 60
    _emit(logger, f"   ✅ 완료! 최종 길이: {final_min:.1f}분 ({output_path_str})")
    return output_path_str
