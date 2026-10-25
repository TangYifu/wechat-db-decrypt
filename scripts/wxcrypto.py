"""lldb 断点脚本：拦截 CCKeyDerivationPBKDF，抓 WeChat 4.x 数据库 passphrase。

用法（由 capture_key.sh 调用）:
  lldb -b -p PID -o "command script import .../wxcrypto.py" -o continue -o "process detach" -o quit

两类调用会命中：
  rounds=256000 → 入参是账号级 passphrase（要的就是这个）
  rounds=2      → 入参是单库派生密钥（每库不同，不能当账号 key 用），自动跳过
"""
import lldb

PRF_NAMES = {1: 'SHA1', 2: 'SHA256', 3: 'SHA384', 4: 'SHA512', 5: 'SHA512'}  # 5=kCCPRFHmacAlgSHA512
found = {'n': 0}


def _cb(frame, bp_loc, internal_dict):
    proc = frame.GetThread().GetProcess()
    x = [frame.FindRegister('x%d' % i).GetValueAsUnsigned() for i in range(7)]
    alg, pw_ptr, pw_len, salt_ptr, salt_len, prf, rounds = x
    if alg != 2:                # kCCPBKDF2
        return False
    err_pw, err_sa = lldb.SBError(), lldb.SBError()
    pw = proc.ReadMemory(pw_ptr, pw_len, err_pw) if 0 < pw_len <= 128 else None
    sa = proc.ReadMemory(salt_ptr, salt_len, err_sa) if 0 < salt_len <= 64 else None
    line = ("HIT alg=%d plen=%d slen=%d prf=%d rounds=%d pass=%s salt=%s"
            % (alg, pw_len, salt_len, prf, rounds,
               pw.hex() if pw else '-', sa.hex() if sa else '-'))
    print(line, flush=True)

    if rounds != 256000 or pw_len != 32:
        return False            # 派生密钥调用，继续跑
    found['n'] += 1
    print("DB_KEY %s" % pw.hex(), flush=True)
    return True                 # 命中账号 passphrase：停下，交给 lldb 后续 process detach


def __lldb_init_module(debugger, internal_dict):
    target = debugger.GetSelectedTarget()
    bp = target.BreakpointCreateByName('CCKeyDerivationPBKDF')
    if bp.GetNumLocations() == 0:
        print("WARN 未解析到 CCKeyDerivationPBKDF，请确认已 attach 到 WeChat 进程", flush=True)
    bp.SetScriptCallbackFunction('wxcrypto._cb')
    print("breakpoint installed: locations=%d" % bp.GetNumLocations(), flush=True)
