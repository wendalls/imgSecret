"""Build publication-ready contact sheets and the Stage-I/II timing chart."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent if PROJECT.name == "code" else PROJECT
ASSETS = ROOT / "paper_assets"


def _font(size: int, bold: bool = False):
    windows = Path("C:/Windows/Fonts")
    name = "arialbd.ttf" if bold else "arial.ttf"
    try:
        return ImageFont.truetype(str(windows / name), size)
    except OSError:
        return ImageFont.load_default()


def _paste_image(canvas, draw, image, x, y, width, height, label, *, label_size=21):
    rendered = image.convert("RGB").resize((width, height), Image.Resampling.NEAREST)
    canvas.paste(rendered, (x, y))
    draw.rectangle((x, y, x + width - 1, y + height - 1), outline="#505050", width=2)
    draw.text((x, y + height + 6), label, fill="black", font=_font(label_size))


def _load(path: Path) -> Image.Image:
    return Image.open(path).convert("L")


def _region_image(path: Path, region: int, expansion: int = 3) -> Image.Image:
    expanded = np.asarray(_load(path), dtype=np.uint8)
    width = expanded.shape[1] // expansion
    return Image.fromarray(expanded[:, region * width : (region + 1) * width], mode="L")


def _xor_region(directory: Path, coalition: tuple[int, ...], region: int, expansion: int) -> Image.Image:
    result = None
    for participant in coalition:
        gray = np.asarray(
            _region_image(directory / f"share_{participant:03d}.png", region, expansion),
            dtype=np.uint8,
        )
        bits = (gray < 128).astype(np.uint8)
        result = bits if result is None else result ^ bits
    if result is None:
        raise ValueError("coalition must be nonempty")
    return Image.fromarray(np.where(result, 0, 255).astype(np.uint8), mode="L")


def _xor_expanded(directory: Path, coalition: tuple[int, ...]) -> Image.Image:
    result = None
    for participant in coalition:
        gray = np.asarray(_load(directory / f"share_{participant:03d}.png"), dtype=np.uint8)
        bits = (gray < 128).astype(np.uint8)
        result = bits if result is None else result ^ bits
    if result is None:
        raise ValueError("coalition must be nonempty")
    return Image.fromarray(np.where(result, 0, 255).astype(np.uint8), mode="L")


def _make_general_sheet() -> None:
    general = ASSETS / "general_n4_chain"
    items = [("Secret", general / "secret_binary.png")]
    items += [(f"Share P{i}", general / f"share_{i:03d}.png") for i in range(1, 5)]
    size, gap, top = 245, 38, 105
    canvas = Image.new("RGB", (2 * size + 3 * gap, 3 * (size + 45) + top + 15), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((28, 14), "n=4 chain access structure", fill="black", font=_font(27, True))
    draw.text((28, 52), "Q- = {{1,2}, {2,3}, {3,4}}", fill="black", font=_font(22))
    for index, (label, path) in enumerate(items):
        row, column = divmod(index, 2)
        x = gap + column * (size + gap)
        y = top + row * (size + 50)
        _paste_image(canvas, draw, _load(path), x, y, size, size, label)

    # Sixth cell: show all three qualified recoveries compactly.
    panel_x = gap + size + gap
    panel_y = top + 2 * (size + 50)
    draw.rectangle(
        (panel_x, panel_y, panel_x + size - 1, panel_y + size - 1),
        outline="#505050",
        width=2,
    )
    draw.text((panel_x + 12, panel_y + 10), "Qualified recoveries", fill="black", font=_font(18, True))
    recovered = (("{1,2}", "recovered_1_2.png"), ("{2,3}", "recovered_2_3.png"), ("{3,4}", "recovered_3_4.png"))
    thumb = 67
    for index, (label, filename) in enumerate(recovered):
        x = panel_x + 10 + index * 78
        y = panel_y + 58
        image = _load(general / filename).convert("RGB").resize((thumb, thumb), Image.Resampling.NEAREST)
        canvas.paste(image, (x, y))
        draw.rectangle((x, y, x + thumb - 1, y + thumb - 1), outline="#505050", width=1)
        draw.text((x + 4, y + thumb + 5), label, fill="black", font=_font(15))
    draw.text((panel_x + 19, panel_y + 170), "Each XOR equals S", fill="black", font=_font(18))
    draw.text((panel_x, panel_y + size + 6), "Recovered phone.png", fill="black", font=_font(20))
    canvas.save(ASSETS / "fig_general_n4.png", optimize=True)


def _make_mixed_n5_sheet() -> None:
    """Show one whole expanded XOR image for each qualified coalition."""
    source = ASSETS / "general_n5_mixed" / "images"
    canvas = Image.new("RGB", (1800, 1060), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (38, 18),
        "Mixed-cardinality general access structure (n=5, m*=2)",
        fill="black",
        font=_font(34, True),
    )
    draw.text(
        (38, 62),
        "Q- = {{1,2}, {1,3}, {1,4,5}, {2,3,4}, {2,3,5}}",
        fill="black",
        font=_font(24),
    )

    _paste_image(
        canvas,
        draw,
        _load(source / "secret_binary.png"),
        42,
        125,
        260,
        260,
        "Secret",
        label_size=22,
    )
    share_width, share_height = 410, 205
    for index in range(5):
        row, column = divmod(index, 3)
        x = 350 + column * 465
        y = 125 + row * 275
        _paste_image(
            canvas,
            draw,
            _load(source / f"share_{index + 1:03d}.png"),
            x,
            y,
            share_width,
            share_height,
            f"Expanded share P{index + 1} (two regions)",
            label_size=20,
        )

    draw.line((38, 685, 1762, 685), fill="#888888", width=2)
    draw.text(
        (38, 704),
        "Whole expanded-share XOR for every minimal qualified coalition",
        fill="black",
        font=_font(29, True),
    )
    coalitions = (
        (1, 2),
        (1, 3),
        (1, 4, 5),
        (2, 3, 4),
        (2, 3, 5),
    )
    for index, coalition in enumerate(coalitions):
        panel_x = 38 + index * 350
        region_matches = [
            np.array_equal(
                np.asarray(_xor_region(source, coalition, region, 2)),
                np.asarray(_load(source / "secret_binary.png")),
            )
            for region in range(2)
        ]
        recovering = ", ".join(
            f"R{region + 1}" for region, exact in enumerate(region_matches) if exact
        )
        _paste_image(
            canvas,
            draw,
            _xor_expanded(source, coalition),
            panel_x,
            790,
            315,
            158,
            "{" + ",".join(map(str, coalition)) + f"}}; S in {recovering}",
            label_size=17,
        )
    draw.text(
        (38, 1000),
        "Each panel is one complete XOR image with horizontal blocks [R1 | R2] (512 x 1024).",
        fill="black",
        font=_font(20),
    )
    canvas.save(ASSETS / "fig_general_n5_mixed.png", optimize=True)


def _make_threshold_sheet() -> None:
    threshold = ASSETS / "threshold_3_6"
    canvas = Image.new("RGB", (900, 1290), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((25, 18), "Complete (3,6) threshold scheme", fill="black", font=_font(31, True))

    _paste_image(canvas, draw, _load(threshold / "secret_binary.png"), 28, 78, 180, 180, "Secret")
    for index in range(6):
        row, column = divmod(index, 2)
        x = 250 + column * 320
        label_y = 75 + row * 117
        draw.text(
            (x, label_y),
            f"Expanded share P{index + 1}",
            fill="black",
            font=_font(16),
        )
        _paste_image(
            canvas,
            draw,
            _load(threshold / f"share_{index + 1:03d}.png"),
            x,
            label_y + 19,
            285,
            95,
            "",
            label_size=16,
        )

    draw.line((25, 435, 875, 435), fill="#888888", width=2)
    draw.text((25, 452), "Whole expanded-share XOR images", fill="black", font=_font(27, True))
    demonstrations = (
        (0, (1, 3, 5), "{1,3,5}: S occurs in region 1"),
        (1, (1, 2, 4), "{1,2,4}: S occurs in region 2"),
        (2, (1, 2, 3), "{1,2,3}: S occurs in region 3"),
    )
    secret = np.asarray(_load(threshold / "secret_binary.png"))
    for row, (recovering_region, coalition, heading) in enumerate(demonstrations):
        for region in range(3):
            recovered = _xor_region(threshold, coalition, region, 3)
            exact = np.array_equal(np.asarray(recovered), secret)
            if exact != (region == recovering_region):
                raise AssertionError("unexpected threshold regional recovery")
        y = 495 + row * 255
        draw.text((25, y), heading, fill="black", font=_font(19, True))
        _paste_image(
            canvas,
            draw,
            _xor_expanded(threshold, coalition),
            120,
            y + 32,
            660,
            220,
            "",
            label_size=16,
        )
    draw.text(
        (25, 1265),
        "Each panel is one complete XOR image with horizontal blocks [R1 | R2 | R3] (512 x 1536).",
        fill="black",
        font=_font(15),
    )
    canvas.save(ASSETS / "fig_threshold_3_6.png", optimize=True)


def make_contact_sheets() -> None:
    _make_threshold_sheet()
    _make_general_sheet()
    _make_mixed_n5_sheet()


def make_timing_chart() -> None:
    rows = json.loads((PROJECT / "results/candidate_experiments.json").read_text("utf-8"))
    width, height = 1400, 820
    left, right, top, bottom = 120, 60, 90, 130
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((left, 25), "General-access Stage I / Stage II median runtime", fill="black", font=_font(32, True))
    max_value = max(max(row["t_gen_median_s"], row["t_ip_median_s"]) for row in rows) * 1.16
    chart_h = height - top - bottom
    chart_w = width - left - right
    draw.line((left, top, left, top + chart_h), fill="black", width=3)
    draw.line((left, top + chart_h, left + chart_w, top + chart_h), fill="black", width=3)
    for tick in range(8):
        value = max_value * tick / 7
        y = top + chart_h - chart_h * tick / 7
        draw.line((left - 8, y, left + chart_w, y), fill="#dddddd" if tick else "black", width=1)
        draw.text((18, y - 12), f"{value:.2f}", fill="black", font=_font(19))
    draw.text((15, top - 38), "seconds", fill="black", font=_font(20))
    group_w = chart_w / len(rows)
    bar_w = 74
    colors = ("#2f6db3", "#e07a2d")
    for index, row in enumerate(rows):
        center = left + group_w * (index + 0.5)
        for offset, key in enumerate(("t_gen_median_s", "t_ip_median_s")):
            value = row[key]
            x0 = center + (-bar_w - 6 if offset == 0 else 6)
            y0 = top + chart_h - chart_h * value / max_value
            draw.rectangle((x0, y0, x0 + bar_w, top + chart_h), fill=colors[offset])
            draw.text((x0 - 2, y0 - 27), f"{value:.3f}", fill="black", font=_font(17))
        label = row["instance"]
        bbox = draw.textbbox((0, 0), label, font=_font(21, True))
        draw.text((center - (bbox[2] - bbox[0]) / 2, top + chart_h + 22), label, fill="black", font=_font(21, True))
    legend_y = height - 55
    for index, (label, color) in enumerate((("Stage I: candidate generation", colors[0]), ("Stage II: exact 0-1 selection", colors[1]))):
        x = left + index * 390
        draw.rectangle((x, legend_y, x + 28, legend_y + 22), fill=color)
        draw.text((x + 38, legend_y - 2), label, fill="black", font=_font(19))
    canvas.save(ASSETS / "fig_stage_timing.png", optimize=True)


if __name__ == "__main__":
    make_contact_sheets()
    make_timing_chart()
