"""Load and query the 3 / 6 / 29 judicial-intelligence catalog."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data" / "catalog.json"


@lru_cache(maxsize=1)
def load() -> dict[str, Any]:
    data = json.loads(CATALOG_PATH.read_text())
    assert len(data["top"]) == 3
    assert len(data["main"]) == 6
    assert len(data["factual"]) == 29
    return data


def factual_by_main(main_id: str) -> list[dict[str, Any]]:
    return [f for f in load()["factual"] if f["main"] == main_id]


def factual_by_top(top_id: str) -> list[dict[str, Any]]:
    return [f for f in load()["factual"] if f["top"] == top_id]


def offer_markdown() -> str:
    cat = load()
    main_name = {m["id"]: m["name"] for m in cat["main"]}
    top_name = {t["id"]: t["name"] for t in cat["top"]}
    lines = ["# Kingsfield offer catalog — 29 factual categories", ""]
    current_main = None
    for f in cat["factual"]:
        if f["main"] != current_main:
            current_main = f["main"]
            lines.append(f"## {f['main']} · {main_name[f['main']]}")
            lines.append("")
        lines.append(f"**{f['id']} {f['name']}** ({top_name[f['top']]})")
        lines.append(f"{f['sentence']}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    print(offer_markdown())
