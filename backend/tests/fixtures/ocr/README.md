# OCR fixtures (ACR-36 / A8-4)

## `baseline.json`

The recorded accuracy floor the no-regression gate compares against
(`tests/integration/test_ocr_accuracy.py`, and `scripts/validation/ocr_roundtrip.py` for the live
endpoint). It carries the run metadata that produced it — git SHA, host, model IDs, corpus shape,
scorer thresholds — because a number without provenance cannot be defended.

The floor is **model-agnostic**: every configured model (`ANTHROPIC_MODEL` and
`ANTHROPIC_FALLBACK_MODEL`) must stay within tolerance of it, so swapping a model is gated by the
same bar as the model it replaces. It is currently the `claude-sonnet-4-6` arm of the 2026-07-31
run — the Claude model in use before OCR went Claude-only.

To check the configured models against it (this is how to answer "is Haiku good enough?"):

```bash
cd backend
set -a && source .env && set +a
python -m scripts.ocr_bench.run_bench --repeat 3 --out /tmp/ocr-bench   # primary + fallback
OCR_BENCH_LIVE=1 pytest tests/integration/test_ocr_accuracy.py -v      # gate each against the floor
```

`--model` picks other arms (repeat it for a head-to-head), and `ANTHROPIC_EFFORT=low` (or `high`)
sweeps effort, which the report records.

Re-record the floor only after a deliberate change to the extraction prompt, the corpus, or the
scorer, or to raise the bar: copy one arm's `header_accuracy`, `item_f1` and `numeric_accuracy`
into `floor` (with its `model`), along with the new `run` block. **Re-record deliberately, never to
make a red gate go green** — a gate that gets rewritten whenever it fires measures nothing.

## `sample_bol_gridded.png`

One rendered document from the corpus, committed so the receiving flow and A10-2's offline OCR mode
have something to upload without running the generator.

The rest of the corpus is **not** committed. It ships as a deterministic generator plus labels
(`backend/scripts/ocr_bench/`), which keeps datasets out of the repo per `CONTRIBUTING.md` and makes
the method — not a blob — the artifact. Regenerate all seven documents with:

```bash
cd backend && python -m scripts.ocr_bench.corpus /tmp/corpus
```
