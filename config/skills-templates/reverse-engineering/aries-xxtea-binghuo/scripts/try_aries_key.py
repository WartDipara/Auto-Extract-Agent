#!/usr/bin/env python3
"""
试解 Aries-wow-sign 加密的 .luac 文件，用一个候选 16 字节 key。
如果 KEY_HEX 正确，会在 stdout 打印 'KEY OK: N/N'。
用法:
    python3 try_aries_key.py <KEY_HEX> <APK_ROOT/assets/res/data>

依赖：标准库；可直接 import SKILL.md 里的 xxtea_decrypt_real 函数体。

退出码:
    0  = 全部文件解密成功
    1  = 部分失败（key 错误或部分文件非加密）
    2  = 用法错误
"""

import sys
import pathlib

DELTA_STRIDE = 0x61C88647
SUM_INIT = 0xB54CDA56


def xxtea_decrypt(src: bytes, key: bytes):
    n = (len(src) + 3) // 4
    if n < 2:
        return None
    # pack src into u32
    v = [0] * n
    for j, b in enumerate(src):
        v[j >> 2] |= b << ((8 * j) & 0x18)
    v = [x & 0xFFFFFFFF for x in v]
    # pack key into u32
    k = [0] * 4
    for i in range(16):
        b = key[i] if i < len(key) else 0
        k[i >> 2] |= b << ((8 * i) & 0x18)
    k = [x & 0xFFFFFFFF for x in k]
    rounds = 52 // n
    s = (rounds * 0x9E3779B9 + SUM_INIT) & 0xFFFFFFFF
    if s == 0:
        return None
    last = n - 1
    v11 = v[0]
    while True:
        v12 = (s >> 2) & 3
        prev = v[last]
        for x in range(last, 0, -1):
            w17 = v[x - 1]
            v11 ^= s
            t = (k[(x & 3) ^ v12] ^ w17) + v11
            t2 = ((w17 >> 5) ^ ((v11 << 2) & 0xFFFFFFFF)) + (((w17 << 4) & 0xFFFFFFFF) ^ (v11 >> 3))
            prev = v[x] = (v[x] - (t ^ t2)) & 0xFFFFFFFF
            v11 = prev
        v11 ^= s
        t = (k[v12] ^ prev) + v11
        t2 = ((prev >> 5) ^ ((v11 << 2) & 0xFFFFFFFF)) + (((prev << 4) & 0xFFFFFFFF) ^ (v11 >> 3))
        v[0] = (v[0] - (t ^ t2)) & 0xFFFFFFFF
        v11 = v[0]
        s = (s + DELTA_STRIDE) & 0xFFFFFFFF
        if s == 0:
            break
    out_len = v[last]
    if not (4 * n - 7 <= out_len <= 4 * n - 4):
        return None
    out = bytearray(out_len)
    for i in range(out_len):
        out[i] = (v[i >> 2] >> ((8 * i) & 0x18)) & 0xFF
    return bytes(out)


def main():
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <KEY_HEX> <DATA_DIR>", file=sys.stderr)
        return 2
    try:
        key = bytes.fromhex(sys.argv[1])
    except ValueError:
        print(f"KEY_HEX not valid hex: {sys.argv[1]}", file=sys.stderr)
        return 2
    if len(key) != 16:
        print(f"key must be 16 bytes (32 hex chars), got {len(key)}", file=sys.stderr)
        return 2

    root = pathlib.Path(sys.argv[2])
    if not root.is_dir():
        print(f"DATA_DIR not found: {root}", file=sys.stderr)
        return 2

    ok = 0
    total = 0
    failures = []
    for p in sorted(root.rglob("*.luac")):
        total += 1
        raw = p.read_bytes()
        if not raw.startswith(b"aries-wow-sign\\"):
            continue
        pt = xxtea_decrypt(raw[14:], key)
        if pt is None:
            failures.append((p, "xxtea returned None"))
            continue
        # check valid output
        head_ok = (
            pt[:4] in (b"\x1b\x4c\x4a", b"\x1bLua")
            or pt[:3] == b"\xef\xbb\xbf"
            or pt[:4] in (b"retu", b"loca", b"func", b"--")
        )
        if head_ok:
            ok += 1
        else:
            failures.append((p, f"bad head: {pt[:8].hex()}"))

    print(f"KEY_OK {ok}/{total}")
    if failures:
        print(f"failures: {len(failures)}", file=sys.stderr)
        for p, why in failures[:5]:
            print(f"  {p.name}: {why}", file=sys.stderr)
    return 0 if (total > 0 and ok == total) else 1


if __name__ == "__main__":
    sys.exit(main())