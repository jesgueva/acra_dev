"""ACR-36 / A8-4 — OCR accuracy + provider comparison bench.

Evaluation tooling for the vision-LLM BOL extractor. Deliberately **not** under `app/`: none of
this ships in the request path, and the application must never import it.

Modules
-------
`ground_truth`  the labelled dataset — six `BolSpec` records, one per layout
`corpus`        deterministic Pillow renderer turning a `BolSpec` into a PNG/PDF
`scoring`       field-level scorer with fuzzy line-item alignment
`run_bench`     opt-in CLI driving the real providers and writing machine-readable evidence

Why a generator instead of committed images: `CONTRIBUTING.md` keeps datasets and large binaries
out of the repo, and a seeded renderer is a stronger reproducibility claim than a checked-in blob —
the *method* is the artifact. One rendered sample is committed under `tests/fixtures/ocr/` so the
receiving flow stays runnable offline.
"""
