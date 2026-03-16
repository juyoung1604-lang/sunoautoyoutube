import json
from groq import Groq

class MetadataGenerator:
    def __init__(self, api_key: str):
        self.client = Groq(api_key=api_key)

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

        response = self.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=1500
        )
        text = response.choices[0].message.content.strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"): text = text[4:]
        try:
            return json.loads(text.strip())
        except:
            return {
                "title": song_name,
                "description": f"{song_name}\n\n#인디음악 #AIMusic #감성음악",
                "tags": ["인디음악","감성","AIMusic","음악","뮤직"],
                "thumbnail_style": "dark atmospheric background with glowing text, cinematic mood"
            }

    def generate_with_context(self, song_name, song_title='', tags_hint='', lyrics_hint='') -> dict:
        prompt = f"""YouTube 음악 채널 메타데이터를 JSON으로 생성해주세요.

곡명: {song_name}
곡 제목: {song_title}
장르/스타일: {tags_hint}
가사 일부: {lyrics_hint}

반드시 아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{{
    "title": "YouTube 제목 (한국어, 50자 이내)",
    "description": "설명 (3-4문단, 해시태그 포함, 한국어)",
    "tags": ["태그1", "태그2", "태그3", "태그4", "태그5", "태그6", "태그7", "태그8", "태그9", "태그10"],
    "thumbnail_style": "썸네일 스타일 설명 (영어)"
}}"""

        response = self.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=1500
        )
        text = response.choices[0].message.content.strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"): text = text[4:]
        try:
            return json.loads(text.strip())
        except:
            return {
                "title": song_title or song_name,
                "description": f"{song_title}\n\n#인디음악 #AIMusic",
                "tags": ["인디음악","감성","AIMusic"],
                "thumbnail_style": "dark atmospheric background with glowing text"
            }
