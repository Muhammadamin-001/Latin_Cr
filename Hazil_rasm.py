import telebot
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import io
import re
import textwrap

def clean_text(text):
    return re.sub(r'[^\x00-\x7Fа-яА-ЯёЁoʻo\'g\'s\' \n!?,.()]+', '', text)

def open_image(image_bytes):
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")
    return img

def apply_effects(img):
    # Sharpness
    sharp_enhancer = ImageEnhance.Sharpness(img)
    img = sharp_enhancer.enhance(2.0)
    # Blur effect - kam blur
    img = img.filter(ImageFilter.GaussianBlur(radius=0.2))
    # Darken
    enhancer = ImageEnhance.Brightness(img)
    img = enhancer.enhance(0.98)
    return img

def draw_caption(img, user_text):
    # Font size - JUDA KATTAROQ
    font_size = int(img.width / 6) if img.width > 400 else 60
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except:
        font = ImageFont.load_default()
    
    avg_char_width = font_size * 0.65
    max_chars_per_line = max(1, int((img.width * 0.85) / avg_char_width))
    lines = textwrap.wrap(user_text, width=max_chars_per_line)
    
    line_height = font_size + 20
    
    # Fon balandligi - MATN UCHUN YETARLI
    rect_height = len(lines) * line_height + 60
    
    # Yuqori qismi
    y_top_offset = 35
    
    img_rgba = img.convert('RGBA')
    
    # YUQORI FONI - SHAFFOF BLUR
    overlay_top = Image.new('RGBA', img_rgba.size, (0, 0, 0, 0))
    draw_overlay_top = ImageDraw.Draw(overlay_top)
    draw_overlay_top.rectangle([0, 0, img_rgba.width, rect_height + 60], fill=(0, 0, 0, 80))
    
    # Overlay ni blur qilish - shaffof blur
    overlay_top_blurred = overlay_top.filter(ImageFilter.GaussianBlur(radius=3))
    img_rgba = Image.alpha_composite(img_rgba, overlay_top_blurred)
    
    img = img_rgba.convert('RGB')
    draw = ImageDraw.Draw(img)
    
    # YUQORI MATN - FAQAT YUQORIGA
    y_offset_top = y_top_offset + 20
    for line in lines:
        # Outline effekti
        outline_color = (0, 0, 0)
        x_pos = 30
        
        # Outline
        for adj_x in [-2, -1, 0, 1, 2]:
            for adj_y in [-2, -1, 0, 1, 2]:
                if adj_x != 0 or adj_y != 0:
                    draw.text((x_pos + adj_x, y_offset_top + adj_y), line, fill=outline_color, font=font)
        
        # Asosiy BRIGHT OQQQ matn
        draw.text((x_pos, y_offset_top), line, fill=(255, 255, 255), font=font)
        y_offset_top += line_height
    
    bio = io.BytesIO()
    bio.name = 'meme.jpg'
    img.save(bio, 'JPEG', quality=95)
    bio.seek(0)
    return bio