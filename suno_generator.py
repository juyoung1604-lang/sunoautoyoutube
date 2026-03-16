import os, time, json, requests
import anthropic
from pathlib import Path

class SunoGenerator:
    def __init__(self, suno_cookie, anthropic_api_key):
        self.suno_cookie = suno_cookie
        self.anthropic_client = anthropic.Anthropic(api_key=anthropic_api_key)
        self._init_suno_client()

    def _init_suno_client(self):
        try:
            from suno import Suno, ModelVersions
            self.client = Suno(cookie=self.suno_cookie, model_version=ModelVersions.CHIRP_V3_5)
            print("   ✅ Suno AI 연결 완료")
        except ImportError:
            raise ImportError("SunoAI 미설치: pip install SunoAI")

    def check_credits(self):
        try:
            return self.client.get_credits()
        except Exception as e:
            print(f"   ⚠️  크레딧 확인 실패: {e}")
            return -1

    def generate_prompt(self, persona, theme=None, style=None):
        theme_text = f"\n테마: {theme}" if theme else ""
        style_text = f"\n스타일: {style}" if style else ""
        prompt = f"""Suno AI 음악 프롬프트를 JSON으로 생성하세요.
페르소나: {persona}{theme_text}{style_text}
JSON만 응답:
{{"title":"곡 제목(한국어,20자이내)","tags":"장르 태그(영어)","lyrics":"가사([Verse],[Chorus],[Bridge] 구조)","style_description":"스타일 설명(영어,50단어이내)"}}"""
        msg = self.anthropic_client.messages.create(
            model="claude-sonnet-4-20250514", max_tokens=1500,
            messages=[{"role":"user","content":prompt}])
        text = msg.content[0].text.strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"): text = text[4:]
        return json.loads(text.strip())

    def generate_and_download(self, persona, theme=None, style=None, output_dir="./suno_downloads", wait=True):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        credits = self.check_credits()
        if credits != -1:
            print(f"   💳 남은 크레딧: {credits}")
            if credits < 10:
                raise RuntimeError(f"크레딧 부족: {credits}")
        print("   🤖 프롬프트 작성 중...")
        prompt_data = self.generate_prompt(persona, theme, style)
        print(f"   📝 제목: {prompt_data['title']}")
        print("   🎵 노래 생성 중... (1-3분 소요)")
        clips = self.client.generate(
            prompt=prompt_data['lyrics'], tags=prompt_data['tags'],
            title=prompt_data['title'], make_instrumental=False,
            is_custom=True, wait_audio=wait)
        if not clips:
            raise RuntimeError("Suno 생성 실패")
        print(f"   ✅ {len(clips)}곡 생성 완료!")
        results = []
        for i, clip in enumerate(clips):
            safe = "".join(c for c in prompt_data['title'] if c.isalnum() or c in ' _-').strip().replace(' ','_')
            mp3_path = output_dir / f"{safe}_{clip.id[:8]}.mp3"
            self._download(clip.audio_url, str(mp3_path))
            results.append({'mp3_path':str(mp3_path),'title':prompt_data['title'],
                'song_id':clip.id,'image_url':getattr(clip,'image_url',None),'prompt_data':prompt_data})
            print(f"   💾 저장: {mp3_path.name}")
        return results

    def _download(self, url, path, retries=3):
        for i in range(retries):
            try:
                r = requests.get(url, stream=True, timeout=60)
                r.raise_for_status()
                with open(path,'wb') as f:
                    for chunk in r.iter_content(8192): f.write(chunk)
                return
            except Exception as e:
                if i < retries-1: time.sleep(2**i)
                else: raise RuntimeError(f"다운로드 실패: {e}")

    @staticmethod
    def get_cookie_guide():
        return """
📋 Suno 쿠키 얻는 방법:
1. suno.com 로그인
2. F12 → Network 탭
3. 새로고침 (Cmd+R)
4. 필터에 _clerk_js_version 입력
5. 뜬 요청 클릭 → Headers 탭
6. Cookie: 값 전체 복사 → .env의 SUNO_COOKIE에 붙여넣기
"""
