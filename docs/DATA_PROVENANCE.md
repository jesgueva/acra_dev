# Data provenance

What data ships in this repository, where it comes from, how to regenerate it, and — the one
thing that actually needs stating explicitly — what is **not** covered by [`LICENSE`](../LICENSE)
and must not be redistributed.

## Synthetic / redistributable

Everything the app runs on locally is generated, not real:

- **Seed data** — `backend/scripts/seed_fake_data.py`. Deterministic: every value is arithmetic on
  a row index, no RNG, no `--seed` flag needed, so two runs with the same arguments produce the
  same database. `--scale N` controls volume; `--scale 1` (no arguments) is the fixture the 83
  Playwright specs assert against and must stay bit-identical. Fully redistributable — regenerate
  it with `python scripts/seed_fake_data.py`.
- **OCR bench corpus** — `backend/scripts/ocr_bench/`. Deterministic Pillow-rendered synthetic
  bills of lading (7 layouts: gridded, borderless/cramped, rotated, multi-page, Spanish-language,
  poor scan, degraded fax), chosen synthetic-only specifically so it ships in-repo with no
  licensing caveat (`plans/plan_a8_a10_readiness.md` §6 #2). The corpus itself is **not**
  committed — it's a deterministic generator plus ground-truth labels, regenerated with
  `python -m scripts.ocr_bench.corpus /tmp/corpus`. One rendered sample,
  `backend/tests/fixtures/ocr/sample_bol_gridded.png`, is committed for the receiving flow and
  offline OCR mode to have something to upload without running the generator — see
  `backend/tests/fixtures/ocr/README.md` for the full detail on that fixture set.
- **Demo credentials** — the accounts listed in `README.md`'s Quickstart are synthetic and exist
  for local development only; that warning already lives there and isn't duplicated here.

## Client-owned / not redistributable

- **`frontend/acra_logo.png`** — the client's brand mark, committed for local UI development so
  the running prototype reflects the client's actual branding. It is **excluded from
  [`LICENSE`](../LICENSE)**: the MIT grant in this repository covers the source code only. This
  image may not be reused, redistributed, or repurposed outside this engagement.

No other client-derived asset is committed to `acra_dev`. The real production-flow vocabulary
walked through with the client (`client_domain_model.md`) lives in the separate `acra_docs`
documentation repository, not in this one, and is out of scope for this file.

## Third-party dependencies

Dependency licenses are governed by the packages themselves (`backend/requirements.lock`,
`frontend/package-lock.json`) and are not individually audited here — that's a different, unscoped
exercise from naming what this project's *own* data is and isn't safe to redistribute.
