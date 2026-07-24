---
name: cocos2d-xxtea-key-discovery
description: "Discover XXTEA keys in cocos2d-x game binaries by reading adjacent .rodata strings."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [cocos2dx, xxtea, key-discovery, rodata, game-reversing]
    related_skills: [get-game-text, ida-pro-mcp, aries-xxtea-binghuo]
---

# cocos2d-x XXTEA Key Discovery via .rodata Adjacent Strings

## When to Use
cocos2d-x game with encrypted files, known sign/prefix, unknown key.

## Procedure
1. `find_regex(pattern="sign_string")` → locate sign in .rodata
2. `get_bytes(addr=sign-15, size=48)` → read adjacent bytes
3. Parse NUL-terminated strings, try concatenations before sign
4. Verify with standard XXTEA

## Known Keys
| Game | Sign | Key |
|------|------|-----|
| 仙剑奇传五 | "libai" (5B) | "dtou4guxiang" (11B) |

## The CZHelperFunc Pattern
`CZHelperFunc::getFileData` wrapper applies XXTEA. Key stored as adjacent .rodata NUL-terminated strings near sign.

## Pitfalls
- Key < 16 bytes auto zero-padded by cocos2d-x
- Sign length varies ("libai"=5B, "aries-wow-sign"=14B)
- Try combinations of 2-3 consecutive fragments
