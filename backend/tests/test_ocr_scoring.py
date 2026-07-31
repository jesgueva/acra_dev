"""ACR-36 / A8-4 — the corpus renderer and the field-level scorer.

Entirely offline: no network, no API keys, no database. These are the tests that make the accuracy
gate trustworthy, so several of them are written as *regressions against the old scorer* rather
than as fresh feature tests — see `test_dropped_row_does_not_shift_later_rows`, which is the defect
that made `scripts/validation/ocr_roundtrip.py`'s positional `got_items[gi]` comparison unusable.
"""

from __future__ import annotations

from datetime import date

import pytest

from scripts.ocr_bench import corpus, scoring
from scripts.ocr_bench.ground_truth import BY_LAYOUT, CORPUS, BolItem, BolSpec

# --------------------------------------------------------------------------------------
# Corpus
# --------------------------------------------------------------------------------------


def test_corpus_covers_the_six_planned_layouts():
    assert {spec.layout for spec in CORPUS} == {
        "gridded",
        "borderless_cramped",
        "rotated",
        "multipage",
        "spanish",
        "poor_scan",
    }


@pytest.mark.parametrize("spec", CORPUS, ids=lambda s: s.layout)
def test_every_spec_is_labelled(spec: BolSpec):
    assert spec.supplier and spec.carrier and spec.bol_reference
    assert isinstance(spec.delivery_date, date)
    assert spec.items, "a document with no line items cannot measure line-item accuracy"
    assert spec.probes, "each layout must state the failure mode it probes"


@pytest.mark.parametrize("spec", CORPUS, ids=lambda s: s.layout)
def test_pallets_times_units_equals_quantity(spec: BolSpec):
    """The triplet heuristic (extraction prompt rule 4) is only checkable if the math holds."""
    for item in spec.items:
        if item.units_per_pallet is not None:
            assert item.pallets * item.units_per_pallet == pytest.approx(item.quantity)


@pytest.mark.parametrize("spec", CORPUS, ids=lambda s: s.layout)
def test_render_is_deterministic(spec: BolSpec, tmp_path):
    """Same spec, same host, same bytes — otherwise a baseline means nothing."""
    first = corpus.render(spec, tmp_path / "a").read_bytes()
    second = corpus.render(spec, tmp_path / "b").read_bytes()
    assert first == second
    assert len(first) > 1000


def test_render_all_writes_every_document(tmp_path):
    written = corpus.render_all(tmp_path)
    assert set(written) == {spec.layout for spec in CORPUS}
    for path in written.values():
        assert path.exists() and path.stat().st_size > 0


def test_multipage_renders_a_two_page_pdf(tmp_path):
    path = corpus.render(BY_LAYOUT["multipage"], tmp_path)
    assert path.suffix == ".pdf"
    assert path.read_bytes().startswith(b"%PDF")


def test_spanish_layout_prints_european_thousands():
    """17122 must reach the page as '17.122' — that is the whole point of the layout."""
    assert corpus._thousands_dot(17122) == "17.122"
    assert corpus._thousands_dot(1223) == "1.223"
    assert corpus._thousands_dot(850) == "850"


def test_spanish_spec_expects_the_transfer_rule_not_the_printed_supplier():
    spec = BY_LAYOUT["spanish"]
    assert "TRANSFERENCIA" in spec.carrier
    assert spec.supplier == "Internal"
    assert spec.rendered_supplier == "Almacén Central Madrid"


# --------------------------------------------------------------------------------------
# Text / date normalization
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "left,right",
    [
        ("Fundición Ibérica S.L.", "FUNDICION IBERICA SL"),
        ("Acme Steel Supply Co.", "acme  steel   supply co"),
        ("Logística del Norte", "Logistica del Norte"),
    ],
)
def test_normalization_ignores_accents_case_and_punctuation(left, right):
    assert scoring.normalize_text(left) == scoring.normalize_text(right)


def test_similarity_of_empty_values_is_zero():
    """Two missing values are not a match — otherwise a model that returns nothing scores 1.0."""
    assert scoring.similarity(None, None) == 0.0
    assert scoring.similarity("", "Acme") == 0.0


@pytest.mark.parametrize(
    "text",
    ["2026-06-23", "23/06/2026", "23-06-2026", "23.06.2026", "23 June 2026", "2026/06/23"],
)
def test_dates_parse_from_any_reasonable_format(text):
    assert scoring.parse_date(text) == date(2026, 6, 23)


def test_unparseable_date_is_none_not_a_guess():
    assert scoring.parse_date("sometime next Tuesday") is None
    assert scoring.parse_date(None) is None


# --------------------------------------------------------------------------------------
# Header scoring — the D1 defect
# --------------------------------------------------------------------------------------


def _extraction(**overrides):
    """A dict-shaped extraction; the scorer accepts dicts and pydantic models alike."""
    base = {
        "supplier": "Acme Steel Supply Co.",
        "carrier": "Iberia Logistics S.L.",
        "bol_reference": "BOL-2026-0623",
        "delivery_date": "2026-06-23",
        "items": [],
    }
    base.update(overrides)
    return base


def test_header_all_correct():
    assert scoring.score_header(BY_LAYOUT["gridded"], _extraction()) == {
        "supplier": True,
        "carrier": True,
        "bol_reference": True,
        "delivery_date": True,
    }


def test_four_wrong_header_values_score_zero():
    """The defect this ticket exists for.

    `ocr_service._build_response` scores `filled / 4`, so this extraction — four values, all wrong —
    reports confidence 1.0. A real scorer must call it 0.0.
    """
    wrong = _extraction(
        supplier="Totally Different Corp",
        carrier="Some Other Freight",
        bol_reference="XX-0000-0000",
        delivery_date="1999-01-01",
    )
    header = scoring.score_header(BY_LAYOUT["gridded"], wrong)
    assert header == {
        "supplier": False,
        "carrier": False,
        "bol_reference": False,
        "delivery_date": False,
    }
    assert scoring.score_document(BY_LAYOUT["gridded"], wrong).header_accuracy == 0.0


def test_header_accepts_accent_and_punctuation_noise():
    spec = BY_LAYOUT["poor_scan"]
    header = scoring.score_header(
        spec,
        _extraction(
            supplier="FUNDICION IBERICA SL",
            carrier="Logistica del Norte",
            bol_reference="FI-2026-0733",
            delivery_date="03/07/2026",
        ),
    )
    assert all(header.values())


def test_bol_reference_demands_exactness():
    """A reference off by one character is a different document, not a near miss."""
    header = scoring.score_header(
        BY_LAYOUT["gridded"], _extraction(bol_reference="BOL-2026-0624")
    )
    assert header["bol_reference"] is False


def test_missing_header_fields_score_false():
    header = scoring.score_header(
        BY_LAYOUT["gridded"],
        _extraction(supplier=None, carrier=None, bol_reference=None, delivery_date=None),
    )
    assert not any(header.values())


# --------------------------------------------------------------------------------------
# Line-item alignment — the D3 defect
# --------------------------------------------------------------------------------------

_EXPECTED = (
    BolItem("Galvanized Steel Sheet", 1000.0, 5, 200),
    BolItem("Aluminum Coil 1050", 450.0, 3, 150),
    BolItem("Copper Wire Spool", 1000.0, 2, 500),
)


def _row(name, quantity, pallets, units_per_pallet):
    return {
        "item_name": name,
        "quantity": quantity,
        "pallets": pallets,
        "units_per_pallet": units_per_pallet,
    }


def test_all_rows_match_in_order():
    matches, missed, spurious = scoring.align_items(
        _EXPECTED,
        [
            _row("Galvanized Steel Sheet", 1000.0, 5, 200),
            _row("Aluminum Coil 1050", 450.0, 3, 150),
            _row("Copper Wire Spool", 1000.0, 2, 500),
        ],
    )
    assert len(matches) == 3
    assert not missed and not spurious
    assert all(m.numeric_correct == m.numeric_comparable for m in matches)


def test_reordered_rows_still_match():
    matches, missed, spurious = scoring.align_items(
        _EXPECTED,
        [
            _row("Copper Wire Spool", 1000.0, 2, 500),
            _row("Galvanized Steel Sheet", 1000.0, 5, 200),
            _row("Aluminum Coil 1050", 450.0, 3, 150),
        ],
    )
    assert len(matches) == 3
    assert not missed and not spurious
    assert all(m.numeric_correct == m.numeric_comparable for m in matches)


def test_dropped_row_does_not_shift_later_rows():
    """The regression that motivated the rewrite.

    The old scorer compared `got_items[gi]` positionally, so dropping row 2 made it compare row 3's
    extraction against row 2's ground truth and score *both* as wrong. Correct behaviour: one miss,
    and the surviving rows still match cleanly.
    """
    matches, missed, spurious = scoring.align_items(
        _EXPECTED,
        [
            _row("Galvanized Steel Sheet", 1000.0, 5, 200),
            _row("Copper Wire Spool", 1000.0, 2, 500),
        ],
    )
    assert len(matches) == 2
    assert [m.item_name for m in missed] == ["Aluminum Coil 1050"]
    assert not spurious
    assert all(m.numeric_correct == m.numeric_comparable for m in matches)


def test_spurious_row_costs_precision_not_recall():
    score = scoring.score_document(
        BY_LAYOUT["gridded"],
        _extraction(
            items=[
                _row("Galvanized Steel Sheet", 1000.0, 5, 200),
                _row("Aluminum Coil 1050", 450.0, 3, 150),
                _row("Copper Wire Spool", 1000.0, 2, 500),
                _row("Hallucinated Widget", 1.0, 1, 1),
            ]
        ),
    )
    assert score.recall == 1.0
    assert score.precision == 0.75
    assert len(score.spurious) == 1


def test_each_extracted_row_is_consumed_once():
    """One extracted row must not satisfy two expected rows."""
    matches, missed, _ = scoring.align_items(
        (BolItem("Copper Wire Spool", 1000.0, 2, 500), BolItem("Copper Wire Spool", 500.0, 1, 500)),
        [_row("Copper Wire Spool", 1000.0, 2, 500)],
    )
    assert len(matches) == 1
    assert len(missed) == 1


def test_near_miss_name_above_threshold_matches():
    matches, _, _ = scoring.align_items(
        (BolItem("Galvanized Steel Sheet", 1000.0, 5, 200),),
        [_row("Galvanised Steel Sheet", 1000.0, 5, 200)],
    )
    assert len(matches) == 1
    assert matches[0].name_similarity >= scoring.ITEM_MATCH_THRESHOLD


def test_unrelated_name_below_threshold_does_not_match():
    matches, missed, spurious = scoring.align_items(
        (BolItem("Galvanized Steel Sheet", 1000.0, 5, 200),),
        [_row("Rubber Duck Assortment", 1000.0, 5, 200)],
    )
    assert not matches
    assert len(missed) == 1 and len(spurious) == 1


def test_empty_extraction_misses_everything():
    score = scoring.score_document(BY_LAYOUT["gridded"], _extraction(items=[]))
    assert score.recall == 0.0
    assert score.f1 == 0.0
    assert len(score.missed) == 3


# --------------------------------------------------------------------------------------
# Numeric comparison
# --------------------------------------------------------------------------------------


def test_quantity_within_tolerance_passes():
    matches, _, _ = scoring.align_items(
        (BolItem("Copper Wire Spool", 1000.0, 2, 500),),
        [_row("Copper Wire Spool", 1000.005, 2, 500)],
    )
    assert matches[0].numeric["quantity"] == (True, True)


def test_quantity_outside_tolerance_fails():
    matches, _, _ = scoring.align_items(
        (BolItem("Copper Wire Spool", 1000.0, 2, 500),),
        [_row("Copper Wire Spool", 1000.5, 2, 500)],
    )
    assert matches[0].numeric["quantity"] == (False, True)


def test_pallets_off_by_one_fails():
    """Counts are exact — there is no such thing as approximately three pallets."""
    matches, _, _ = scoring.align_items(
        (BolItem("Copper Wire Spool", 1000.0, 2, 500),),
        [_row("Copper Wire Spool", 1000.0, 3, 500)],
    )
    assert matches[0].numeric["pallets"] == (False, True)


def test_european_thousands_misread_as_decimal_is_caught():
    """The failure the Spanish layout exists to detect: 17.122 read as 17.122, not 17122."""
    matches, _, _ = scoring.align_items(
        (BolItem("Chapa Galvanizada 2mm", 17122.0, 14, 1223),),
        [_row("Chapa Galvanizada 2mm", 17.122, 14, 1.223)],
    )
    assert matches[0].numeric["quantity"] == (False, True)
    assert matches[0].numeric["units_per_pallet"] == (False, True)


def test_absent_ground_truth_value_is_not_graded():
    """`units_per_pallet` is legitimately absent on some rows; grading it would punish a right answer."""
    matches, _, _ = scoring.align_items(
        (BolItem("Loose Cargo", 12.0, 1, None),),
        [_row("Loose Cargo", 12.0, 1, None)],
    )
    assert matches[0].numeric["units_per_pallet"] == (False, False)
    assert matches[0].numeric_comparable == 2
    assert matches[0].numeric_correct == 2


def test_missing_numeric_value_counts_against_the_model():
    matches, _, _ = scoring.align_items(
        (BolItem("Copper Wire Spool", 1000.0, 2, 500),),
        [_row("Copper Wire Spool", None, 2, 500)],
    )
    assert matches[0].numeric["quantity"] == (False, True)


def test_non_numeric_value_counts_against_the_model():
    matches, _, _ = scoring.align_items(
        (BolItem("Copper Wire Spool", 1000.0, 2, 500),),
        [_row("Copper Wire Spool", "about a thousand", 2, 500)],
    )
    assert matches[0].numeric["quantity"] == (False, True)


# --------------------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------------------


def _perfect(spec: BolSpec, latency_ms: float | None = None) -> scoring.BolScore:
    return scoring.score_document(
        spec,
        {
            "supplier": spec.supplier,
            "carrier": spec.carrier,
            "bol_reference": spec.bol_reference,
            "delivery_date": spec.delivery_date.isoformat(),
            "items": [
                _row(i.item_name, i.quantity, i.pallets, i.units_per_pallet) for i in spec.items
            ],
        },
        provider="gemini",
        latency_ms=latency_ms,
    )


def test_perfect_run_scores_one():
    result = scoring.score_corpus(_perfect(spec) for spec in CORPUS)
    assert result.header_accuracy == 1.0
    assert result.item_f1 == 1.0
    assert result.numeric_accuracy == 1.0


def test_corpus_score_is_micro_averaged():
    """A six-item document must carry more weight than a two-item one."""
    good = _perfect(BY_LAYOUT["multipage"])  # 6 items
    bad = scoring.score_document(BY_LAYOUT["rotated"], _extraction(items=[]))  # 2 items missed
    result = scoring.score_corpus([good, bad])
    assert result.recall == round(6 / 8, 4)


def test_errored_document_scores_zero_and_keeps_the_reason():
    score = scoring.score_document(
        BY_LAYOUT["gridded"], None, provider="claude", error="both providers failed"
    )
    assert score.header_accuracy == 0.0
    assert score.recall == 0.0
    assert score.error == "both providers failed"
    assert score.to_dict()["error"] == "both providers failed"


def test_latency_percentiles():
    scores = [_perfect(BY_LAYOUT["gridded"], latency_ms=ms) for ms in (100, 200, 300, 400)]
    result = scoring.score_corpus(scores)
    assert result.latency_percentile(50) == 200.0
    assert result.latency_percentile(100) == 400.0


def test_latency_percentiles_are_none_when_nothing_was_timed():
    result = scoring.score_corpus([_perfect(BY_LAYOUT["gridded"])])
    assert result.latency_percentile(95) is None
    assert result.to_dict()["latency_ms"]["p95"] is None


def test_to_dict_is_json_serializable():
    import json

    payload = scoring.score_corpus([_perfect(spec) for spec in CORPUS]).to_dict()
    assert json.loads(json.dumps(payload))["item_f1"] == 1.0


def test_format_document_report_names_misses_and_spurious_rows():
    score = scoring.score_document(
        BY_LAYOUT["gridded"],
        _extraction(
            items=[
                _row("Galvanized Steel Sheet", 1000.0, 5, 200),
                _row("Hallucinated Widget", 1.0, 1, 1),
            ]
        ),
    )
    report = scoring.format_document_report(score)
    assert "MISSED" in report and "SPURIOUS" in report
    assert "Aluminum Coil 1050" in report
