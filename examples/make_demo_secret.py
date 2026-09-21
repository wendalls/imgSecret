"""Create the deterministic binary secret image used by the visual tutorial."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def main() -> None:
    target = Path(__file__).with_name("secret.png")
    image = Image.new("1", (128, 80), color=1)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=22)
    draw.rounded_rectangle((4, 4, 123, 75), radius=10, outline=0, width=3)
    draw.text((31, 15), "SARR", font=font, fill=0)
    draw.text((24, 43), "SECRET", font=font, fill=0)
    image.save(target)
    print(target)


if __name__ == "__main__":
    main()
