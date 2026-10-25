#!/bin/bash
# 让微信可被调试：克隆 App + 加 get-task-allow 重签名，原 App 只改名不动内容。
# 用法: make_debuggable.sh prepare | launch | restore | status
set -u
APP=${APP:-/Applications/WeChat.app}
BAK=/Applications/.WeChat.orig.app
WORK=${WORK:-/tmp/wxdbg}
CLONE="$WORK/WeChat.app"
ENT="$WORK/ent.plist"
STATE="$WORK/state"

die() { echo "错误: $*" >&2; exit 1; }

case "${1:-}" in
prepare)
  [ -d "$APP" ] || die "未找到 $APP"
  [ -d "$BAK" ] && die "已存在 $BAK，先跑 restore"
  mkdir -p "$WORK"
  echo "[1/4] 克隆（APFS clonefile，几乎不占空间）"
  rm -rf "$CLONE"
  cp -Rc "$APP" "$CLONE" 2>/dev/null || cp -R "$APP" "$CLONE"
  echo "[2/4] 提取 entitlements 并加入 get-task-allow"
  codesign -d --entitlements :- "$APP" 2>/dev/null > "$ENT" || die "读取 entitlements 失败"
  /usr/libexec/PlistBuddy -c "Add :com.apple.security.get-task-allow bool true" "$ENT" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Set :com.apple.security.get-task-allow true" "$ENT"
  echo "[3/4] ad-hoc 重签名副本"
  codesign -f -s - --entitlements "$ENT" "$CLONE" 2>&1 | sed 's/^/    /'
  echo "[4/4] 把原 App 改名腾出 bundle id"
  mv "$APP" "$BAK" || die "改名校验失败"
  echo "prepare" > "$STATE"
  echo "完成。接着跑: $0 launch"
  ;;
launch)
  [ -d "$CLONE" ] || die "先跑 prepare"
  if pgrep -f "/WeChat.app/Contents/MacOS/WeChat$" >/dev/null; then
    echo "已退出微信再继续"; pkill -f "/WeChat.app/Contents/MacOS/WeChat$"; sleep 3
  fi
  open -n "$CLONE" || die "启动失败"
  sleep 2
  PID=$(pgrep -f "wxdbg/WeChat.app/Contents/MacOS/WeChat$" | head -1)
  echo "PID=$PID"; [ -n "$PID" ] || die "副本没起来"
  echo "launch" > "$STATE"
  ;;
restore)
  echo "清理调试会话"
  pkill -f "lldb -b -p" 2>/dev/null
  sleep 1
  pkill -f "wxdbg/WeChat.app/Contents/MacOS/WeChat" 2>/dev/null
  sleep 3
  rm -rf "$CLONE" "$ENT"
  if [ -d "$BAK" ]; then
    rm -rf "$APP"
    mv "$BAK" "$APP" || die "恢复原 App 失败"
    echo "原 App 已恢复"
  fi
  codesign -dvv "$APP" 2>&1 | grep -E "Identifier=|Signature=" | sed 's/^/  /'
  open -a "$APP"
  sleep 5
  echo "微信已重启，db 打开数: $(pid=$(pgrep -f '/WeChat.app/Contents/MacOS/WeChat$' | head -1); [ -n "$pid" ] && lsof -p "$pid" 2>/dev/null | grep -c db_storage || echo 0)"
  ;;
status)
  echo "原 App: $([ -d "$APP" ] && echo 存在 || echo 缺失)"
  echo "备份:   $([ -d "$BAK" ] && echo 存在 || echo 无)"
  echo "克隆:   $([ -d "$CLONE" ] && echo 存在 || echo 无)"
  pgrep -fl "WeChat.app/Contents/MacOS/WeChat$" | sed 's/^/  /'
  ;;
*)
  echo "用法: $0 prepare|launch|restore|status"; exit 1;;
esac
