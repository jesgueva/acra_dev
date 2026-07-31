"""Deterministic renderer turning a `BolSpec` into a document.

Determinism is the point: the same spec plus the same fonts produces byte-identical output, so a
bench run can be repeated and an accuracy number can be attributed to a *model* change rather than
to a corpus that quietly drifted. The only randomness — scan grain on `poor_scan` — is drawn from a
seeded `random.Random`, never the global RNG.

Cross-platform caveat: byte-identity holds per host. Font availability differs between macOS and CI
Linux, so a PNG rendered on one will not hash-match the other. The determinism *tests* assert
same-host stability, which is what protects a baseline.
"""

from __future__ import annotations

import random
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .ground_truth import CORPUS, BolSpec

#: Fixes the scan grain on `poor_scan`. Changing it invalidates the recorded baseline.
NOISE_SEED = 20260730

_FONT_CANDIDATES_REGULAR = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)
_FONT_CANDIDATES_BOLD = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
)

_EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "application/pdf": ".pdf"}


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    """First available system font at `size`, falling back to Pillow's bundled face.

    `load_default(size=...)` returns a scalable FreeType font on Pillow >= 10.1, so the fallback
    stays legible to a vision model rather than collapsing to the old 11px bitmap.
    """
    for path in _FONT_CANDIDATES_BOLD if bold else _FONT_CANDIDATES_REGULAR:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _thousands_dot(value: float) -> str:
    """Format with European thousands separators: 17122 -> '17.122'."""
    return f"{int(value):,}".replace(",", ".")


def _header_block(
    draw: ImageDraw.ImageDraw,
    spec: BolSpec,
    labels: tuple[str, str, str, str],
    *,
    x: int,
    y: int,
    value_x: int,
    size: int,
    leading: int,
) -> int:
    """Draw the four header fields; returns the y coordinate below them."""
    values = (
        spec.rendered_supplier,
        spec.carrier,
        spec.bol_reference,
        spec.delivery_date.isoformat(),
    )
    for label, value in zip(labels, values):
        draw.text((x, y), label, font=_font(size, bold=True), fill="black")
        draw.text((value_x, y), value, font=_font(size), fill="black")
        y += leading
    return y


def _render_gridded(spec: BolSpec) -> Image.Image:
    """Ruled table with explicit column and row separators — the easy baseline."""
    width, height = 1000, 1180
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, width - 20, height - 20], outline="black", width=2)
    draw.text((40, 40), "BILL OF LADING", font=_font(40, bold=True), fill="black")
    draw.line([40, 95, width - 40, 95], fill="black", width=2)

    y = _header_block(
        draw,
        spec,
        ("Supplier:", "Carrier:", "BOL Reference:", "Delivery Date:"),
        x=40,
        y=120,
        value_x=320,
        size=24,
        leading=48,
    )

    y += 30
    columns = [40, 470, 620, 790, 950]
    headers = ("Material", "Pallets", "Units/Pallet", "Quantity")
    row_h = 56
    top = y
    bottom = y + row_h * (len(spec.items) + 1)

    for i, label in enumerate(headers):
        draw.text((columns[i] + 12, y + 16), label, font=_font(22, bold=True), fill="black")
    y += row_h
    for item in spec.items:
        cells = (
            item.item_name,
            str(item.pallets),
            str(item.units_per_pallet),
            f"{item.quantity:g}",
        )
        for i, cell in enumerate(cells):
            draw.text((columns[i] + 12, y + 14), cell, font=_font(22), fill="black")
        y += row_h

    for gx in columns:
        draw.line([gx, top, gx, bottom], fill="black", width=1)
    for r in range(len(spec.items) + 2):
        gy = top + r * row_h
        draw.line([columns[0], gy, columns[-1], gy], fill="black", width=1)
    return img


def _render_borderless(spec: BolSpec) -> Image.Image:
    """No rule lines, tight leading, columns nearly touching — the ISS-05 failure shape."""
    width, height = 620, 430
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw.text((36, 28), "BILL OF LADING", font=_font(26, bold=True), fill="black")

    y = _header_block(
        draw,
        spec,
        ("Supplier", "Carrier", "BOL Ref", "Date"),
        x=36,
        y=70,
        value_x=170,
        size=16,
        leading=24,
    )

    y += 18
    # Deliberately cramped: the three numeric columns sit ~60px apart with no separators and no
    # rule lines, so nothing but the triplet heuristic distinguishes pallets from units from total.
    columns = [36, 330, 400, 480]
    headers = ("Material", "Pallets", "Ud/Pallet", "Cantidad")
    for i, label in enumerate(headers):
        draw.text((columns[i], y), label, font=_font(15, bold=True), fill="black")
    y += 26
    for item in spec.items:
        cells = (
            item.item_name,
            str(item.pallets),
            str(item.units_per_pallet),
            f"{item.quantity:g}",
        )
        for i, cell in enumerate(cells):
            draw.text((columns[i], y), cell, font=_font(15), fill="black")
        y += 26
    return img


def _render_rotated(spec: BolSpec) -> Image.Image:
    """The gridded document photographed off-axis."""
    base = _render_gridded(spec)
    return base.rotate(-3.8, resample=Image.BICUBIC, expand=True, fillcolor="white")


def _render_spanish(spec: BolSpec) -> Image.Image:
    """Spanish headings and European thousands separators."""
    width, height = 1000, 900
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, width - 20, height - 20], outline="black", width=2)
    draw.text((40, 40), "ALBARÁN DE ENTREGA", font=_font(34, bold=True), fill="black")
    draw.line([40, 88, width - 40, 88], fill="black", width=2)

    y = _header_block(
        draw,
        spec,
        ("Proveedor:", "Transportista:", "Nº Albarán:", "Fecha de entrega:"),
        x=40,
        y=112,
        value_x=340,
        size=22,
        leading=44,
    )

    y += 24
    columns = [40, 500, 640, 810, 950]
    headers = ("Descripción", "Palets", "Ud. por palet", "Cantidad")
    row_h = 52
    top = y
    bottom = y + row_h * (len(spec.items) + 1)

    for i, label in enumerate(headers):
        draw.text((columns[i] + 10, y + 14), label, font=_font(19, bold=True), fill="black")
    y += row_h
    for item in spec.items:
        # The whole point of this layout: quantities printed 17.122, not 17122.
        cells = (
            item.item_name,
            str(item.pallets),
            _thousands_dot(item.units_per_pallet),
            _thousands_dot(item.quantity),
        )
        for i, cell in enumerate(cells):
            draw.text((columns[i] + 10, y + 12), cell, font=_font(19), fill="black")
        y += row_h

    for gx in columns:
        draw.line([gx, top, gx, bottom], fill="black", width=1)
    for r in range(len(spec.items) + 2):
        gy = top + r * row_h
        draw.line([columns[0], gy, columns[-1], gy], fill="black", width=1)
    return img


def _render_poor_scan(spec: BolSpec) -> Image.Image:
    """Grain, low contrast and blur, from a seeded RNG so the degradation is reproducible."""
    base = _render_gridded(spec).convert("L")

    rng = random.Random(NOISE_SEED)
    # Small noise field scaled up: same grain character as per-pixel noise at a fraction of the
    # cost, and trivially deterministic.
    small = (base.width // 4, base.height // 4)
    noise = Image.frombytes(
        "L", small, bytes(rng.randrange(256) for _ in range(small[0] * small[1]))
    ).resize(base.size, Image.BILINEAR)

    grainy = Image.blend(base, noise, 0.18)
    # Crush contrast toward mid-grey — a washed-out photocopy, not a clean scan.
    faded = grainy.point(lambda px: int(60 + px * 0.62))
    return faded.filter(ImageFilter.GaussianBlur(0.6)).convert("RGB")


def _render_degraded_fax(spec: BolSpec) -> Image.Image:
    """Every degradation at once: downscale, grain, contrast crush, blur, skew, JPEG.

    Deliberately the hardest document in the corpus. The gentler `poor_scan` turned out to be read
    perfectly by both providers, which leaves a saturated bench with no power to detect a
    regression; this one exists to find where the pipeline actually breaks.
    """
    base = _render_gridded(spec).convert("L")
    # Fax resolution: throw away detail, then resample back up so the loss is baked in.
    small_size = (int(base.width * 0.45), int(base.height * 0.45))
    faxed = base.resize(small_size, Image.BILINEAR).resize(base.size, Image.NEAREST)

    rng = random.Random(NOISE_SEED + 1)
    noise_size = (faxed.width // 3, faxed.height // 3)
    noise = Image.frombytes(
        "L", noise_size, bytes(rng.randrange(256) for _ in range(noise_size[0] * noise_size[1]))
    ).resize(faxed.size, Image.BILINEAR)

    grainy = Image.blend(faxed, noise, 0.40)
    washed = grainy.point(lambda px: int(88 + px * 0.42))
    blurred = washed.filter(ImageFilter.GaussianBlur(1.3))
    skewed = blurred.rotate(1.6, resample=Image.BICUBIC, expand=True, fillcolor=150)
    return skewed.convert("RGB")


def _render_multipage(spec: BolSpec) -> list[Image.Image]:
    """Two pages with the line items split across the break."""
    half = (len(spec.items) + 1) // 2
    pages: list[Image.Image] = []
    width, height = 950, 760

    for page_no, chunk in enumerate((spec.items[:half], spec.items[half:]), start=1):
        img = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(img)
        draw.text((36, 30), "BILL OF LADING", font=_font(30, bold=True), fill="black")
        draw.text((width - 200, 38), f"Page {page_no} of 2", font=_font(18), fill="black")
        draw.line([36, 78, width - 36, 78], fill="black", width=2)

        if page_no == 1:
            y = _header_block(
                draw,
                spec,
                ("Supplier:", "Carrier:", "BOL Reference:", "Delivery Date:"),
                x=36,
                y=100,
                value_x=300,
                size=20,
                leading=38,
            )
            y += 20
        else:
            # Page 2 carries only the reference, as a real continuation sheet does.
            draw.text((36, 100), "BOL Reference:", font=_font(20, bold=True), fill="black")
            draw.text((300, 100), spec.bol_reference, font=_font(20), fill="black")
            y = 158

        columns = [36, 470, 600, 780, 914]
        headers = ("Material", "Pallets", "Units/Pallet", "Quantity")
        row_h = 48
        top = y
        bottom = y + row_h * (len(chunk) + 1)

        for i, label in enumerate(headers):
            draw.text((columns[i] + 10, y + 13), label, font=_font(18, bold=True), fill="black")
        y += row_h
        for item in chunk:
            cells = (
                item.item_name,
                str(item.pallets),
                str(item.units_per_pallet),
                f"{item.quantity:g}",
            )
            for i, cell in enumerate(cells):
                draw.text((columns[i] + 10, y + 12), cell, font=_font(18), fill="black")
            y += row_h

        for gx in columns:
            draw.line([gx, top, gx, bottom], fill="black", width=1)
        for r in range(len(chunk) + 2):
            gy = top + r * row_h
            draw.line([columns[0], gy, columns[-1], gy], fill="black", width=1)
        pages.append(img)
    return pages


_RENDERERS = {
    "gridded": _render_gridded,
    "borderless_cramped": _render_borderless,
    "rotated": _render_rotated,
    "spanish": _render_spanish,
    "poor_scan": _render_poor_scan,
    "degraded_fax": _render_degraded_fax,
}


#: Pillow stamps the wall-clock time into a PDF's CreationDate/ModDate, which makes two otherwise
#: identical renders differ. Replaced with a fixed timestamp of the *same length* so the xref byte
#: offsets stay valid.
_PDF_DATE = re.compile(rb"D:\d{14}")
_FROZEN_PDF_DATE = b"D:20260101000000"


def _freeze_pdf_dates(payload: bytes) -> bytes:
    return _PDF_DATE.sub(_FROZEN_PDF_DATE, payload)


def render(spec: BolSpec, out_dir: Path | str) -> Path:
    """Render `spec` into `out_dir`; returns the written path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"bol_{spec.layout}{_EXTENSIONS[spec.mime_type]}"

    if spec.layout == "multipage":
        first, *rest = _render_multipage(spec)
        first.save(path, "PDF", save_all=True, append_images=rest, resolution=150.0)
        path.write_bytes(_freeze_pdf_dates(path.read_bytes()))
        return path

    img = _RENDERERS[spec.layout](spec)
    if spec.mime_type == "image/jpeg":
        img.save(path, "JPEG", quality=42)
    else:
        img.save(path, "PNG")
    return path


def render_all(out_dir: Path | str) -> dict[str, Path]:
    """Render every corpus document; returns {layout: path}."""
    return {spec.layout: render(spec, out_dir) for spec in CORPUS}


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Render the synthetic BOL corpus.")
    parser.add_argument("out_dir", nargs="?", default="validation-evidence/ocr-corpus")
    args = parser.parse_args()

    for layout, path in render_all(args.out_dir).items():
        print(f"{layout:20} {path}  ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
