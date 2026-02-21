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
    # Font size - eski koddan
    font_size = int(img.width / 18) if img.width > 400 else 25
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except:
        font = ImageFont.load_default()
    
    # Matnni qatorlarga bo'lish - eski koddan
    avg_char_width = font_size * 0.55
    max_chars_per_line = max(1, int((img.width * 0.9) / avg_char_width))
    lines = textwrap.wrap(user_text, width=max_chars_per_line)

    # Matn uchun yarim shaffof fon (Rectangle overlay) - eski koddan
    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    draw_overlay = ImageDraw.Draw(overlay)
    
    line_height = font_size + 10
    rect_height = len(lines) * line_height + 20
    # Matn foni: qora rang, 130 darajali shaffoflik - BLUR QILINDI
    draw_overlay.rectangle([0, 0, img.width, rect_height + 30], fill=(0, 0, 0, 130))
    
    # Overlay ni blur qilish - SHAFFOF BLUR
    draw_overlay_blurred = overlay.filter(ImageFilter.GaussianBlur(radius=3))
    
    # Rasmni va fonni birlashtiramiz
    img = Image.alpha_composite(img.convert('RGBA'), draw_overlay_blurred).convert('RGB')
    draw = ImageDraw.Draw(img)

    # Matnni chizish (oq rangda)
    y_offset = 30
    for line in lines:
        # Outline effekti
        outline_color = (0, 0, 0)
        x_pos = 25
        
        # Outline
        for adj_x in [-2, -1, 0, 1, 2]:
            for adj_y in [-2, -1, 0, 1, 2]:
                if adj_x != 0 or adj_y != 0:
                    draw.text((x_pos + adj_x, y_offset + adj_y), line, fill=outline_color, font=font)
        
        # Asosiy oq matn
        draw.text((x_pos, y_offset), line, fill=(255, 255, 255), font=font)
        y_offset += line_height

    bio = io.BytesIO()
    bio.name = 'meme.jpg'
    img.save(bio, 'JPEG', quality=95)
    bio.seek(0)
    
    return bio