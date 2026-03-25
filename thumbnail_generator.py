import json, random
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from pathlib import Path


def _parse_json(text: str) -> dict:
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


_DEFAULT_DESIGN = {
    "bg_color_1": "#0a0015", "bg_color_2": "#1a0030",
    "accent_color": "#c77dff", "text_color": "#ffffff",
    "shadow_color": "#9d4edd", "emoji": "🎵",
    "subtitle": "감성 음악", "glow_intensity": 8
}


class ThumbnailGenerator:
    WIDTH  = 1280
    HEIGHT = 720

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
                max_tokens=300,
                temperature=0.8,
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
                temperature=0.8,
                max_tokens=300
            )
            return response.choices[0].message.content

    def generate(self, title: str, style_prompt: str, output_path: str):
        design = self._get_design_spec(title, style_prompt)
        img = self._create_image(title, design)
        img.save(output_path, 'JPEG', quality=95)
        return output_path

    def _get_design_spec(self, title, style_prompt):
        prompt = f"""YouTube 음악 썸네일의 전문 비주얼 디자이너로서 아래 곡의 디자인 스펙을 JSON으로 제안하세요.

[곡 정보]
- 곡명: {title}
- 스타일 가이드: {style_prompt}

[디자인 가이드라인]
1. bg_color_1 & bg_color_2: 깊이감 있는 배경을 위한 두 가지 컬러 (그라데이션용). 곡의 분위기(예: 밤, 새벽, 여름, 가을 등)에 맞춰 선택.
2. accent_color: 텍스트나 포인트 요소에 사용할 눈에 띄는 컬러.
3. shadow_color: 텍스트 후광(glow) 효과를 위한 은은한 색상.
4. subtitle: "새벽 감성 믹스", "오늘 하루의 위로"와 같은 짧고 감성적인 카피(8자 이내).
5. emoji: 무드에 어울리는 이모지 1-2개.

반드시 아래 JSON 형식으로만 응답하세요:
{{
    "bg_color_1": "#HEX",
    "bg_color_2": "#HEX",
    "accent_color": "#HEX",
    "text_color": "#ffffff",
    "shadow_color": "#HEX",
    "emoji": "...",
    "subtitle": "...",
    "glow_intensity": 10
}}

분위기별 컬러 추천: 
- 감성/새벽: 딥네이비/퍼플/라벤더 
- 신나는/여름: 밝은오렌지/옐로우/코랄 
- 슬픈/조용한: 차가운블루/그레이 
- 몽환적인: 에메랄드/다크퍼플/피치"""
        try:
            return _parse_json(self._call(prompt))
        except Exception:
            return _DEFAULT_DESIGN.copy()

    def _hex_to_rgb(self, h):
        h = h.lstrip('#')
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

    def _create_image(self, title, design):
        # 기본 캔버스 생성 (RGBA)
        img = Image.new('RGBA', (self.WIDTH, self.HEIGHT), (0, 0, 0, 255))
        draw = ImageDraw.Draw(img)

        # 1. 고해상도 그라데이션 배경
        rgb1 = self._hex_to_rgb(design.get('bg_color_1', '#0a0015'))
        rgb2 = self._hex_to_rgb(design.get('bg_color_2', '#1a0030'))
        
        # 대각선 그라데이션 구현
        for y in range(self.HEIGHT):
            for x in range(self.WIDTH):
                # 대각선 비율 계산
                ratio = (x / self.WIDTH + y / self.HEIGHT) / 2
                r = int(rgb1[0] + (rgb2[0] - rgb1[0]) * ratio)
                g = int(rgb1[1] + (rgb2[1] - rgb1[1]) * ratio)
                b = int(rgb1[2] + (rgb2[2] - rgb1[2]) * ratio)
                draw.point((x, y), fill=(r, g, b, 255))

        # 2. 오버레이 효과 (은은한 노이즈 및 빛 망울)
        acc = self._hex_to_rgb(design.get('accent_color', '#c77dff'))
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        
        for _ in range(5): # 5개의 빛 망울
            cx, cy = random.randint(0, self.WIDTH), random.randint(0, self.HEIGHT)
            radius = random.randint(150, 400)
            for r in range(radius, 0, -5):
                alpha = int(15 * (1 - r / radius))
                odraw.ellipse([(cx-r, cy-r), (cx+r, cy+r)], fill=acc+(alpha,))
        
        img = Image.alpha_composite(img, overlay)
        draw = ImageDraw.Draw(img)

        # 3. 폰트 설정
        def get_font(size):
            for fp in ["/opt/homebrew/share/fonts/nanum/NanumGothicBold.ttf",
                       "/Library/Fonts/AppleSDGothicNeo.ttc",
                       "/System/Library/Fonts/AppleSDGothicNeo.ttc",
                       "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"]:
                try:
                    return ImageFont.truetype(fp, size)
                except Exception:
                    pass
            return ImageFont.load_default()

        title_font = get_font(96) # 폰트 크기 확대
        sub_font   = get_font(48)
        emoji_font = get_font(110)

        # 4. 텍스트 레이아웃 및 랩핑
        def wrap(text, font, max_w):
            lines, cur = [], ""
            for ch in text:
                test = cur + ch
                bb = font.getbbox(test)
                if bb[2] - bb[0] <= max_w:
                    cur = test
                else:
                    if cur: lines.append(cur)
                    cur = ch
            if cur: lines.append(cur)
            return lines

        lines = wrap(title, title_font, int(self.WIDTH * 0.85))
        line_h = 110
        total_h = len(lines) * line_h
        start_y = (self.HEIGHT - total_h) // 2 + 30
        cx = self.WIDTH // 2

        # 5. 후광(Glow) 효과가 들어간 텍스트 렌더링
        glow_color = self._hex_to_rgb(design.get('shadow_color', '#9d4edd'))
        text_color = self._hex_to_rgb(design.get('text_color', '#ffffff'))
        gi = design.get('glow_intensity', 12)

        # 이모지 상단 배치
        emoji = design.get('emoji', '🎵')
        draw.text((cx, start_y - 120), emoji, font=emoji_font, fill=text_color, anchor="mm")

        for i, line in enumerate(lines):
            y = start_y + i * line_h
            # 글로우 레이어
            glow_layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
            gd = ImageDraw.Draw(glow_layer)
            for off in range(gi, 0, -2):
                alpha = int(100 * (1 - off / gi))
                for dx, dy in [(-off, 0), (off, 0), (0, -off), (0, off)]:
                    gd.text((cx+dx, y+dy), line, font=title_font, fill=glow_color+(alpha,), anchor="mm")
            
            glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(4))
            img.paste(glow_layer, mask=glow_layer)
            # 메인 텍스트
            draw.text((cx, y), line, font=title_font, fill=text_color, anchor="mm")

        # 6. 서브타이틀 (감성 카피)
        subtitle = design.get('subtitle', '')
        if subtitle:
            sub_y = start_y + len(lines) * line_h + 40
            # 서브타이틀 배경 바
            tw = draw.textbbox((cx, sub_y), subtitle, font=sub_font, anchor="mm")
            padding = 20
            draw.rectangle([(tw[0]-padding, tw[1]-5), (tw[2]+padding, tw[3]+5)], 
                           fill=acc+(40,), outline=acc+(100,))
            draw.text((cx, sub_y), subtitle, font=sub_font, fill=acc, anchor="mm")

        # 7. 하단 진행 바 (장식 요소)
        bar_w = random.randint(500, 1000)
        bar_x = (self.WIDTH - bar_w) // 2
        bar_box = [(bar_x, self.HEIGHT-12), (bar_x+bar_w, self.HEIGHT-4)]
        if hasattr(draw, "rounded_rectangle"):
            draw.rounded_rectangle(bar_box, fill=acc+(180,), radius=4)
        else:
            draw.rectangle(bar_box, fill=acc+(180,))

        return img.convert('RGB')
