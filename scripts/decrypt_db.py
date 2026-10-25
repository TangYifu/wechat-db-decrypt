#!/usr/bin/env python3
"""解密 WeChat 4.x (macOS/Windows) 的 SQLCipher4 数据库。

格式（实测 WeChat 4.1.15）:
  页 4096, reserve 80 = IV(16) + HMAC-SHA512(64)
  页 1  : [salt 16][密文 4000][IV 16][HMAC 64]
  页 N  : [密文 4016][IV 16][HMAC 64]
  enc_key = PBKDF2-HMAC-SHA512(pass32, salt, 256000, 32)
  mac_key = PBKDF2-HMAC-SHA512(enc_key, salt^0x3a, 2, 32)

用法:
  decrypt_db.py --src <db_storage目录|单个.db> --out <输出目录> --key <64位hex>
"""
import argparse, hashlib, hmac, os, shutil, sqlite3, struct, sys

PS, RESERVE, IVSZ, HMACSZ, SALT = 4096, 80, 16, 64, 16
HDR = b'SQLite format 3\x00'

try:
    from Crypto.Cipher import AES
except ImportError:
    sys.exit('需要 pycryptodome:  pip install pycryptodome')


def derive(pw, salt, rounds):
    return hashlib.pbkdf2_hmac('sha512', pw, salt, rounds, 32)


def verify_page1(data, pass32):
    """返回 (ok, enc_key, reason)"""
    if len(data) < PS:
        return False, None, 'file too small'
    salt = data[:SALT]
    enc = derive(pass32, salt, 256000)
    mac_salt = bytes(b ^ 0x3A for b in salt)
    mac_key = derive(enc, mac_salt, 2)
    ctext = data[SALT:PS - RESERVE]
    iv = data[PS - RESERVE:PS - RESERVE + IVSZ]
    stored = data[PS - HMACSZ:PS]
    d = hmac.new(mac_key, data[SALT:PS - HMACSZ], hashlib.sha512)
    d.update(struct.pack('<I', 1))
    if d.digest() != stored:
        return False, enc, 'hmac mismatch'
    pt = AES.new(enc, AES.MODE_CBC, iv).decrypt(ctext)
    # 页 1 的 salt 占了明文头 16 字节的位置，所以解出来从 header 第 16 字节开始：
    # 前两字节应是页大小 0x1000 的大端表示。
    good = pt[:2] == b'\x10\x00'
    return good, enc, 'ok' if good else 'bad page1 (page_size=%02x%02x)' % (pt[0], pt[1])


def decrypt_file(path, out_path, pass32):
    data = open(path, 'rb').read()
    ok, key, why = verify_page1(data, pass32)
    if not ok:
        return False, why
    pages = []
    for i in range(0, len(data) - PS + 1, PS):
        ch = data[i:i + PS]
        iv = ch[PS - RESERVE:PS - RESERVE + IVSZ]
        if i == 0:
            pt = HDR + AES.new(key, AES.MODE_CBC, iv).decrypt(ch[SALT:PS - RESERVE])
        else:
            pt = AES.new(key, AES.MODE_CBC, iv).decrypt(ch[:PS - RESERVE])
        pages.append(pt + b'\x00' * RESERVE)
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    with open(out_path, 'wb') as f:
        f.write(b''.join(pages))
    return True, 'ok'


def integrity(path):
    try:
        con = sqlite3.connect('file:%s?mode=ro' % path, uri=True)
        r = con.execute('pragma integrity_check').fetchone()[0]
        con.close()
        return r
    except Exception as e:
        return 'error: %s' % e


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True, help='db_storage 目录或单个 .db 文件')
    ap.add_argument('--out', required=True)
    ap.add_argument('--key', required=True, help='passphrase 的 64 位 hex（32 字节）')
    ap.add_argument('--flat', action='store_true', help='输出扁平文件名（默认保留子目录）')
    a = ap.parse_args()
    pass32 = bytes.fromhex(a.key.strip())
    if len(pass32) != 32:
        sys.exit('key 必须是 32 字节（64 位 hex），当前 %d 字节' % len(pass32))

    files = []
    if os.path.isdir(a.src):
        for root, _, fs in os.walk(a.src):
            files += [os.path.join(root, f) for f in fs if f.endswith('.db')]
    else:
        files = [a.src]
    files.sort()
    if not files:
        sys.exit('没找到 .db 文件')

    ok = bad = 0
    for p in files:
        rel = os.path.relpath(p, a.src if os.path.isdir(a.src) else os.path.dirname(p))
        out = os.path.join(a.out, rel.replace('/', '__') if a.flat else rel)
        good, why = decrypt_file(p, out, pass32)
        if good:
            ic = integrity(out)
            status = 'PASS' if ic == 'ok' else 'CHECK=%s' % ic
            ok += 1
            print('OK   %-40s %-12s %s' % (rel, status, os.path.getsize(out)))
        else:
            bad += 1
            print('FAIL %-40s %s' % (rel, why))
    print('\n解密成功 %d，失败 %d' % (ok, bad))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
