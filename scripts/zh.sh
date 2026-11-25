#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<'EOF'
SideStore 简体中文一键管理工具

用法:
  ./scripts/zh.sh          打开交互式菜单
  ./scripts/zh.sh build    一键构建简体中文版 SideStore.ipa
  ./scripts/zh.sh status   检查当前未翻译词条数量与全量审计
  ./scripts/zh.sh sync     拉取上游更新并提取新增未翻译词条
  ./scripts/zh.sh apply    将 untranslated_zh_hans.json 写回 .xcstrings
  ./scripts/zh.sh audit    仅审计失效规则与遗漏的 Swift UI 文案
EOF
}

cmd_sync() {
  echo ">>> 1/3 同步上游代码..."
  if git remote get-url upstream >/dev/null 2>&1; then
    git fetch upstream develop
    git merge --no-edit -X ours upstream/develop
  else
    git fetch origin develop
    git merge --no-edit -X ours origin/develop
  fi
  git submodule update --init --recursive

  echo ">>> 2/3 扫描 .xcstrings 新增词条..."
  python3 scripts/sync_zh_hans.py extract --out untranslated_zh_hans.json
  if [ -f untranslated_zh_hans.json ]; then
    echo ""
    echo "发现新增未翻译词条，已导出到: untranslated_zh_hans.json"
    echo "翻译完成后运行: ./scripts/zh.sh apply"
  else
    echo ""
    echo "没有新增 .xcstrings 未翻译词条。"
  fi

  echo ">>> 3/3 审计 Swift 硬编码文案与失效规则..."
  python3 scripts/sync_zh_hans.py audit
}

cmd_apply() {
  if [ ! -f untranslated_zh_hans.json ]; then
    echo "未找到 untranslated_zh_hans.json，无需写回。"
    exit 0
  fi
  python3 scripts/sync_zh_hans.py apply untranslated_zh_hans.json
  rm -f untranslated_zh_hans.json
  echo "已写回 .xcstrings 并清理临时文件。"
}

cmd_build() {
  cleanup() {
    python3 scripts/apply_extra_zh.py restore || true
  }
  trap cleanup EXIT

  if [ ! -f Dependencies/SideSign/Package.swift ] || [ ! -f Dependencies/minimuxer/Package.swift ]; then
    echo ">>> Submodules missing, initializing..."
    git submodule update --init --recursive
  fi

  python3 scripts/apply_extra_zh.py apply
  rm -rf SideStore.xcarchive
  BASE_VER=$(grep -m1 '^MARKETING_VERSION = ' Build.xcconfig | sed 's/MARKETING_VERSION = //')
  BUILD_DATE=$(date -u +%Y%m%d)
  BUILD_NUM=$(git rev-list --count HEAD 2>/dev/null || echo 0)
  SHORT_SHA=$(git rev-parse --short=8 HEAD)
  LOCAL_VER="${BASE_VER}-${BUILD_DATE}.${BUILD_NUM}+${SHORT_SHA}"
  echo ">>> 构建版本号: $LOCAL_VER"
  make -B build MARKETING_VERSION="$LOCAL_VER"

  if command -v ldid >/dev/null 2>&1; then
    make fakesign
  else
    codesign -f -s - --entitlements AltStore/Resources/ReleaseEntitlements.plist SideStore.xcarchive/Products/Applications/SideStore.app/SideStore
    codesign -f -s - --entitlements AltWidget/Resources/ReleaseEntitlements.plist SideStore.xcarchive/Products/Applications/SideStore.app/PlugIns/AltWidgetExtension.appex/AltWidgetExtension
    unzip -q -o SideStore.xcarchive/Products/Applications/SideStore.app/SideBackup.ipa -d SideStore.xcarchive/Products/Applications/SideStore.app/
    codesign -f -s - --entitlements SideBackup/SideBackup.entitlements SideStore.xcarchive/Products/Applications/SideStore.app/Payload/SideBackup.app/SideBackup
    (cd SideStore.xcarchive/Products/Applications/SideStore.app/ && rm -f SideBackup.ipa && zip -qr SideBackup.ipa Payload)
    rm -rf SideStore.xcarchive/Products/Applications/SideStore.app/Payload
  fi

  make ipa
  echo "Done: SideStore.ipa"
}

cmd_status() {
  python3 - <<'PY'
import json
from pathlib import Path

files = [
    "AltStore/Localizable.xcstrings",
    "AltStore/InfoPlist.xcstrings",
    "AltWidget/Localizable.xcstrings",
    "AltWidget/InfoPlist.xcstrings",
    "SideBackup/Localizable.xcstrings",
    "SideBackup/InfoPlist.xcstrings",
]
total = 0
untranslated = 0
for fp in files:
    p = Path(fp)
    if not p.exists():
        continue
    data = json.loads(p.read_text(encoding="utf-8"))
    strings = data.get("strings", {})
    total += len(strings)
    for v in strings.values():
        zh = v.get("localizations", {}).get("zh-Hans", {}).get("stringUnit", {})
        if not zh.get("value"):
            untranslated += 1

extra = Path("scripts/extra_zh_hans.json")
extra_count = sum(len(v) for v in json.loads(extra.read_text(encoding="utf-8")).values()) if extra.exists() else 0
swift_extra = Path("scripts/extra_swift_zh_hans.json")
swift_count = sum(len(v) for v in json.loads(swift_extra.read_text(encoding="utf-8")).values()) if swift_extra.exists() else 0
print(f"String Catalogs: {total} 条（空缺: {untranslated} 条）")
print(f"Storyboard/XIB : {extra_count} 条")
print(f"Swift 补充文案 : {swift_count} 条")
PY
  echo ""
  python3 scripts/sync_zh_hans.py audit
}

interactive_menu() {
  while true; do
    echo ""
    echo "====== SideStore 简体中文工具 ======"
    echo "1) 构建简体中文版 SideStore.ipa (build)"
    echo "2) 查看翻译统计与全量审计 (status)"
    echo "3) 同步上游代码并扫描新增词条 (sync)"
    echo "4) 写回 untranslated_zh_hans.json (apply)"
    echo "5) 仅审计失效规则与漏翻 (audit)"
    echo "0) 退出"
    read -rp "请选择操作 [0-5]: " choice
    case "$choice" in
      1) cmd_build; break ;;
      2) cmd_status ;;
      3) cmd_sync ;;
      4) cmd_apply ;;
      5) python3 scripts/sync_zh_hans.py audit ;;
      0) exit 0 ;;
      *) echo "无效选项，请输入 0-5。" ;;
    esac
  done
}

if [ $# -eq 0 ]; then
  if [ -t 0 ]; then
    interactive_menu
  else
    usage
  fi
  exit 0
fi

case "$1" in
  sync)   cmd_sync ;;
  apply)  cmd_apply ;;
  build)  cmd_build ;;
  status) cmd_status ;;
  audit)  python3 scripts/sync_zh_hans.py audit ;;
  -h|--help|help) usage ;;
  *)      usage; exit 1 ;;
esac
