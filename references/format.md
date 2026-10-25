# WeChat 4.x 数据库格式与踩坑记录

实测环境：WeChat 4.1.15 (270135)、macOS 15.6.1 arm64。Windows 4.0.x 同一套 WCDB/SQLCipher4 参数，仅密钥获取方式不同。

## 文件布局

```
db_storage/
├── message/message_0.db        聊天消息（核心）
├── message/message_1.db        分片，表名与 message_0 不重复
├── message/media_0.db          媒体索引
├── message/message_fts.db      全文索引
├── contact/contact.db          联系人（username/remark/nick_name/alias）
├── session/session.db          会话列表 SessionTable
├── sns/sns.db                  朋友圈
├── favorite/favorite.db        收藏
└── ...
```

## 加密参数

| 项 | 值 |
| --- | --- |
| cipher | AES-256-CBC，逐页独立 |
| page size | 4096 |
| reserve | 80 = IV(16) + HMAC-SHA512(64) |
| KDF（主） | PBKDF2-HMAC-SHA512，256000 轮，dklen 32 |
| KDF（HMAC） | PBKDF2-HMAC-SHA512，2 轮，salt 为 `salt ^ 0x3a` |
| salt | 文件前 16 字节 |

页布局：

```
page 1 : [ salt(16) ][ ciphertext(4000) ][ IV(16) ][ HMAC(64) ]
page N : [ ciphertext(4016) ][ IV(16) ][ HMAC(64) ]
HMAC   : HMAC-SHA512(mac_key, page[SALT:PS-64] || uint32LE(page_no))
```

页 1 的 16 字节 salt **占掉了明文头 `SQLite format 3\0` 的位置**，所以解密出的第一页正文从 header 第 16 字节开始，导出时必须自己补回 `SQLite format 3\0`。校验页 1 成功最稳的判断是解密后前两字节等于 `0x10 0x00`（页大小 4096 大端）。

## 坑

1. **`task_for_pid` 被拒**：WeChat 带 hardened runtime 且无 `get-task-allow`，`lldb -p` 直接 `KERN_FAILURE`。做法是克隆 App → 加 `com.apple.security.get-task-allow` → ad-hoc 重签名 → 把原 App 改名腾出 bundle id（LaunchServices 按 bundle id 解析，不挪开就只会启动 /Applications 那份）。
2. **`open -n <路径>` 仍启动原 App**：同上，bundle id 冲突。必须 `mv /Applications/WeChat.app /Applications/.WeChat.orig.app`。
3. **抓到的密钥只能开一个库**：KDF 有两类调用。`rounds=2` 那次入参是**单库派生密钥**，`rounds=256000` 那次才是账号 passphrase。按 rounds 过滤，别取第一个命中。
4. **没有命中 = 没登录**：DB 只在登录后打开，停在登录页/被弹窗遮挡时不会有任何 KDF 调用。先用 `lsof -p <pid> | grep -c db_storage` 确认 > 0。
5. **`CCKeyDerivationPBKDF` 在 libcommonCrypto 里**：直接按符号名下断点即可命中，不需要找 stub（前提是进程确实在打开 DB）。
6. **正文被 zstd 压缩**：`WCDB_CT_message_content = 4` 表示内容是 zstd 流（magic `28 B5 2F FD`），要 `zstandard` 解压。
7. **群聊正文带前缀**：形如 `wxid_xxx:\n实际内容`，需剥离后按 sender 显示；`real_sender_id` 指向 `Name2Id.rowid`。
8. **表名是 md5**：`Msg_<md5(会话 username)>`，反查靠 `md5(contact.username)` 建表。
9. **WAL**：`-wal` 里可能还有未 checkpoint 的最新消息，只解 `.db` 会滞后一点；需要最新数据先让微信正常退出/切后台触发 checkpoint。
10. **媒体文件另一套密钥**：图片是 `xor 0x95` + AES，key 与 DB key 无关，从 `account_keys.json` 或进程里另取。

## 媒体（未包含在本 skill 脚本里）

- 图片：`.dat` 文件先按字节异或，再 AES-CBC 解密，key 形如 16 字节 hex（示例 `<16字节hex>`），xor key 0x95。
- 语音：`silk` 编码，需要 silk-v3 解码器再转 pcm/mp3。
- 视频：mp4 明文，一般在 `msg/video` 下。
