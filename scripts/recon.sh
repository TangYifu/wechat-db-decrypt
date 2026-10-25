#!/bin/bash
# 侦察微信安装与数据目录（只读，不改动任何东西）
set -u
APP=${APP:-/Applications/WeChat.app}
CONTAINER="$HOME/Library/Containers/com.tencent.xinWeChat"
FILES="$CONTAINER/Data/Documents/xwechat_files"

echo "== macOS =="
sw_vers | sed 's/^/  /'
echo "  arch: $(uname -m)"

echo "== WeChat =="
if [ -d "$APP" ]; then
  echo "  path:    $APP"
  echo "  version: $(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP/Contents/Info.plist" 2>/dev/null)"
  codesign -dvv "$APP" 2>&1 | grep -E "Identifier=|Signature=|flags=" | sed 's/^/  /'
else
  echo "  ! 未找到 $APP"
fi

echo "== 账号目录 =="
if [ -d "$FILES" ]; then
  for d in "$FILES"/*_*; do
    [ -d "$d/db_storage" ] || continue
    n=$(find "$d/db_storage" -name '*.db' | wc -l | tr -d ' ')
    echo "  WXID_DIR: $d"
    echo "    db_storage: $d/db_storage  (${n} 个 .db)"
  done
else
  echo "  ! 未找到 $FILES"
fi

echo "== 密钥缓存 =="
find "$FILES/all_users/login" -name 'key_info.db' 2>/dev/null | while read -r f; do
  c=$(sqlite3 "$f" "select count(*) from LoginKeyInfoTable;" 2>/dev/null)
  echo "  $f  (登录记录 ${c:-?} 条)"
done

echo "== 进程 =="
ps aux | grep -E "[W]eChat.app/Contents/MacOS/WeChat$" | awk '{print "  pid="$2}'
echo "  db 打开数: $(pid=$(pgrep -f '/WeChat.app/Contents/MacOS/WeChat$' | head -1); [ -n "$pid" ] && lsof -p "$pid" 2>/dev/null | grep -c db_storage || echo 0)"
