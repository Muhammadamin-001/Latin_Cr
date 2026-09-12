import io
from PIL import Image, ImageDraw, ImageFont

DEFAULT_WATERMARK_TEXT = "🔐 Himoyalangan rasm"

FONT_CANDIDATES = [
    "DejaVuSans-Bold.ttf",
    "Arial-Bold.ttf",
    "arialbd.ttf",
    "arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def open_image(image_bytes: bytes) -> Image.Image:
    """Baytlardan rasmni ochadi va RGB formatga o'giradi."""
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")
    return img


def _load_font(size: int) -> ImageFont.ImageFont:
    """Mavjud shriftlardan birini yuklaydi, topilmasa standart shriftga o'tadi."""
    for name in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _draw_text_with_outline(draw, xy, text, font, fill, outline_fill, outline_width):
    """Matnni chiroyli, o'qilishi oson bo'lishi uchun konturli (outline/shadow) chizadi."""
    x, y = xy
    for ox in range(-outline_width, outline_width + 1):
        for oy in range(-outline_width, outline_width + 1):
            if ox == 0 and oy == 0:
                continue
            draw.text((x + ox, y + oy), text, font=font, fill=outline_fill)
    draw.text((x, y), text, font=font, fill=fill)


def apply_watermark(img: Image.Image, text: str) -> io.BytesIO:
    """
    Rasmga ikki qatlamli watermark qo'shadi:
      1) Butun rasm bo'ylab diagonal, shaffof, takrorlanuvchi naqsh —
         rasmni ruxsatsiz o'g'irlash/qirqishdan himoya qilish uchun.
      2) Pastki o'ng burchakda aniq, konturli "brend" yozuvi —
         kanal/muallif nomini ko'rsatish uchun.
    Shrift o'lchami rasm o'lchamiga nisbatan avtomatik moslashadi (Smart Font).
    """
    text = text.strip() if text and text.strip() else DEFAULT_WATERMARK_TEXT

    base = img.convert("RGBA")
    width, height = base.size
    short_side = min(width, height)

    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    measure_draw = ImageDraw.Draw(overlay)

    # ---------- 1) Diagonal, takrorlanuvchi himoya naqshi ----------
    tile_font_size = max(16, int(short_side / 16))
    tile_font = _load_font(tile_font_size)
    tile_text_w, tile_text_h = _text_size(measure_draw, text, tile_font)

    pad = tile_font_size * 3
    tile = Image.new("RGBA", (tile_text_w + pad, tile_text_h + pad), (0, 0, 0, 0))
    tile_draw = ImageDraw.Draw(tile)
    tx = (tile.width - tile_text_w) // 2
    ty = (tile.height - tile_text_h) // 2
    _draw_text_with_outline(
        tile_draw, (tx, ty), text, tile_font,
        fill=(255, 255, 255, 55),
        outline_fill=(0, 0, 0, 45),
        outline_width=max(1, tile_font_size // 20),
    )
    tile = tile.rotate(30, expand=True, resample=Image.BICUBIC)

    step_x, step_y = tile.width, tile.height
    for y in range(-step_y, height + step_y, step_y):
        for x in range(-step_x, width + step_x, step_x):
            overlay.alpha_composite(tile, (x, y))

    # ---------- 2) Pastki o'ng burchakdagi aniq brend yozuvi ----------
    brand_font_size = max(20, int(short_side / 11))
    brand_font = _load_font(brand_font_size)
    brand_w, brand_h = _text_size(measure_draw, text, brand_font)

    margin = max(10, int(short_side * 0.025))
    pos_x = max(margin, width - brand_w - margin)
    pos_y = max(margin, height - brand_h - margin)

    _draw_text_with_outline(
        measure_draw, (pos_x, pos_y), text, brand_font,
        fill=(255, 255, 255, 235),
        outline_fill=(0, 0, 0, 190),
        outline_width=max(2, brand_font_size // 14),
    )

    watermarked = Image.alpha_composite(base, overlay).convert("RGB")

    bio = io.BytesIO()
    bio.name = "watermark.jpg"
    watermarked.save(bio, "JPEG", quality=95, optimize=True)
    bio.seek(0)
    return bio