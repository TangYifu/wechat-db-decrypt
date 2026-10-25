#!/bin/bash
# 抓取 WeChat 4.x 数据库 passphrase（需已登录，DB 已打开）
# 用法: capture_key.sh [--timeout 秒] [--pid PID]
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
TIMEOUT=120
PID=""
while [ $# -gt 0 ]; do
  case "$1" in
    --timeout) TIMEOUT="$2"; shift 2;;
    --pid) PID="$2"; shift 2;;
    *) echo "未知参数 $1"; exit 1;;
  esac
done

[ -z "$PID" ] && PID=$(pgrep -f "WeChat.app/Contents/MacOS/WeChat$" | head -1)
[ -z "$PID" ] && { echo "错误: 找不到微信进程"; exit 1; }

OPENED=$(lsof -p "$PID" 2>/dev/null | grep -c db_storage)
echo "pid=$PID  db 打开数=$OPENED"
if [ "$OPENED" -eq 0 ]; then
  echo "警告: 该进程还没打开数据库（可能停在登录页），此时不会有 KDF 调用。"
  echo "      请先在微信窗口完成登录/进入主界面，再重跑本脚本。"
  exit 2
fi

LOG=$(mktemp -t wxkey.XXXXXX)
echo "日志: $LOG"
( sleep "$TIMEOUT"; pkill -INT -f "lldb -b -p $PID" 2>/dev/null ) &
WATCH=$!

lldb -b -p "$PID" \
  -o "command script import $HERE/wxcrypto.py" \
  -o "continue" \
  -o "process detach" \
  -o "quit" 2>&1 | tee "$LOG"

kill "$WATCH" 2>/dev/null
echo "---- 结果 ----"
grep '^DB_KEY ' "$LOG" | awk '{print $2}' | sort -u | while read -r k; do echo "passphrase(raw32) = $k"; done
grep -q '^DB_KEY ' "$LOG" || echo "未抓到账号密钥：确认已登录且 db 打开数>0，或调大 --timeout"
