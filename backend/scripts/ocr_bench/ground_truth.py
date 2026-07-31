"""The labelled corpus — ground truth for every synthetic BOL.

This module is the dataset. `corpus.py` renders these records into documents; `scoring.py` grades
extractions against them. Editing a value here changes what "correct" means, so any change must be
paired with a re-measured baseline (`tests/fixtures/ocr/baseline.json`).

Each layout probes a documented failure mode rather than adding volume for its own sake — ISS-05
and KI-09 both say line-item extraction is *layout*-sensitive while header fields are robust, and
this corpus is built to show that separation rather than assume it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class BolItem:
    """One line item, as it should be extracted.

    `pallets * units_per_pallet == quantity` holds for every row in this corpus, which is what makes
    the extractor's "triplet heuristic" (rule 4 of the extraction prompt) checkable.
    """

    item_name: str
    quantity: float
    pallets: int
    units_per_pallet: int | None = None
    description: str | None = None


@dataclass(frozen=True)
class BolSpec:
    """One document: what gets rendered, and what a correct extraction returns.

    `supplier` is the *expected extraction*, which is not always the text printed on the page —
    see `printed_supplier`.
    """

    layout: str
    supplier: str
    carrier: str
    bol_reference: str
    delivery_date: date
    items: tuple[BolItem, ...]
    probes: str
    mime_type: str = "image/png"
    #: Set only when the expected `supplier` differs from what is printed on the document, i.e. when
    #: an extraction *rule* rather than plain reading determines the answer.
    printed_supplier: str | None = None

    @property
    def rendered_supplier(self) -> str:
        """The string the renderer should actually draw on the page."""
        return self.printed_supplier if self.printed_supplier is not None else self.supplier


GRIDDED = BolSpec(
    layout="gridded",
    supplier="Acme Steel Supply Co.",
    carrier="Iberia Logistics S.L.",
    bol_reference="BOL-2026-0623",
    delivery_date=date(2026, 6, 23),
    items=(
        BolItem("Galvanized Steel Sheet", 1000.0, 5, 200),
        BolItem("Aluminum Coil 1050", 450.0, 3, 150),
        BolItem("Copper Wire Spool", 1000.0, 2, 500),
    ),
    probes="Baseline. Ruled table, unambiguous columns — the shape the extractor handles best.",
)

BORDERLESS_CRAMPED = BolSpec(
    layout="borderless_cramped",
    supplier="Nordwerk Metallhandel GmbH",
    carrier="TransEuropa Cargo",
    bol_reference="NW-88213",
    delivery_date=date(2026, 5, 14),
    items=(
        BolItem("Stainless Sheet 304", 480.0, 4, 120),
        BolItem("Brass Rod 12mm", 540.0, 6, 90),
        BolItem("Zinc Ingot 25kg", 320.0, 8, 40),
        BolItem("Nickel Strip", 150.0, 2, 75),
    ),
    probes="ISS-05 / KI-09 directly: no rule lines, tight leading, columns nearly touching.",
)

ROTATED = BolSpec(
    layout="rotated",
    supplier="Talleres Vega S.A.",
    carrier="Rapid Freight",
    bol_reference="TV-2026-0117",
    delivery_date=date(2026, 1, 17),
    items=(
        BolItem("Steel Beam IPN-200", 75.0, 3, 25),
        BolItem("Rebar Bundle 16mm", 350.0, 7, 50),
    ),
    probes="Skew from a phone photo of a paper BOL — the realistic capture path on a plant floor.",
)

MULTIPAGE = BolSpec(
    layout="multipage",
    supplier="Continental Alloys Ltd.",
    carrier="Maersk Overland",
    bol_reference="CA-99401",
    delivery_date=date(2026, 3, 8),
    items=(
        BolItem("Titanium Sheet Gr2", 120.0, 2, 60),
        BolItem("Inconel Tube 625", 40.0, 1, 40),
        BolItem("Monel Plate 400", 90.0, 3, 30),
        BolItem("Hastelloy Bar C276", 40.0, 2, 20),
        BolItem("Duplex Sheet 2205", 180.0, 4, 45),
        BolItem("Copper Busbar", 400.0, 5, 80),
    ),
    probes="Line items split across a page break — tests whether page 2 is read at all.",
    mime_type="application/pdf",
)

SPANISH = BolSpec(
    layout="spanish",
    # Rule 1 of the extraction prompt: a carrier containing TRANSFERENCIA means an internal move,
    # so the correct supplier is the literal "Internal" — not the warehouse printed on the page.
    supplier="Internal",
    printed_supplier="Almacén Central Madrid",
    carrier="TRANSFERENCIA INTERNA S.L.",
    bol_reference="ALB-2026-0442",
    delivery_date=date(2026, 4, 22),
    items=(
        BolItem("Chapa Galvanizada 2mm", 17122.0, 14, 1223),
        BolItem("Perfil Aluminio 40x40", 12000.0, 8, 1500),
        BolItem("Tubo Cobre 15mm", 2550.0, 3, 850),
    ),
    probes=(
        "Spanish headings, European thousands separators (17.122 -> 17122), and the "
        "TRANSFERENCIA -> supplier='Internal' rule. Exercises prompt rules 1, 3 and 4 at once."
    ),
)

POOR_SCAN = BolSpec(
    layout="poor_scan",
    supplier="Fundición Ibérica S.L.",
    carrier="Logística del Norte",
    bol_reference="FI-2026-0733",
    delivery_date=date(2026, 7, 3),
    items=(
        BolItem("Lingote Aluminio", 660.0, 6, 110),
        BolItem("Chatarra Ferrosa", 950.0, 10, 95),
    ),
    probes="Scan grain, low contrast and JPEG artifacts — the degraded-input floor.",
    mime_type="image/jpeg",
)

DEGRADED_FAX = BolSpec(
    layout="degraded_fax",
    supplier="Metalúrgica del Sur S.A.",
    carrier="Transportes Álvarez",
    bol_reference="MS-2026-0891",
    delivery_date=date(2026, 2, 11),
    items=(
        BolItem("Bobina Acero Laminado", 1170.0, 9, 130),
        BolItem("Varilla Roscada M10", 1040.0, 4, 260),
        BolItem("Placa Antideslizante", 96.0, 2, 48),
    ),
    probes=(
        "The hard end of the corpus: downscaled, heavy grain, crushed contrast, blur, skew and "
        "aggressive JPEG. A faxed BOL photographed off a desk. Exists so the corpus has a "
        "difficulty gradient — a bench every layout aces cannot detect a regression."
    ),
    mime_type="image/jpeg",
)

CORPUS: tuple[BolSpec, ...] = (
    GRIDDED,
    BORDERLESS_CRAMPED,
    ROTATED,
    MULTIPAGE,
    SPANISH,
    POOR_SCAN,
    DEGRADED_FAX,
)

BY_LAYOUT: dict[str, BolSpec] = {spec.layout: spec for spec in CORPUS}
