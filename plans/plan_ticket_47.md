# Plan — ACR-47 · A10-6 LICENSE + data-provenance doc

**Status:** draft for review
**Written against:** `origin/master` @ `8b84f9a` (`ticket-36: A8-4 — OCR accuracy gate & provider comparison bench (#ACR-36) (#40)`)
**Date:** 2026-07-31
**Branch:** `ticket-47/license-data-provenance`
**Ticket:** [ACR-47](https://linear.app/chronos-laboral/issue/ACR-47/a10-6-license-data-provenance-doc) · plan item A10-6 of `plans/plan_a8_a10_readiness.md` §3.1

Docs-only. No backend, frontend, model, migration, or RBAC changes.

---

## 1. Current state

### 1.1 No license exists, and the repo is public

- `find . -iname "LICENSE*"` at repo root returns nothing (only vendored `.venv/`/`node_modules`
  package licenses, which are irrelevant).
- `frontend/package.json` carries `"private": true` (blocks accidental npm publish) but no
  `"license"` field. No `backend/pyproject.toml` `[project] license` entry either.
- **`gh repo view` confirms the GitHub repo is `PUBLIC`** (`jesgueva/acra_dev`). That matters: with
  no LICENSE file, the code is view-only by default copyright — nobody has explicit reuse rights —
  while the client logo sits in the same public tree with no notice attached at all. Today the repo
  is simultaneously *more* locked-down than an academic portfolio piece usually wants (no reuse
  grant for the student's own code) and *less* locked-down than the logo actually needs (no
  redistribution notice on it whatsoever).

### 1.2 What's in the repo and its actual provenance

| Asset | Provenance | Redistributable? |
|---|---|---|
| `frontend/acra_logo.png` (committed `8efcbad`, ACR-17) | Client brand asset | **No** — no attribution/license ever attached; must be called out explicitly |
| `backend/scripts/ocr_bench/` (corpus generator) + `backend/tests/fixtures/ocr/` | Deterministic Pillow-rendered **synthetic** BOLs, decided synthetic-only per `plan_a8_a10_readiness.md` §6 #2 | Yes — already partially documented in `backend/tests/fixtures/ocr/README.md:31-33` ("not committed... deterministic generator plus labels") |
| `backend/scripts/seed_fake_data.py` | Arithmetic-on-row-index synthetic data, no RNG, no real records (`seed_fake_data.py:1-14`) | Yes |
| Demo credentials in `README.md:81-90` | Synthetic, README already warns "local development only" | Yes, with existing caveat |
| `acra_docs/reference/client_domain_model.md` (separate repo, not in `acra_dev`) | Real production-flow vocabulary walked through with the client, in English/Spanish | Out of scope for **this** repo's LICENSE — lives in a different repo with its own visibility; flagged here only so the provenance doc doesn't contradict it |
| Application source code (`backend/app`, `frontend/src`, etc.) | Written by the student for this engagement | Own choice — see §2 |

The brief's exact ask (`10_Artifact_Hardening_Reproducibility_Check/brief.md` §2): *"If the project
uses data, explain where the data comes from, how it should be prepared, and what cannot be
redistributed."* Only the logo fails that test today.

---

## 2. Open decision — what license, if any (blocking, needs your call)

This is the one judgment call in an otherwise mechanical ticket, because the answer depends on
facts only you know: whether this is meant to double as a public portfolio piece, and whether
there's any actual agreement with the client about redistribution.

| Option | What it does | Tradeoff |
|---|---|---|
| **A — MIT for the code, explicit carve-out for the logo** *(recommended)* | Root `LICENSE` = MIT, copyright line to you. New `docs/DATA_PROVENANCE.md` states the logo is excluded from the grant (client-owned, included for local development context only, not licensed for reuse/redistribution). | Standard pattern for public academic/portfolio repos with one non-OSS asset (e.g. a trademarked logo) sitting in an otherwise-open tree. Doesn't grant anyone rights to the logo just because it's in a public repo. |
| **B — All-rights-reserved (no OSS grant at all)** | `LICENSE` states copyright, all rights reserved, repository is source-available for evaluation only — no reuse/fork/redistribution grant. | Safest with respect to the client relationship, since none of the code is licensed out either. But the repo is already public on GitHub for the course's evidence trail, so this mostly formalizes "look, don't take" rather than changing who can currently view it. |
| **C — No LICENSE file, provenance doc only** | Skip the license question, just ship `docs/DATA_PROVENANCE.md`. | Fails the brief's "what cannot be redistributed" ask only partially — it names the *data* problem but leaves the *code* in the same ambiguous no-license default it's in today, which is the thing A10-6 exists to fix. |

**Recommendation: Option A.** Nothing in the repo suggests a real NDA or client redistribution
restriction on the *code* — `client_domain_model.md` (the one document that reflects real client
input) already lives in the separate, non-public `acra_docs` repo, not here. The one genuinely
client-owned asset actually inside `acra_dev` is the logo, so scope the restriction to exactly that
rather than locking down the whole tree.

**If you'd rather go with B or C, say so in this file and I'll adjust before implementing.**

---

## 3. Change list

### CREATE

| File | Purpose |
|---|---|
| `LICENSE` | MIT text (pending §2's answer), copyright line `Copyright (c) 2026 <name>` |
| `docs/DATA_PROVENANCE.md` | One doc per §4 below: what's synthetic, what's client-owned, what's demo-only, and the explicit "not licensed for redistribution" statement for the logo |

### MODIFY

| File | Change |
|---|---|
| `README.md` | Add `docs/DATA_PROVENANCE.md` to the Documentation table (`README.md:210-219`), and a one-line "License" section near the top or bottom, matching the existing doc-table style |
| `CONTRIBUTING.md` | One line in the artifact-storage table or a short note pointing at the provenance doc, so "what belongs in this repo" and "what can leave this repo" are cross-referenced |
| `frontend/package.json` | Add `"license": "MIT"` (or the chosen SPDX identifier) so tooling that reads it agrees with the root `LICENSE` file |
| `backend/pyproject.toml` | Add `license = "MIT"` (or matching) under `[project]`, same reasoning |
| `plans/plan_a8_a10_readiness.md` | Flip the A10-6 row in §8.1 and append the §8.2 evidence row |

**Explicitly not touching:** `frontend/acra_logo.png` itself, `acra_docs` (separate repo, out of
scope), any application code.

---

## 4. `docs/DATA_PROVENANCE.md` — proposed structure

1. **Purpose** — one paragraph, answers the brief's three questions (where data comes from, how to
   prepare it, what can't be redistributed) up front.
2. **Synthetic / redistributable** — seed data (`seed_fake_data.py`), the OCR corpus generator and
   its committed sample fixture. Cross-link `backend/tests/fixtures/ocr/README.md` rather than
   duplicating it.
3. **Client-owned / not redistributable** — `frontend/acra_logo.png`: what it is, why it's in the
   repo (UI branding for the working prototype), and the explicit statement that it is not covered
   by `LICENSE` and must not be reused outside this engagement.
4. **Demo credentials** — cross-link the existing README warning (`README.md:90`) rather than
   duplicating it; state plainly they are synthetic and local-only.
5. **Third-party dependencies** — one line noting dependency licenses are governed by their own
   packages (`requirements.lock`, `package-lock.json`) and are not audited individually here, since
   the brief's ask is about *this project's* data, not a full third-party license inventory.

---

## 5. Test plan

No backend or frontend tests apply — this is documentation. Verification is:

- `LICENSE` present at repo root, valid SPDX-recognizable MIT text (GitHub's license detector
  should pick it up — visible on the repo's right-hand sidebar after merge).
- `docs/DATA_PROVENANCE.md` renders correctly (markdown lint / link check, matching how other docs
  are verified — `CONTRIBUTING.md` states relative markdown links must resolve, and
  `plan_a8_a10_readiness.md` §1 already noted "every relative markdown link resolves" as a baseline
  fact worth preserving).
- `./scripts/smoke-test.sh` — confirms the docs-only change didn't break anything (should be a
  no-op pass, but cheap to prove).

---

## 6. Live verification

Docs-only, so "live" means reading the rendered output, not a click-through:

1. View `LICENSE` and `docs/DATA_PROVENANCE.md` rendered on GitHub (or locally in a markdown
   previewer) — confirm formatting, links resolve, no broken relative paths.
2. Confirm `README.md`'s Documentation table links to the new doc and the license line reads
   correctly.
3. `./scripts/smoke-test.sh` passes (no regression from the docs-only diff).

---

## 7. Risks / open questions

- **§2 is the blocking one** — license choice (A/B/C) needs your decision before I write `LICENSE`
  text, since the wrong choice here is the kind of thing that's awkward to walk back once a grader
  or a stranger has already forked the repo under it.
- **R1 — scope creep into a full third-party license audit.** The brief asks about *data*
  redistribution, not a SPDX inventory of every pinned dependency. §4 point 5 deliberately keeps
  that to one line rather than opening a much larger, unscoped task.
- **R2 — `acra_docs` is out of scope but adjacent.** That repo holds the real client vocabulary
  (`client_domain_model.md`) and is not part of this ticket's change list. If it's also public,
  that's a separate, pre-existing exposure this ticket doesn't fix — worth a one-line mention to you
  now rather than silently ignoring it, but not this ticket's job to resolve.

---

## 8. Build order

1. Cut `ticket-47/license-data-provenance` from `origin/master`.
2. Wait for §2's answer (or proceed under the recommended Option A if you'd rather I not block).
3. Write `LICENSE`.
4. Write `docs/DATA_PROVENANCE.md` per §4.
5. Update `README.md`, `CONTRIBUTING.md`, `frontend/package.json`, `backend/pyproject.toml`.
6. `./scripts/smoke-test.sh`.
7. Update `plans/plan_a8_a10_readiness.md` §8.
8. Draft PR, `Closes ACR-47`.

---

## 9. Definition of done

- [ ] `LICENSE` at repo root, matching §2's decision
- [ ] `docs/DATA_PROVENANCE.md` naming synthetic vs. client-owned vs. demo-only data, with an
      explicit redistribution statement for `frontend/acra_logo.png`
- [ ] README / CONTRIBUTING cross-referenced
- [ ] `frontend/package.json` / `backend/pyproject.toml` license fields match the root `LICENSE`
- [ ] Smoke test green; draft PR open; `plan_a8_a10_readiness.md` §8 updated
