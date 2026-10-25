---
name: wechat-db-decrypt
description: Use when asked to decrypt WeChat (微信) chat history / SQLite databases on macOS, extract the WCDB/SQLCipher database key, recover messages from db_storage, or export chats to text/HTML/JSON. Covers WeChat 4.x encrypted DBs, macOS key capture via lldb, and full export pipeline.
---

# 微信数据库解密（macOS / WeChat 4.x）

把 `~/Library/Containers/com.tencent.xinWeChat/.../xwechat_files/<wxid>_<hash>/db_storage` 下加密的 SQLite 库解密成可直接查询的明文库，并导出聊天记录。

## 何时用

- 用户要「解密微信聊天记录 / 导出微信聊天 / 找出微信数据库密钥」
- 需要恢复 message / contact / session / sns / favorite 等库内容
- 需要把历史消息做成可读文件（txt / html / json）

## 核心事实（已实测验证，WeChat 4.1.15 macOS arm64）

| 项 | 值 |
| --- | --- |
| 页大小 | 4096 |
| 每页 reserve | 80 = IV(16) + HMAC-SHA512(64) |
| 页 1 布局 | `[salt 16][密文 4000][IV 16][HMAC 64]` |
| 页 N 布局 | `[密文 4016][IV 16][HMAC 64]` |
| 主密钥 | 32 字节**原始值**，不是 hex 字符串 |
| enc_key | `PBKDF2-HMAC-SHA512(pass32, salt, 256000, dklen=32)` |
| mac_key | `PBKDF2-HMAC-SHA512(enc_key, salt ^ 0x3a, 2, dklen=32)` |
| 校验 | 页 1 解密后前 16 字节为 `SQLite format 3\0`；页面 HMAC 覆盖 `密文+IV` + `uint32LE(页号)` |

**关键陷阱**：PBKDF2 会被调用两类，`rounds=2` 的那次入参是**单库派生密钥**（每库不同），只能解对应库；只有 `rounds=256000` 的入参才是账号级 passphrase。抓错会让你只能开一个库。

## 流程

### 1. 侦察

```bash
bash scripts/recon.sh            # 打印微信版本、账号目录、db_storage 列表、密钥缓存位置
```

记录 `<WXID_DIR>`（形如 `wxid_xxx_ab12`）、`DB_STORAGE`、`APP`（/Applications/WeChat.app）。

### 2. 让目标进程可调试

WeChat 是 hardened runtime + 无 `get-task-allow`，直接 `task_for_pid` 会被拒（`KERN_FAILURE`，`debugserver` 日志可见）。不要动原应用，克隆一份改签名：

```bash
bash scripts/make_debuggable.sh prepare     # APFS 克隆 + 加 get-task-allow + 重签名 + 把原 App 挪到 .WeChat.orig.app
bash scripts/make_debuggable.sh launch      # open 克隆副本（LaunchServices 按 bundle id 解析，必须先挪开原 App）
```

### 3. 抓密钥

必须**登录状态**才有 DB 打开动作，也就才有 KDF 调用。抓取前先确认 `lsof -p <pid> | grep -c db_storage` 大于 0。

```bash
bash scripts/capture_key.sh                 # attach + 断 CCKeyDerivationPBKDF，输出 rounds/pass/salt
```

只看 `rounds=256000` 且 `plen=32 slen=16 prf=5` 的行，取 `pass`。若一直无命中，说明 DB 还没打开（停在登录页 / 弹窗遮挡），先完成登录。

### 4. 解密

```bash
python3 scripts/decrypt_db.py --src "$DB_STORAGE" --out ./db --key 00112233...
# 单库：--src path/to/x.db
```

脚本会逐库派生 key、解页、回填 `SQLite format 3\0`，并对每个输出跑 `pragma integrity_check` 报 OK/FAIL。

### 5. 导出

```bash
python3 scripts/export_chats.py --db ./db --out ./export
```

产出 `index.html` + `chats/*.html` + `chats_txt/*.txt` + `messages.json`。会话表名规则：`Msg_<md5(会话username)>`；发送人 `real_sender_id → Name2Id.rowid → username`；群聊正文带 `wxid_xxx:\n` 前缀需剥离；`WCDB_CT_message_content=4` 表示内容为 zstd 压缩（本脚本已处理）。

### 6. 复原环境（必做）

```bash
bash scripts/make_debuggable.sh restore     # 杀副本、恢复原 App、重启微信
```

## 判断密钥是否还有效

```python
md5(raw32)  # 记下来，重登后再抓一次比对
```

同机正常重登一般不变；重装、删除 `xwechat_files`、换设备、改密/风控会变。

## 注意

- 全程只读原数据目录；解密产物写到单独目录，不要回写 `db_storage`。
- 抓取需要把原 App 临时改名，**必须**执行 `restore`，否则用户桌面上的微信是 /tmp 副本。
- 媒体文件（图片/语音/视频）另算：图片是 xor + AES，key 与 DB key 不同，见 `references/format.md`。
