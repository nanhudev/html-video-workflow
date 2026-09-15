#!/usr/bin/env python
"""Regenerate `schemas/video_ir_v2.schema.json` from the Pydantic models.

The IR schema is a *generated artifact*: `project/ir.py` is the single source of
truth, and a hand-edited schema would silently drift from the code that actually
validates. Run this after touching any model, and commit the result.

    python scripts/export_schema.py            # write
    python scripts/export_schema.py --check    # exit 1 if stale (for CI)

The `--check` mode is what keeps this honest: a schema that lags the models is
worse than no schema, because consumers trust it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

SCHEMA_PATH = ROOT / "schemas" / "video_ir_v2.schema.json"

SCHEMA_META = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": (
        "https://github.com/nanhudev/html-video-workflow/"
        "schemas/video_ir_v2.schema.json"
    ),
    "title": "Video Project IR V2",
    "description": (
        "Renderer-neutral video project description. Layers carry "
        "{type, role, content, layout, motion} and must never contain "
        "renderer-specific tokens such as remotionComponent or cssClass."
    ),
}


def build_schema() -> dict:
    from html_video_workflow.project.ir import VideoProject

    schema = VideoProject.model_json_schema()
    # Metadata first so the file reads well at the top.
    return {**SCHEMA_META, **schema}


def render(schema: dict) -> str:
    return json.dumps(schema, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    check_only = "--check" in sys.argv
    text = render(build_schema())

    if check_only:
        if not SCHEMA_PATH.exists():
            print(f"FAIL {SCHEMA_PATH.relative_to(ROOT)} does not exist")
            return 1
        if SCHEMA_PATH.read_text(encoding="utf-8") != text:
            print(
                f"FAIL {SCHEMA_PATH.relative_to(ROOT)} is stale — "
                "run: python scripts/export_schema.py"
            )
            return 1
        print(f"OK   {SCHEMA_PATH.relative_to(ROOT)} matches the models")
        return 0

    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(text, encoding="utf-8")
    print(f"wrote {SCHEMA_PATH.relative_to(ROOT)} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
