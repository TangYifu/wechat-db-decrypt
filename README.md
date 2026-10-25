# wechat-db-decrypt

微信（WeChat 4.x）本地数据库解密 + 聊天记录导出的 Claude/DSH skill，macOS 实测可用。

- 抓密钥：`lldb` 断 `CCKeyDerivationPBKDF`，取 `rounds=256000` 的 32 字节入参
- 解密：AES-256-CBC 逐页解，页 4096 / reserve 80（IV 16 + HMAC-SHA512 64）
- 导出：`index.html` + 每会话 HTML + 纯文本 + `messages.json`

## 安装

```bash
cp -R . ~/.dsh/skills/wechat-db-decrypt      # 或 ~/.claude/skills/
```

## 用法

```bash
bash scripts/recon.sh                                  # 1. 侦察目录/版本/进程
bash scripts/make_debuggable.sh prepare                # 2. 克隆 + 重签名（原 App 只改名）
bash scripts/make_debuggable.sh launch                 #    启动可调试副本
bash scripts/capture_key.sh                            # 3. 抓 passphrase（需已登录）
python3 scripts/decrypt_db.py --src "$DB_STORAGE" --out ./db --key <64hex>
python3 scripts/export_chats.py --db ./db --out ./export
bash scripts/make_debuggable.sh restore                # 4. 复原环境
```

依赖：`pip install pycryptodome zstandard`，以及 Xcode Command Line Tools（`lldb`）。

## 范围

只处理本机、本人账号的数据；脚本对 `db_storage` 全程只读，产物写到独立目录。抓取阶段会临时把 `/Applications/WeChat.app` 改名，`restore` 会还原并重启微信。

详细格式与踩坑见 [references/format.md](references/format.md)。
