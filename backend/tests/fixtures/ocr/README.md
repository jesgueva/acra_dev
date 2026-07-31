# OCR fixtures (ACR-36 / A8-4)

## `baseline.json`

The recorded accuracy baseline the no-regression gate compares against
(`tests/integration/test_ocr_accuracy.py`). It carries the run metadata that produced it — git SHA,
host, model IDs, corpus shape, scorer thresholds — because a number without provenance cannot be
defended.

Re-record it after any deliberate change to the extraction prompt, the corpus, the scorer, or the
model IDs:

```bash
cd backend
set -a && source .env && set +a
python -m scripts.ocr_bench.run_bench --provider both --repeat 3 --delay 13 --out /tmp/ocr-bench
```

Then copy the `header_accuracy`, `item_f1` and `numeric_accuracy` figures for each provider into
`baseline.json`, along with the new `run` block. **Re-record deliberately, never to make a red gate
go green** — a gate that gets rewritten whenever it fires measures nothing.

`--delay 13` matters: Gemini's free tier allows only five requests per minute. Without
pacing, most calls come back HTTP 429 and the run measures quota rather than extraction quality.

## `sample_bol_gridded.png`

One rendered document from the corpus, committed so the receiving flow and A10-2's offline OCR mode
have something to upload without running the generator.

The rest of the corpus is **not** committed. It ships as a deterministic generator plus labels
(`backend/scripts/ocr_bench/`), which keeps datasets out of the repo per `CONTRIBUTING.md` and makes
the method — not a blob — the artifact. Regenerate all seven documents with:

```bash
cd backend && python -m scripts.ocr_bench.corpus /tmp/corpus
```
