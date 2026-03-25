import json


def _parse_json(text: str) -> dict:
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def _fallback(song_name: str) -> dict:
    return {
        "title": song_name,
        "description": f"{song_name}\n\n#인디음악 #AIMusic #감성음악",
        "tags": ["인디음악", "감성", "AIMusic", "음악", "뮤직"],
        "thumbnail_style": "dark atmospheric background with glowing text, cinematic mood"
    }


class MetadataGenerator:
    def __init__(self, api_key: str, provider: str = 'groq'):
        self.provider = provider
        if provider == 'claude':
            import anthropic
            self._anthropic = anthropic.Anthropic(api_key=api_key)
        elif provider == 'gemini':
            from google import genai
            self._gemini = genai.Client(api_key=api_key)
        else:
            from groq import Groq
            self._client = Groq(api_key=api_key)

    def _call(self, prompt: str) -> str:
        if self.provider == 'claude':
            response = self._anthropic.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1500,
                temperature=0.7,
                messages=[{"role": "user", "content": prompt}],
            )
            parts = []
            for block in getattr(response, "content", []):
                if getattr(block, "type", "") == "text":
                    parts.append(block.text)
            return "\n".join(parts).strip()
        if self.provider == 'gemini':
            response = self._gemini.models.generate_content(
                model='gemini-2.0-flash', contents=prompt)
            return response.text
        else:
            response = self._client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=1500
            )
            return response.choices[0].message.content

    def generate(self, song_name: str, persona: str = None) -> dict:
        persona_ctx = f"\n아티스트 페르소나: {persona}" if persona else ""
        prompt = f"""YouTube 음악 채널 메타데이터를 JSON으로 생성해주세요.

노래 파일명: {song_name}{persona_ctx}

반드시 아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{{
    "title": "YouTube 제목 (한국어, 50자 이내, 감성적이고 검색최적화)",
    "description": "설명 (3-4문단, 해시태그 포함, 한국어)",
    "tags": ["태그1", "태그2", "태그3", "태그4", "태그5", "태그6", "태그7", "태그8", "태그9", "태그10", "태그11", "태그12", "태그13", "태그14", "태그15"],
    "thumbnail_style": "썸네일 스타일 설명 (영어, 색상/분위기/배치 구체적으로)"
}}"""
        try:
            return _parse_json(self._call(prompt))
        except Exception:
            return _fallback(song_name)

    def generate_with_context(self, song_name, song_title='', tags_hint='', lyrics_hint='') -> dict:
        prompt = f"""YouTube 음악 채널의 전문 마케터로서 아래 곡에 대한 최적화된 메타데이터를 JSON 형식으로 생성해주세요.

[입력 정보]
- 파일명: {song_name}
- 곡 제목(제공된 경우): {song_title}
- 장르/스타일 힌트: {tags_hint}
- 가사 힌트: {lyrics_hint}

[생성 가이드라인]
1. 제목(title): 
   - 클릭을 부르는 감성적인 제목 (예: "비 오는 날 듣기 좋은 감성 인디 팝 | {song_title or song_name}")
   - 한국어 위주로 작성하되 감각적인 단어 선택
2. 설명(description):
   - 3-4문단의 풍부한 내용
   - 1문단: 곡의 분위기와 감성 묘사
   - 2문단: 가사의 의미나 아티스트의 의도 (제공된 힌트 활용)
   - 3문단: 구독/좋아요 유도 및 저작권 관련 부드러운 안내
   - 하단에 관련 해시태그 10-15개 포함
3. 태그(tags): 
   - 검색 노출을 위한 핵심 키워드 15개 (음악 장르, 분위기, 악기, 상황 등)
4. 썸네일 스타일(thumbnail_style): 
   - AI 이미지 생성기에 입력할 수 있는 구체적인 영어 프롬프트
   - 곡의 분위기에 맞춘 배경, 광원, 색감(cinematic, dreamy, moody 등) 포함

반드시 아래 JSON 형식으로만 응답하세요:
{{
    "title": "...",
    "description": "...",
    "tags": ["...", "..."],
    "thumbnail_style": "..."
}}"""
        try:
            return _parse_json(self._call(prompt))
        except Exception:
            return _fallback(song_title or song_name)
