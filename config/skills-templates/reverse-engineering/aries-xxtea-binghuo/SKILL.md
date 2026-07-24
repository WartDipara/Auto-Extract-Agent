---
name: aries-xxtea-binghuo
description: "Reverse Aries XXTEA used by 冰火游戏 cocos2dx-lua games. Decrypts .luac with 'aries-wow-sign' header."
version: 2.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [game-reversing, xxtea, aries, cocos2dx, binghuo, encryption]
    related_skills: [get-game-text, ida-pro-mcp]
---

# 冰火游戏 Aries 加密 (Standard XXTEA) 解密

## 特征
- `.luac` 文件头：`aries-wow-sign`（14 字节）
- `libcocos2dlua.so` 中有 `xxtea_decrypt`、`setXXTEAKeyAndSign`

## 算法：标准 XXTEA
| 常量 | 值 |
|------|-----|
| DELTA | `0x9E3779B9` |
| 轮数 | `6 + 52/n` |
| Key 长度 | 15 字节（zero-pad 到 16） |
| 已知 Key | `wowaries5102wow` |

## 找 Key 方法
1. **先试已知 key** `wowaries5102wow`（30 秒验证）
2. xrefs_to "aries-wow-sign" 定位 init 函数 → 看 std::string 构造
3. 批量验证：`scripts/aries_xxtea_bulk_verify.py`

## 批量验证脚本
`scripts/aries_xxtea_bulk_verify.py` — 扫描目录下所有 `.luac`
```python
ROOT = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else r"{{HERMES_ROOT}}/work/decoded/assets/res/data")
```

## 注意事项
- **不要信 IDA 反编译的 SSO std::string**，看汇编的 MOV 立即数
- header = 14 字节，不是 16
- **相关脚本**: `scripts/try_aries_key.py` — 单候选 key 暴力试解
- **参考资料**: `references/public-info-search-results.md`
