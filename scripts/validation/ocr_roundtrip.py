"""ACRA MES — real OCR round-trip.

Generates a synthetic Bill of Lading image (known ground truth), uploads it to the
live POST /api/v1/deliveries/ocr endpoint, and reports the structured extraction the
vision-LLM pipeline (Gemini 2.5 Flash primary -> Claude Sonnet 4.6 fallback) returned.
This exercises the REAL external integration end to end — not a mock.
"""
import io
import json
import sys
import httpx
from PIL import Image, ImageDraw, ImageFont

BASE = "http://localhost:8000"
OUT_IMG = sys.argv[1] if len(sys.argv) > 1 else "/tmp/sample_bol.png"

# --- ground truth encoded into the synthetic document ------------------------
GROUND_TRUTH = {
    "supplier": "Acme Steel Supply Co.",
    "carrier": "Iberia Logistics S.L.",
    "bol_reference": "BOL-2026-0623",
    "delivery_date": "2026-06-23",
    "items": [
        # (material, pallets, units_per_pallet, quantity)
        ("Galvanized Steel Sheet", 5, 200, 1000),
        ("Aluminum Coil 1050", 3, 150, 450),
        ("Copper Wire Spool", 2, 500, 1000),
    ],
}


def _font(size, bold=False):
    path = "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf"
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def build_bol(path):
    W, H = 1000, 1180
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, W - 20, H - 20], outline="black", width=2)
    d.text((40, 40), "BILL OF LADING", font=_font(40, bold=True), fill="black")
    d.line([40, 95, W - 40, 95], fill="black", width=2)

    y = 120
    rows = [
        ("Supplier:", GROUND_TRUTH["supplier"]),
        ("Carrier:", GROUND_TRUTH["carrier"]),
        ("BOL Reference:", GROUND_TRUTH["bol_reference"]),
        ("Delivery Date:", GROUND_TRUTH["delivery_date"]),
    ]
    for label, val in rows:
        d.text((40, y), label, font=_font(24, bold=True), fill="black")
        d.text((320, y), val, font=_font(24), fill="black")
        y += 48

    y += 30
    # gridded line-items table — clear columns + row separators
    colx = [40, 470, 620, 790, 950]          # left edges + right border
    headers = ["Material", "Pallets", "Units/Pallet", "Quantity"]
    row_h = 56
    n = len(GROUND_TRUTH["items"])
    top = y
    bottom = y + row_h * (n + 1)
    # header row
    for i, label in enumerate(headers):
        d.text((colx[i] + 12, y + 16), label, font=_font(22, bold=True), fill="black")
    y += row_h
    for (name, pal, upp, qty) in GROUND_TRUTH["items"]:
        d.text((colx[0] + 12, y + 14), name, font=_font(22), fill="black")
        d.text((colx[1] + 12, y + 14), str(pal), font=_font(22), fill="black")
        d.text((colx[2] + 12, y + 14), str(upp), font=_font(22), fill="black")
        d.text((colx[3] + 12, y + 14), str(qty), font=_font(22), fill="black")
        y += row_h
    # grid lines
    for gx in colx:
        d.line([gx, top, gx, bottom], fill="black", width=1)
    for r in range(n + 2):
        gy = top + r * row_h
        d.line([colx[0], gy, colx[-1], gy], fill="black", width=1)
    img.save(path)
    return path


def main():
    build_bol(OUT_IMG)
    with open(OUT_IMG, "rb") as f:
        img_bytes = f.read()

    client = httpx.Client(base_url=BASE, timeout=90.0)
    tok = client.post("/api/v1/auth/login",
                      json={"username": "admin", "password": "admin123"}).json()["access_token"]

    print("REQUEST")
    print(f"  POST {BASE}/api/v1/deliveries/ocr")
    print(f"  multipart file: sample_bol.png  ({len(img_bytes):,} bytes, image/png)")
    print(f"  auth: Bearer <admin JWT, redacted>")

    r = client.post("/api/v1/deliveries/ocr",
                    headers={"Authorization": f"Bearer {tok}"},
                    files={"file": ("sample_bol.png", img_bytes, "image/png")})
    print(f"\nRESPONSE  (HTTP {r.status_code})")
    resp = r.json()
    print(json.dumps(resp, indent=2, ensure_ascii=False))

    # --- field-level accuracy vs ground truth -------------------------------
    print("\nFIELD-LEVEL ACCURACY (extracted vs. ground truth)")

    def norm(s):
        return (s or "").strip().lower().replace(".", "").replace(",", "")

    header_fields = ["supplier", "carrier", "bol_reference", "delivery_date"]
    correct = 0
    for fld in header_fields:
        exp, got = GROUND_TRUTH[fld], resp.get(fld)
        ok = norm(got) == norm(exp) or (norm(exp) in norm(got)) or (norm(got) in norm(exp) and got)
        correct += bool(ok)
        print(f"  [{'OK ' if ok else 'DIFF'}] {fld:14} expected={exp!r}  got={got!r}")

    got_items = resp.get("items", [])
    print(f"\n  line items: expected {len(GROUND_TRUTH['items'])}, extracted {len(got_items)}")
    for gi, (name, pal, upp, qty) in enumerate(GROUND_TRUTH["items"]):
        match = got_items[gi] if gi < len(got_items) else {}
        print(f"    - expected: {name!r:30} pallets={pal} u/p={upp} qty={qty}")
        print(f"      got     : name={match.get('item_name')!r} pallets={match.get('pallets')} "
              f"u/p={match.get('units_per_pallet')} qty={match.get('quantity')}")

    print(f"\nSUMMARY: confidence={resp.get('confidence')}  | "
          f"header fields matched {correct}/{len(header_fields)}  | "
          f"items {len(got_items)}/{len(GROUND_TRUTH['items'])}")


if __name__ == "__main__":
    main()
