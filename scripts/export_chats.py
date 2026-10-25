#!/usr/bin/env python3
"""把解密后的微信库导出成可读聊天记录（txt / html / json）。

用法:
  export_chats.py --db ./db --out ./export [--me wxid_xxx] [--include-biz]

--db 下需包含 contact.db 与 message_*.db（decrypt_db.py 的默认输出结构即可）。
"""
import argparse, datetime, hashlib, html, json, os, re, sqlite3, sys

try:
    import zstandard as zstd
    DCTX = zstd.ZstdDecompressor()
except ImportError:
    DCTX = None

APP_LABEL = {6: '[文件]', 8: '[表情]', 19: '[聊天记录]', 33: '[小程序]', 36: '[小程序]',
             57: '[引用]', 62: '[引用]', 2000: '[转账]', 2001: '[红包]'}


def maybe_zstd(b):
    if DCTX and isinstance(b, bytes) and b[:4] == b'\x28\xb5\x2f\xfd':
        try:
            return DCTX.decompress(b).decode('utf-8', 'replace')
        except Exception:
            return None
    return None


def find(d, name):
    for root, _, fs in os.walk(d):
        for f in fs:
            if f == name:
                return os.path.join(root, f)
    return None


def load_contacts(path):
    out = {}
    if not path or not os.path.exists(path):
        return out
    con = sqlite3.connect(path)
    try:
        for u, rem, nick, alias in con.execute(
                "select username,remark,nick_name,alias from contact"):
            if u:
                out[u] = rem or nick or alias or u
    except sqlite3.Error as e:
        print('WARN 读 contact 失败: %s' % e, file=sys.stderr)
    con.close()
    return out


def decode(local_type, content, compress, names):
    t, sub = local_type & 0xFFFFFFFF, local_type >> 32
    txt = ''
    if isinstance(content, bytes):
        txt = maybe_zstd(content) or content.decode('utf-8', 'replace')
    elif content is not None:
        txt = content
    if isinstance(compress, bytes) and compress:
        txt = maybe_zstd(compress) or txt
    sender = None
    if isinstance(txt, str):
        m = re.match(r'^(wxid_[0-9a-zA-Z_\-]+|[0-9]+@chatroom):\n', txt)
        if m:
            sender, txt = m.group(1), txt[m.end():]
    if t == 1:
        return txt or '', sender
    if t in (3,):   return '[图片]', sender
    if t == 34:     return '[语音]', sender
    if t == 43:     return '[视频]', sender
    if t == 42:     return '[名片]', sender
    if t == 47:     return '[表情]', sender
    if t == 48:     return '[位置]', sender
    if t == 50:     return '[通话]', sender
    if t == 10000:  return (txt or '').strip(), sender
    if t == 10002:  return '[撤回了一条消息]', sender
    if t == 49:
        title = re.search(r'<title>(.*?)</title>', txt or '', re.S)
        des = re.search(r'<des>(.*?)</des>', txt or '', re.S)
        label = APP_LABEL.get(sub, '[链接/应用消息]')
        extra = ' '.join(html.unescape(x.group(1)) for x in (title, des) if x)[:120]
        return label + (' ' + extra if extra else ''), sender
    return '[type=%d sub=%d]' % (t, sub), sender


CSS = """
body{background:#111;color:#e6e6e6;font-family:-apple-system,"PingFang SC",sans-serif;margin:0}
a{color:#7cc4ff;text-decoration:none}
.wrap{max-width:900px;margin:0 auto;padding:20px}
h1{font-size:20px;border-bottom:1px solid #333;padding-bottom:10px}
.list a{display:flex;justify-content:space-between;padding:10px 12px;border-bottom:1px solid #222}
.list a:hover{background:#1b1b1b}
.meta{color:#888;font-size:12px}
.msg{margin:10px 0;display:flex;flex-direction:column}
.me{align-items:flex-end}
.bub{max-width:70%;padding:8px 12px;border-radius:10px;background:#2a2a2a;white-space:pre-wrap;word-break:break-word}
.me .bub{background:#1f5f3f}
.s{font-size:11px;color:#888;margin:0 4px 2px}
.ts{font-size:10px;color:#666;margin:2px 4px 0}
.bar{position:sticky;top:0;background:#151515;padding:12px 0;border-bottom:1px solid #333;margin-bottom:10px}
"""


def page(title, body):
    return ("<!doctype html><meta charset='utf-8'><title>%s</title><style>%s</style>"
            "<div class='wrap'>%s</div>" % (html.escape(title), CSS, body))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', required=True, help='解密后的库目录')
    ap.add_argument('--out', required=True)
    ap.add_argument('--me', default='', help='自己的 wxid（可选，仅用于判左右气泡）')
    ap.add_argument('--include-biz', action='store_true', help='一起导出公众号消息')
    a = ap.parse_args()

    contacts = load_contacts(find(a.db, 'contact.db'))
    me = a.me or next((u for u in contacts if u.startswith('wxid_') and contacts[u] == contacts.get(u)), '')

    # 收集所有含 Msg_ 表的库
    msg_dbs = []
    for root, _, fs in os.walk(a.db):
        for f in fs:
            if not f.endswith('.db'):
                continue
            if f.startswith('biz_message') and not a.include_biz:
                continue
            p = os.path.join(root, f)
            try:
                con = sqlite3.connect(p)
                t = con.execute("select count(*) from sqlite_master where type='table' and name like 'Msg_%'").fetchone()[0]
                con.close()
            except sqlite3.Error:
                continue
            if t:
                msg_dbs.append(p)
    if not msg_dbs:
        sys.exit('没找到含 Msg_ 表的库，确认 --db 指向 decrypt_db.py 的输出')

    md5map = {hashlib.md5(u.encode()).hexdigest(): u for u in contacts}
    chats = {}
    for p in msg_dbs:
        con = sqlite3.connect(p)
        n2id = dict(con.execute("select rowid,user_name from Name2Id"))
        for u in n2id.values():
            md5map.setdefault(hashlib.md5(u.encode()).hexdigest(), u)
        tabs = [r[0] for r in con.execute("select name from sqlite_master where type='table' and name like 'Msg_%'")]
        for tb in tabs:
            user = md5map.get(tb[4:], tb[4:])
            try:
                rows = con.execute(
                    "select real_sender_id,create_time,local_type,message_content,compress_content "
                    "from %s order by create_time asc, local_id asc" % tb).fetchall()
            except sqlite3.Error as e:
                print('WARN %s: %s' % (tb, e), file=sys.stderr)
                continue
            bucket = chats.setdefault(user, [])
            for rsid, ct, lt, mc, cc in rows:
                text, sw = decode(lt, mc, cc, contacts)
                uid = sw or n2id.get(rsid, '')
                sname = contacts.get(uid, uid or '我')
                bucket.append({
                    't': datetime.datetime.fromtimestamp(ct).strftime('%Y-%m-%d %H:%M:%S') if ct else '',
                    's': sname,
                    'x': text,
                    'me': bool(me and uid == me),
                    'raw_type': lt,
                })
        con.close()

    out = a.out
    CH, TXT = os.path.join(out, 'chats'), os.path.join(out, 'chats_txt')
    os.makedirs(CH, exist_ok=True)
    os.makedirs(TXT, exist_ok=True)
    index = []
    for i, (user, msgs) in enumerate(sorted(chats.items(), key=lambda kv: -len(kv[1]))):
        if not msgs:
            continue
        title = contacts.get(user, user)
        safe = re.sub(r'[^\w\u4e00-\u9fff\-]+', '_', title)[:60] or str(i)
        body = ["<div class='bar'><a href='index.html'>← 返回会话列表</a><h1 style='margin:8px 0 0'>%s</h1>"
                "<div class='meta'>%d 条消息 · %s</div></div>" % (html.escape(title), len(msgs), html.escape(user))]
        for m in msgs:
            body.append("<div class='msg %s'><div class='s'>%s</div><div class='bub'>%s</div><div class='ts'>%s</div></div>"
                        % ('me' if m['me'] else '', html.escape(m['s']), html.escape(m['x']), html.escape(m['t'])))
        fn = '%s__%d.html' % (safe, i)
        open(os.path.join(CH, fn), 'w').write(page(title, ''.join(body)))
        with open(os.path.join(TXT, '%s__%d.txt' % (safe, i)), 'w') as f:
            f.write('== %s (%s) — %d 条 ==\n\n' % (title, user, len(msgs)))
            for m in msgs:
                f.write('[%s] %s: %s\n' % (m['t'], m['s'], m['x']))
        index.append((title, len(msgs), msgs[-1]['t'], user, fn))

    index.sort(key=lambda r: r[2], reverse=True)
    lis = ''.join("<a href='chats/%s'><span>%s</span><span class='meta'>%d 条 · %s</span></a>"
                  % (r[4], html.escape(r[0]), r[1], r[2][:16]) for r in index)
    open(os.path.join(out, 'index.html'), 'w').write(
        page('微信聊天记录', "<h1>微信聊天记录（%d 个会话）</h1><div class='list'>%s</div>" % (len(index), lis)))
    json.dump([{'user': u, 'title': contacts.get(u, u), 'msgs': m} for u, m in chats.items()],
              open(os.path.join(out, 'messages.json'), 'w'), ensure_ascii=False)

    total = sum(len(m) for m in chats.values())
    print('会话 %d，消息 %d' % (len(chats), total))
    print('输出: %s' % os.path.abspath(out))


if __name__ == '__main__':
    main()
