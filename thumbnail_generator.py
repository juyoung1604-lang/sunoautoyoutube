import json, random
from groq import Groq
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from pathlib import Path

class ThumbnailGenerator:
    WIDTH = 1280
    HEIGHT = 720

    def __init__(self, api_key: str):
        self.client = Groq(api_key=api_key)

    def generate(self, title: str, style_prompt: str, output_path: str):
        design = self._get_design_spec(title, style_prompt)
        img = self._create_image(title, design)
        img.save(output_path, 'JPEG', quality=95)
        return output_path

    def _get_design_spec(self, title, style_prompt):
        prompt = f"""YouTube 썸네일 디자인 스펙을 JSON으로 생성하세요.
노래: {title}
스타일: {style_prompt}

반드시 아래 JSON만 응답 (다른 텍스트 없이):
{{"bg_color_1":"#0a0015","bg_color_2":"#1a0030","accent_color":"#c77dff","text_color":"#ffffff","shadow_color":"#9d4edd","emoji":"🎵","subtitle":"짧은 감성 문구(8자이내)","glow_intensity":8}}

곡 분위기에 맞는 색상 선택. 새벽/슬픔→딥퍼플/블루, 신남→오렌지/핑크, 사랑→로즈/코랄"""

        response = self.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8, max_tokens=300
        )
        text = response.choices[0].message.content.strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"): text = text[4:]
        try:
            return json.loads(text.strip())
        except:
            return {"bg_color_1":"#0a0015","bg_color_2":"#1a0030","accent_color":"#c77dff",
                    "text_color":"#ffffff","shadow_color":"#9d4edd","emoji":"🎵",
                    "subtitle":"감성 음악","glow_intensity":8}

    def _hex_to_rgb(self, h):
        h = h.lstrip('#')
        return tuple(int(h[i:i+2],16) for i in (0,2,4))

    def _create_image(self, title, design):
        img = Image.new('RGBA', (self.WIDTH, self.HEIGHT), (0,0,0,255))
        draw = ImageDraw.Draw(img)

        # 그라데이션 배경
        rgb1 = self._hex_to_rgb(design.get('bg_color_1','#0a0015'))
        rgb2 = self._hex_to_rgb(design.get('bg_color_2','#1a0030'))
        for i in range(self.HEIGHT):
            ratio = i / self.HEIGHT
            r = int(rgb1[0]+(rgb2[0]-rgb1[0])*ratio)
            g = int(rgb1[1]+(rgb2[1]-rgb1[1])*ratio)
            b = int(rgb1[2]+(rgb2[2]-rgb1[2])*ratio)
            draw.line([(0,i),(self.WIDTH,i)], fill=(r,g,b))

        # 장식 원
        acc = self._hex_to_rgb(design.get('accent_color','#c77dff'))
        for cx,cy,radius in [(200,150,180),(1100,580,140),(640,80,90)]:
            for r in range(radius,0,-3):
                alpha = int(20*(1-r/radius))
                draw.ellipse([(cx-r,cy-r),(cx+r,cy+r)], outline=acc+(alpha,), width=1)

        # 폰트
        def get_font(size):
            for fp in ["/opt/homebrew/share/fonts/nanum/NanumGothicBold.ttf",
                       "/Library/Fonts/AppleSDGothicNeo.ttc",
                       "/System/Library/Fonts/AppleSDGothicNeo.ttc",
                       "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"]:
                try: return ImageFont.truetype(fp, size)
                except: pass
            return ImageFont.load_default()

        title_font = get_font(88)
        sub_font = get_font(44)
        emoji_font = get_font(100)

        # 텍스트 줄바꿈
        def wrap(text, font, max_w):
            lines, cur = [], ""
            for ch in text:
                test = cur+ch
                bb = font.getbbox(test)
                if bb[2]-bb[0] <= max_w: cur = test
                else:
                    if cur: lines.append(cur)
                    cur = ch
            if cur: lines.append(cur)
            return lines

        lines = wrap(title, title_font, int(self.WIDTH*0.8))
        line_h = 100
        total_h = len(lines)*line_h + 60
        start_y = (self.HEIGHT - total_h) // 2
        cx = self.WIDTH // 2

        # 이모지
        emoji = design.get('emoji','🎵')
        draw.text((cx, start_y-90), emoji, font=emoji_font,
                  fill=self._hex_to_rgb(design.get('text_color','#ffffff')),
                  anchor="mm")

        # 글로우 + 제목
        glow = self._hex_to_rgb(design.get('shadow_color','#9d4edd'))
        gi = design.get('glow_intensity', 8)
        text_color = self._hex_to_rgb(design.get('text_color','#ffffff'))

        for i, line in enumerate(lines):
            y = start_y + i*line_h
            glow_layer = Image.new('RGBA', img.size, (0,0,0,0))
            gd = ImageDraw.Draw(glow_layer)
            for off in range(gi,0,-2):
                alpha = int(90*(1-off/gi))
                for dx,dy in [(-off,0),(off,0),(0,-off),(0,off)]:
                    gd.text((cx+dx, y+dy), line, font=title_font,
                            fill=glow+(alpha,), anchor="mm")
            glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(3))
            img.paste(glow_layer, mask=glow_layer)
            draw.text((cx, y), line, font=title_font, fill=text_color, anchor="mm")

        # 부제목
        subtitle = design.get('subtitle','')
        if subtitle:
            sub_y = start_y + len(lines)*line_h + 20
            draw.text((cx, sub_y), subtitle, font=sub_font,
                      fill=acc, anchor="mm")

        # 하단 바
        bar_w = random.randint(400,900)
        bar_x = (self.WIDTH-bar_w)//2
        draw.rectangle([(bar_x, self.HEIGHT-8),(bar_x+bar_w, self.HEIGHT)], fill=acc)

        return img.convert('RGB')
