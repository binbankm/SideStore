#!/usr/bin/env python3
"""Temporarily inject/restore Storyboard, XIB, and unlocalized Swift zh-Hans strings for builds.

Usage:
  python3 scripts/apply_extra_zh.py apply
  python3 scripts/apply_extra_zh.py restore
"""

from __future__ import annotations

import argparse
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTRA_UI_JSON = ROOT / "scripts/extra_zh_hans.json"
EXTRA_SWIFT_JSON = ROOT / "scripts/extra_swift_zh_hans.json"


def apply_translations() -> int:
    total_ui = 0
    if EXTRA_UI_JSON.exists():
        data = json.loads(EXTRA_UI_JSON.read_text(encoding="utf-8"))
        for rel_path, items in data.items():
            file_path = ROOT / rel_path
            if not file_path.exists():
                print(f"Warning: {rel_path} not found, skipping.")
                continue

            tree = ET.parse(file_path)
            by_id: dict[str, list[dict]] = {}
            for item in items:
                by_id.setdefault(item["id"], []).append(item)

            file_applied = 0
            for el in tree.getroot().iter():
                oid = el.attrib.get("id")
                if oid not in by_id:
                    continue
                for item in by_id[oid]:
                    attr = item["attr"]
                    if attr in el.attrib:
                        el.attrib[attr] = item["zh"]
                        file_applied += 1

            tree.write(file_path, encoding="UTF-8", xml_declaration=True)
            total_ui += file_applied
            print(f"Patched {rel_path}: {file_applied} attributes")

    total_swift = 0
    if EXTRA_SWIFT_JSON.exists():
        swift_data = json.loads(EXTRA_SWIFT_JSON.read_text(encoding="utf-8"))
        for rel_path, rules in swift_data.items():
            file_path = ROOT / rel_path
            if not file_path.exists():
                continue
            text = file_path.read_text(encoding="utf-8")
            file_hits = 0
            for rule in rules:
                if rule["find"] in text:
                    text = text.replace(rule["find"], rule["replace"])
                    file_hits += 1
            if file_hits:
                file_path.write_text(text, encoding="utf-8")
                total_swift += file_hits

    print(f"Total applied: {total_ui} Storyboard/XIB attributes, {total_swift} Swift UI rules")
    return 0


def restore_files() -> int:
    paths: list[str] = []
    for cfg in (EXTRA_UI_JSON, EXTRA_SWIFT_JSON):
        if cfg.exists():
            data = json.loads(cfg.read_text(encoding="utf-8"))
            paths.extend(p for p in data.keys() if (ROOT / p).exists())
    if not paths:
        return 0
    res = subprocess.run(["git", "checkout", "--", *paths], cwd=ROOT)
    if res.returncode == 0:
        print(f"Restored {len(paths)} files to clean git state.")
    return res.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply or restore extra zh-Hans strings.")
    parser.add_argument("action", choices=["apply", "restore"])
    args = parser.parse_args()
    if args.action == "apply":
        return apply_translations()
    return restore_files()


if __name__ == "__main__":
    raise SystemExit(main())
