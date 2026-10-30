import io
import random
from PIL import Image, ImageDraw, ImageFont

# Non-ambiguous alphanumeric characters (excluding 0, O, 1, I)
CAPTCHA_CHARS = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def generate_captcha_text(length=5):
    """Generate a random alphanumeric CAPTCHA text string."""
    return "".join(random.choice(CAPTCHA_CHARS) for _ in range(length))


def generate_captcha_image(code):
    """
    Render a clean, stylized, dark-themed CAPTCHA image with noise and subtle letter rotation.
    Returns PNG image bytes.
    """
    width, height = 180, 54
    # Dark charcoal background matching dark UI theme (#12161a)
    image = Image.new("RGB", (width, height), color=(18, 22, 26))
    draw = ImageDraw.Draw(image)

    # Random subtle noise dots
    for _ in range(75):
        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)
        draw.point(
            (x, y),
            fill=(
                random.randint(45, 95),
                random.randint(55, 115),
                random.randint(65, 135),
            ),
        )

    # Random noise lines
    for _ in range(4):
        x1, y1 = random.randint(0, width), random.randint(0, height)
        x2, y2 = random.randint(0, width), random.randint(0, height)
        draw.line(
            [(x1, y1), (x2, y2)],
            fill=(
                random.randint(40, 85),
                random.randint(50, 105),
                random.randint(70, 130),
            ),
            width=random.randint(1, 2),
        )

    # Try loading clean sans-serif fonts
    font = None
    for font_name in ["arial.ttf", "DejaVuSans.ttf", "calibri.ttf", "tahoma.ttf", "Arial.ttf"]:
        try:
            font = ImageFont.truetype(font_name, 28)
            break
        except Exception:
            continue
    if not font:
        font = ImageFont.load_default()

    # Brand vibrant colors matching J CSD UI
    colors = [
        (90, 163, 255),   # vibrant blue
        (246, 190, 93),   # warm amber
        (47, 207, 122),   # emerald green
        (179, 127, 235),  # neon purple
        (243, 245, 247),  # clean white
    ]

    char_spacing = (width - 32) // max(len(code), 1)
    for i, ch in enumerate(code):
        char_img = Image.new("RGBA", (38, 46), (0, 0, 0, 0))
        char_draw = ImageDraw.Draw(char_img)
        color = random.choice(colors)
        char_draw.text((4, 2), ch, font=font, fill=color)

        angle = random.randint(-20, 20)
        rotated = char_img.rotate(angle, resample=Image.BICUBIC, expand=1)

        x = 16 + i * char_spacing + random.randint(-2, 3)
        y = (height - rotated.height) // 2 + random.randint(-2, 2)
        image.paste(rotated, (x, y), rotated)

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()

