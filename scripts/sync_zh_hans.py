#!/usr/bin/env python3
"""Sync zh-Hans String Catalogs (.xcstrings) after merging upstream updates.

Usage:
  1. Extract new/changed strings from Xcode into .xcstrings (preserving existing translations):
       python3 scripts/sync_zh_hans.py extract

  2. Apply translations from a JSON file (mapping table_path -> {key: translated_value}):
       python3 scripts/sync_zh_hans.py apply untranslated_zh_hans.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CATALOG_MAP = {
    "AltStore/en.lproj/Localizable.strings": ROOT / "AltStore/Localizable.xcstrings",
    "AltStore/en.lproj/InfoPlist.strings": ROOT / "AltStore/InfoPlist.xcstrings",
    "AltWidget/en.lproj/Localizable.strings": ROOT / "AltWidget/Localizable.xcstrings",
    "AltWidget/en.lproj/InfoPlist.strings": ROOT / "AltWidget/InfoPlist.xcstrings",
    "SideBackup/en.lproj/Localizable.strings": ROOT / "SideBackup/Localizable.xcstrings",
    "SideBackup/en.lproj/InfoPlist.strings": ROOT / "SideBackup/InfoPlist.xcstrings",
}


def load_catalog(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"sourceLanguage": "en", "strings": {}, "version": "1.0"}


def save_catalog(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cmd_extract(out_untranslated: Path | None) -> int:
    with tempfile.TemporaryDirectory(prefix="sidestore_xcloc_") as tmpdir:
        cmd = [
            "xcodebuild",
            "-exportLocalizations",
            "-localizationPath",
            tmpdir,
            "-project",
            str(ROOT / "AltStore.xcodeproj"),
            "-exportLanguage",
            "zh-Hans",
            "CODE_SIGNING_ALLOWED=NO",
        ]
        print("Running:", " ".join(cmd))
        res = subprocess.run(cmd, cwd=ROOT)
        if res.returncode != 0:
            return res.returncode

        xliff_path = Path(tmpdir) / "zh-Hans.xcloc/Localized Contents/zh-Hans.xliff"
        tree = ET.parse(xliff_path)
        ns = {"x": "urn:oasis:names:tc:xliff:document:1.2"}

        untranslated: dict[str, dict[str, str]] = {}
        new_count = 0

        for f in tree.getroot().findall("x:file", ns):
            orig = f.attrib.get("original", "")
            catalog_path = CATALOG_MAP.get(orig)
            if not catalog_path:
                continue

            catalog = load_catalog(catalog_path)
            strings = catalog.setdefault("strings", {})

            for unit in f.findall(".//x:trans-unit", ns):
                uid = unit.attrib["id"]
                src_el = unit.find("x:source", ns)
                note_el = unit.find("x:note", ns)
                src = "".join(src_el.itertext()) if src_el is not None else uid
                note = "".join(note_el.itertext()) if note_el is not None else ""

                entry = strings.setdefault(uid, {})
                if note:
                    entry["comment"] = note

                locs = entry.setdefault("localizations", {})
                zh = locs.get("zh-Hans", {}).get("stringUnit", {})
                if zh.get("state") != "translated" or not zh.get("value"):
                    locs["zh-Hans"] = {"stringUnit": {"state": "new", "value": ""}}
                    rel = str(catalog_path.relative_to(ROOT))
                    untranslated.setdefault(rel, {})[uid] = src
                    new_count += 1

            save_catalog(catalog_path, catalog)

        if out_untranslated and untranslated:
            out_untranslated.write_text(
                json.dumps(untranslated, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"Found {new_count} untranslated strings -> {out_untranslated}")
        else:
            print(f"Sync complete. Untranslated strings: {new_count}")
    return 0


def cmd_apply(json_path: Path) -> int:
    updates = json.loads(json_path.read_text(encoding="utf-8"))
    applied = 0
    for rel_path, mapping in updates.items():
        catalog_path = ROOT / rel_path
        catalog = load_catalog(catalog_path)
        strings = catalog.setdefault("strings", {})
        for uid, zh_val in mapping.items():
            entry = strings.setdefault(uid, {})
            locs = entry.setdefault("localizations", {})
            locs["zh-Hans"] = {"stringUnit": {"state": "translated", "value": zh_val}}
            applied += 1
        save_catalog(catalog_path, catalog)
    print(f"Applied {applied} translations.")
    return 0


def cmd_audit() -> int:
    """Audit extra_zh_hans.json, extra_swift_zh_hans.json, and scan Swift UI strings."""
    extra_ui_path = ROOT / "scripts/extra_zh_hans.json"
    extra_ui: dict[str, list[dict[str, str]]] = (
        json.loads(extra_ui_path.read_text(encoding="utf-8")) if extra_ui_path.exists() else {}
    )
    stale_ui: list[tuple[str, str]] = []
    for rel_path, items in extra_ui.items():
        fp = ROOT / rel_path
        if not fp.exists():
            stale_ui.append((rel_path, "<file missing>"))
            continue
        ids = {el.attrib.get("id") for el in ET.parse(fp).getroot().iter() if el.attrib.get("id")}
        for item in items:
            if item["id"] not in ids:
                stale_ui.append((rel_path, f"id={item['id']} ({item.get('attr', '')})"))

    extra_path = ROOT / "scripts/extra_swift_zh_hans.json"
    extra_data: dict[str, list[dict[str, str]]] = (
        json.loads(extra_path.read_text(encoding="utf-8")) if extra_path.exists() else {}
    )

    # 1. Check for stale rules whose `find` text no longer matches
    stale: list[tuple[str, str]] = []
    for rel_path, rules in extra_data.items():
        fp = ROOT / rel_path
        if not fp.exists():
            stale.append((rel_path, "<file missing>"))
            continue
        text = fp.read_text(encoding="utf-8", errors="ignore")
        for r in rules:
            if r["find"] not in text:
                stale.append((rel_path, r["find"]))

    # 2. Load all xcstrings keys + zh-Hans values
    xc: dict[str, str] = {}
    for catalog_path in CATALOG_MAP.values():
        if not catalog_path.exists():
            continue
        for k, v in load_catalog(catalog_path).get("strings", {}).items():
            zh = v.get("localizations", {}).get("zh-Hans", {}).get("stringUnit", {}).get("value", "")
            xc[k] = zh

    # 3. Scan Swift files for String-parameter UI calls & Label(...) not covered by extra_swift_zh_hans.json
    param_re = re.compile(
        r'(?:title|subtitle|label|message|header|footer|detailText|placeholder):\s*"([A-Za-z][^"\\]{2,})"'
    )
    label_re = re.compile(r'Label\(\s*"([A-Za-z][^"\\]{2,})"')
    skip_line_re = re.compile(
        r'(Logger|os_log|print\(|debugLog|fatalError|NSLocalizedString|String\(localized:|LocalizedStringKey|@Parameter|DispatchQueue|URL\()'
    )

    missed_xc_param: list[tuple[str, int, str]] = []
    missed_new_ui: list[tuple[str, int, str]] = []

    for root_dir in ("AltStore", "SideStore", "AltWidget", "SideBackup"):
        base = ROOT / root_dir
        if not base.exists():
            continue
        for fp in sorted(base.rglob("*.swift")):
            rel = str(fp.relative_to(ROOT))
            if "/Tests/" in rel:
                continue
            extra_finds = {r["find"] for r in extra_data.get(rel, [])}
            for idx, line in enumerate(fp.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                sline = line.strip()
                if sline.startswith("//") or skip_line_re.search(sline):
                    continue
                for rx in (param_re, label_re):
                    for m in rx.finditer(line):
                        s = m.group(1)
                        if any(s in ef for ef in extra_finds):
                            continue
                        if s in xc:
                            # Label("...", systemImage:) takes LocalizedStringKey and auto-localizes via xcstrings
                            if rx is param_re and xc[s] and xc[s] != s:
                                missed_xc_param.append((rel, idx, s))
                        elif " " in s and not any(x in s for x in ("com.", "http://", "https://")):
                            missed_new_ui.append((rel, idx, s))

    print(f"Storyboard/XIB 失效规则: {len(stale_ui)} 条")
    for rel, pat in stale_ui[:10]:
        print(f"  [失效] {rel}: {pat[:80]}")

    print(f"Extra Swift 失效规则: {len(stale)} 条")
    for rel, pat in stale[:10]:
        print(f"  [失效] {rel}: {pat[:80]}")

    print(f"String 参数未注入 (xcstrings 已有但需补进 extra_swift): {len(missed_xc_param)} 处")
    for rel, idx, s in missed_xc_param[:15]:
        print(f"  [未注入] {rel}:L{idx} -> {s}")

    print(f"疑似新增未收录 Swift UI 文案: {len(missed_new_ui)} 处")
    for rel, idx, s in missed_new_ui[:15]:
        print(f"  [疑似新增] {rel}:L{idx} -> {s}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync zh-Hans String Catalogs for SideStore.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ext = sub.add_parser("extract", help="Extract strings from Xcode and update .xcstrings")
    p_ext.add_argument(
        "--out",
        type=Path,
        default=ROOT / "untranslated_zh_hans.json",
        help="Output JSON for untranslated keys (default: untranslated_zh_hans.json)",
    )

    p_app = sub.add_parser("apply", help="Apply translated JSON back into .xcstrings")
    p_app.add_argument("json_file", type=Path, help="Translated JSON file")

    sub.add_parser("audit", help="Audit extra_swift_zh_hans.json and scan Swift UI strings")

    args = parser.parse_args()
    if args.cmd == "extract":
        return cmd_extract(args.out)
    if args.cmd == "apply":
        return cmd_apply(args.json_file)
    return cmd_audit()


if __name__ == "__main__":
    raise SystemExit(main())
