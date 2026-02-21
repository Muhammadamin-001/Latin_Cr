import telebot
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import io
import re
import textwrap

def clean_text(text):
    return re.sub(r"[^\x00-\x7Fа-яА-ЯёЁoʻo'g's' \n!?,.()]+", '', text)

def open_image(image_bytes):
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")
    return img

def apply_effects(img):
    # Sharpness
    sharp_enhancer = ImageEnhance.Sharpness(img)
    img = sharp_enhancer.enhance(2.0)
    # Blur effect
    img = img.filter(ImageFilter.GaussianBlur(radius=0.5))
    # Darken
    enhancer = ImageEnhance.Brightness(img)
    img = enhancer.enhance(0.9)
    return img

def draw_caption(img, user_text):
    font_size = int(img.width / 18) if img.width > 400 else 25
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except:
        font = ImageFont.load_default()
    avg_char_width = font_size * 0.55
    max_chars_per_line = max(1, int((img.width * 0.9) / avg_char_width))
    lines = textwrap.wrap(user_text, width=max_chars_per_line)
    line_height = font_size + 10
    y_offset = 30
    rect_height = len(lines) * line_height + 20
    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    draw_overlay = ImageDraw.Draw(overlay)
    draw_overlay.rectangle([0, 0, img.width, rect_height + 30], fill=(0, 0, 0, 130))
    img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')
    draw = ImageDraw.Draw(img)
    for line in lines:
        draw.text((25, y_offset), line, fill=(255, 255, 255), font=font)
        y_offset += line_height
    bio = io.BytesIO()
    bio.name = 'meme.jpg'
    img.save(bio, 'JPEG', quality=95)
    bio.seek(0)
    return bio