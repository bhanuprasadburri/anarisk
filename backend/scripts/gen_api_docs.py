"""Generate docs/API.md from the live OpenAPI spec (run with the API server up).

The output path is derived from this file's location so the script works regardless of
where the repo is checked out, and the API root is configurable via NIMBUS_API_ROOT.
"""
import collections
import json
import os
import urllib.request
from pathlib import Path

API_ROOT = os.environ.get("NIMBUS_API_ROOT", "http://127.0.0.1:8000/api/v1").rstrip("/")
REPO_DOCS = Path(__file__).resolve().parents[2] / "docs" / "API.md"
# FastAPI serves the schema at the app root, not under the /api/v1 router prefix.
SPEC_URL = os.environ.get(
    "NIMBUS_SPEC_URL", API_ROOT.rsplit("/api/v1", 1)[0] + "/openapi.json"
)

spec = json.load(urllib.request.urlopen(SPEC_URL))
groups: dict[str, list[tuple[str, str, str]]] = collections.OrderedDict()
total = 0
for path, ops in sorted(spec["paths"].items()):
    for method, op in ops.items():
        if method.upper() not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            continue
        total += 1
        tag = op.get("tags", ["misc"])[0]
        groups.setdefault(tag, []).append((method.upper(), path, op.get("summary", "") or ""))

lines = [
    "# AnaRisk — API Reference",
    "",
    "Generated from the live OpenAPI schema (`GET /openapi.json`, interactive docs at `/docs`).",
    f"Base URL: `{API_ROOT}` — **{total} endpoints** across {len(groups)} tags.",
    "",
    "Authentication: `Authorization: Bearer <JWT>` (obtain via `POST /auth/login`).",
    "Role checks are enforced server-side per endpoint; unauthenticated requests return 401,",
    "missing permissions return 403.",
    "",
]
for tag, items in groups.items():
    lines.append(f"## {tag} ({len(items)})")
    lines.append("")
    lines.append("| Method | Path | Summary |")
    lines.append("|---|---|---|")
    for method, path, summary in sorted(items, key=lambda x: (x[1], x[0])):
        s = summary.replace("|", "\\|")
        lines.append(f"| {method} | `{path}` | {s} |")
    lines.append("")

out = "\n".join(lines) + "\n"
REPO_DOCS.parent.mkdir(parents=True, exist_ok=True)
with open(REPO_DOCS, "w", encoding="utf-8") as f:
    f.write(out)
print(f"OK: {total} endpoints, {len(groups)} tags -> {REPO_DOCS}")
