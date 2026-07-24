"""Dump the FastAPI route inventory in the A5 evidence format."""
from app.main import app

rows = []
for r in app.routes:
    methods = getattr(r, "methods", None)
    path = getattr(r, "path", None)
    if not path:
        continue
    if methods:
        verbs = ",".join(sorted(m for m in methods if m not in ("HEAD", "OPTIONS")))
    else:
        verbs = "GET"
    rows.append((path, verbs))

rows = sorted(set(rows), key=lambda x: (x[0], x[1]))

print("ACRA MES API — route inventory (FastAPI app.routes)")
print()
print(f"{'METHODS':<22} PATH")
print("-" * 60)
for path, verbs in rows:
    print(f"{verbs:<22} {path}")
print()
print(f"Total: {len(rows)} routes")
