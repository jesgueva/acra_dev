"""OCR Service — Vision LLM-based BOL field extraction, Claude only.

Two-tier model chain on one provider:
  1. `settings.anthropic_model`          — primary  (Claude Haiku 5.5 by default)
  2. `settings.anthropic_fallback_model` — fallback (Claude Sonnet 5.5 by default), used when the
     primary raises, refuses, or returns no header fields at all. Empty disables the fallback.

Both model IDs are configuration, not constants, so a swap does not require a code change and the
A8-4 comparison bench can report the model that actually ran.

The raw file bytes (JPEG, PNG, or PDF) go to Claude base64-encoded, and the reply is constrained to
`_BOL_SCHEMA` with structured outputs, so it always parses.

`settings.ocr_mock_mode` (ACR-50) short-circuits the models with a canned response — see
`_mock_response()` — so the receiving flow is runnable without an API key.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

import anthropic

from app.core.config import settings
from app.schemas.delivery import OCRItemResult, OCRResponse

logger = logging.getLogger("acra.ocr")

# ---------------------------------------------------------------------------
# Lazy singleton — initialized on first use, reused across requests
# ---------------------------------------------------------------------------

_anthropic_client: anthropic.Anthropic | None = None


def _get_anthropic_client() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _anthropic_client


_OCR_EXTRACTION_INSTRUCTIONS = (
    "Extract all Bill of Lading fields from this document.\n\n"
    "Return a JSON object with exactly these keys: "
    "supplier (string or null), "
    "carrier (string or null), "
    "bol_reference (string or null), "
    "delivery_date (string or null, any format you find), "
    "items (array — each element has: item_name, description, quantity as number, "
    "pallets as integer, units_per_pallet as integer or null).\n\n"
    "Rules:\n"
    "1) Supplier: If the carrier value contains 'TRANSFER' or 'TRANSFERENCIA' "
    "(case-insensitive), set supplier to the string 'Internal'.\n"
    "2) units_per_pallet: For each line item, if the table has a third numeric column "
    "(units per pallet, Ud/Pallet, U/C, bultos/pallet, or similar), fill units_per_pallet. "
    "Use null only when that value is truly absent or illegible.\n"
    "3) European thousands: When a number uses a dot as a thousands separator "
    "(e.g. 17.122 or 1.234.567 — typically groups of three digits after dots), "
    "do not treat the dot as a decimal point; normalize to the correct integer or count. "
    "When only one or two digits follow the dot (e.g. 5.44), treat as a decimal "
    "unless the triplet rule below clearly indicates otherwise.\n"
    "4) Triplet heuristic: If exactly three distinct numeric values appear on one item row "
    "(same logical line), sort them ascending: smallest → pallets, middle → units_per_pallet, "
    "largest → quantity (total units or weight for that row, per the document). "
    "pallets × units_per_pallet should be approximately equal to quantity (allow small OCR rounding); "
    "if column order is ambiguous, prefer this math over strict left-to-right order.\n"
    "5) If a field is not present, use null."
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_items(raw: list[dict[str, Any]]) -> list[OCRItemResult]:
    items = []
    for entry in raw or []:
        try:
            items.append(
                OCRItemResult(
                    item_name=entry.get("item_name"),
                    description=entry.get("description"),
                    quantity=float(entry["quantity"]) if entry.get("quantity") is not None else None,
                    pallets=int(entry["pallets"]) if entry.get("pallets") is not None else None,
                    units_per_pallet=int(entry["units_per_pallet"]) if entry.get("units_per_pallet") is not None else None,
                )
            )
        except (TypeError, ValueError):
            pass
    return items


def _build_response(data: dict[str, Any], provider: str) -> OCRResponse:
    """Shape a model's raw JSON into the wire response.

    `confidence` is a **header fill rate**, not an accuracy: it counts how many of the four header
    fields came back non-empty, so four wrong values still score 1.0. It keeps its meaning because
    the 422 gate and the primary→fallback model chain both key off `> 0.0`; `header_fill_rate`
    carries the same number under an honest name. Measured accuracy comes from the A8-4 bench
    (`backend/scripts/ocr_bench/`), which scores against a labelled corpus.
    """
    supplier = data.get("supplier")
    carrier = data.get("carrier")
    bol_reference = data.get("bol_reference")
    delivery_date = data.get("delivery_date")
    filled = sum(1 for v in [supplier, carrier, bol_reference, delivery_date] if v)
    fill_rate = round(filled / 4.0, 2)
    raw_items = data.get("items") or []
    return OCRResponse(
        supplier=supplier,
        carrier=carrier,
        bol_reference=bol_reference,
        delivery_date=delivery_date,
        items=_parse_items(raw_items),
        confidence=fill_rate,
        header_fill_rate=fill_rate,
        provider=provider,
    )


# ---------------------------------------------------------------------------
# Claude extraction
# ---------------------------------------------------------------------------


def _nullable(json_type: str) -> dict[str, Any]:
    return {"anyOf": [{"type": json_type}, {"type": "null"}]}


#: Structured-output schema. Every key is required and nullable rather than optional, so a field
#: that is absent from the document comes back as an explicit null instead of a missing key.
_BOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "supplier": _nullable("string"),
        "carrier": _nullable("string"),
        "bol_reference": _nullable("string"),
        "delivery_date": _nullable("string"),
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_name": _nullable("string"),
                    "description": _nullable("string"),
                    "quantity": _nullable("number"),
                    "pallets": _nullable("integer"),
                    "units_per_pallet": _nullable("integer"),
                },
                "required": ["item_name", "description", "quantity", "pallets", "units_per_pallet"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["supplier", "carrier", "bol_reference", "delivery_date", "items"],
    "additionalProperties": False,
}

#: Room for adaptive thinking as well as the JSON — thinking counts toward `max_tokens`, and a cap
#: sized for the answer alone can be spent before any text is written.
_MAX_TOKENS = 16000


class ExtractionError(RuntimeError):
    """Claude answered, but not with a usable extraction (refusal or truncated output)."""


def _extract_with_claude(
    file_bytes: bytes, content_type: str, model: str | None = None
) -> OCRResponse:
    """One extraction on one model — `settings.anthropic_model` unless `model` names another.

    `provider` on the result is the model ID, so a caller can tell the primary from the fallback.
    """
    model = model or settings.anthropic_model
    b64 = base64.b64encode(file_bytes).decode()
    file_block: dict[str, Any]
    if content_type == "application/pdf":
        file_block = {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
        }
    else:
        file_block = {
            "type": "image",
            "source": {"type": "base64", "media_type": content_type, "data": b64},
        }

    response = _get_anthropic_client().messages.create(
        model=model,
        max_tokens=_MAX_TOKENS,
        output_config={
            "effort": settings.anthropic_effort,
            "format": {"type": "json_schema", "schema": _BOL_SCHEMA},
        },
        messages=[
            {
                "role": "user",
                "content": [
                    file_block,
                    {"type": "text", "text": _OCR_EXTRACTION_INSTRUCTIONS},
                ],
            }
        ],
    )
    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        raise ExtractionError(f"{model} declined the request (category: {category})")
    if response.stop_reason == "max_tokens":
        raise ExtractionError(f"{model} hit max_tokens={_MAX_TOKENS} before finishing the JSON")
    # Adaptive thinking means the reply can open with `thinking` blocks, so find the text by type.
    text = next((block.text for block in response.content if block.type == "text"), None)
    if text is None:
        raise ExtractionError(
            f"{model} returned no text block (stop_reason: {response.stop_reason})"
        )
    return _build_response(json.loads(text), model)


# ---------------------------------------------------------------------------
# Offline/mock mode (ACR-50 / A10-2)
# ---------------------------------------------------------------------------

def _mock_response() -> OCRResponse:
    """A canned extraction, used when `settings.ocr_mock_mode` is on.

    Field values mirror the `GRIDDED` layout in `backend/scripts/ocr_bench/ground_truth.py`
    (duplicated here, not imported — `ocr_bench/__init__.py` states the app must never import that
    package, since none of it is meant to ship in the request path). The one committed fixture,
    `backend/tests/fixtures/ocr/sample_bol_gridded.png`, is the matching image to upload against it.
    Content is ignored entirely in mock mode; every upload gets this same response.
    """
    return OCRResponse(
        supplier="Acme Steel Supply Co.",
        carrier="Iberia Logistics S.L.",
        bol_reference="BOL-2026-0623",
        delivery_date="2026-06-23",
        items=[
            OCRItemResult(item_name="Galvanized Steel Sheet", description=None, quantity=1000.0, pallets=5, units_per_pallet=200),
            OCRItemResult(item_name="Aluminum Coil 1050", description=None, quantity=450.0, pallets=3, units_per_pallet=150),
            OCRItemResult(item_name="Copper Wire Spool", description=None, quantity=1000.0, pallets=2, units_per_pallet=500),
        ],
        confidence=1.0,
        header_fill_rate=1.0,
        provider="mock",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def process_image_bytes(file_bytes: bytes, content_type: str) -> OCRResponse:
    if settings.ocr_mock_mode:
        return _mock_response()

    models = [settings.anthropic_model]
    fallback = settings.anthropic_fallback_model
    if fallback and fallback != settings.anthropic_model:
        models.append(fallback)

    for model in models:
        try:
            result = _extract_with_claude(file_bytes, content_type, model)
        except anthropic.APIStatusError as exc:
            logger.warning("[%s] API error %s: %s", model, exc.status_code, exc.message)
        except anthropic.APIConnectionError as exc:
            logger.warning("[%s] connection error: %s", model, exc)
        except ExtractionError as exc:
            logger.warning("[%s] %s", model, exc)
        except Exception:
            logger.warning("[%s] unexpected error", model, exc_info=True)
        else:
            if result.confidence > 0.0:
                return result
            logger.warning("[%s] no header fields extracted", model)

    logger.error("OCR failed on every configured model: %s", ", ".join(models))
    return OCRResponse(confidence=0.0)
