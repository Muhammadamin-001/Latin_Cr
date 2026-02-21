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
    img = img.filter(ImageFilter.GaussianBlur(radius=0.3))
    # Darken
    enhancer = ImageEnhance.Brightness(img)
    img = enhancer.enhance(0.92)
    return img

def draw_caption(img, user_text):
    # Font size - KATTAROQ
    font_size = int(img.width / 10) if img.width > 400 else 40
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except:
        font = ImageFont.load_default()
    
    avg_char_width = font_size * 0.58
    max_chars_per_line = max(1, int((img.width * 0.88) / avg_char_width))
    lines = textwrap.wrap(user_text, width=max_chars_per_line)
    
    line_height = font_size + 18
    
    # Matnni yuqoriga va pastga qo'yish uchun
    rect_height = len(lines) * line_height + 50
    
    # Yuqori qismi - matn uchun
    y_top_offset = 25
    
    # Pastki qismi - matn uchun
    img_height = img.height
    y_bottom_offset = img_height - rect_height - 25
    
    img = img.convert('RGBA')
    
    # YUQORI FONI - blur effekti bilan
    overlay_top = Image.new('RGBA', img.size, (0, 0, 0, 0))
    draw_overlay_top = ImageDraw.Draw(overlay_top)
    draw_overlay_top.rectangle([0, 0, img.width, rect_height + 50], fill=(0, 0, 0, 155))
    
    # Overlay ni blur qilish
    overlay_top_blurred = overlay_top.filter(ImageFilter.GaussianBlur(radius=2))
    img = Image.alpha_composite(img, overlay_top_blurred)
    
    # PASTKI FONI - blur effekti bilan
    overlay_bottom = Image.new('RGBA', img.size, (0, 0, 0, 0))
    draw_overlay_bottom = ImageDraw.Draw(overlay_bottom)
    draw_overlay_bottom.rectangle([0, y_bottom_offset, img.width, img_height], fill=(0, 0, 0, 155))
    
    # Overlay ni blur qilish
    overlay_bottom_blurred = overlay_bottom.filter(ImageFilter.GaussianBlur(radius=2))
    img = Image.alpha_composite(img, overlay_bottom_blurred)
    
    img = img.convert('RGB')
    draw = ImageDraw.Draw(img)
    
    # YUQORI MATN
    y_offset_top = y_top_offset + 15
    for line in lines:
        # Outline effekti - qalin
        outline_color = (0, 0, 0)
        x_pos = 25
        
        # Qalinlik uchun bir nechta qatlamda outline
        for adj_x in [-3, -2, -1, 0, 1, 2, 3]:
            for adj_y in [-3, -2, -1, 0, 1, 2, 3]:
                if adj_x != 0 or adj_y != 0:
                    draw.text((x_pos + adj_x, y_offset_top + adj_y), line, fill=outline_color, font=font)
        
        # Asosiy oq matn - BRIGHT
        draw.text((x_pos, y_offset_top), line, fill=(255, 255, 255), font=font)
        y_offset_top += line_height
    
    # PASTKI MATN
    y_offset_bottom = y_bottom_offset + 15
    for line in lines:
        # Outline effekti - qalin
        outline_color = (0, 0, 0)
        x_pos = 25
        
        # Qalinlik uchun bir nechta qatlamda outline
        for adj_x in [-3, -2, -1, 0, 1, 2, 3]:
            for adj_y in [-3, -2, -1, 0, 1, 2, 3]:
                if adj_x != 0 or adj_y != 0:
                    draw.text((x_pos + adj_x, y_offset_bottom + adj_y), line, fill=outline_color, font=font)
        
        # Asosiy oq matn - BRIGHT
        draw.text((x_pos, y_offset_bottom), line, fill=(255, 255, 255), font=font)
        y_offset_bottom += line_height
    
    bio = io.BytesIO()
    bio.name = 'meme.jpg'
    img.save(bio, 'JPEG', quality=95)
    bio.seek(0)
    return bio