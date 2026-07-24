---
name: extract-game-text-csv
description: "Extract game text into a single-column texts.csv from reverse-engineered mobile game resources."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [game-reversing, text-extraction, chinese, csv, output-format]
    related: [get-game-text, ida-pro-mcp]
---

# Game Text Extraction → texts.csv 规范

## 输出文件
| 项目 | 要求 |
|------|------|
| 文件名 | `texts.csv`（硬性） |
| 编码 | utf-8-sig |
| 列数 | 1 列，表头 `text` |
| 包裹 | 不加引号，不转义 `"` 或 `,` |

```python
with open('texts.csv', 'w', encoding='utf-8-sig', newline='') as f:
    f.write('text\n')
    for s in texts:
        f.write(s + '\n')
```

## KEEP / SKIP
- **KEEP**: 富文本、占位符、UI标签、角色名、描述、对白、任务说明
- **SKIP**: 纯英文/数字、变量名、注释、代码、路径URL、屏蔽词、随机名库

过滤：含中文字符且占比 ≥ 20%，无代码关键字，无资源后缀，长度 ≥ 2。

## 字段级提取
配表结构 `tabLua={name={fields}, data={rows}}`：
- KEEP 字段名：`name`, `desc`, `title`, `dialogue`, `content`, `text`, `str`, `cn_name`, `cn_desc`, `tip` 等
- SKIP 字段名：`sid`, `id`, `type`, `order`, `icon`, `url`, `path`, `price`, `num` 等

## 相关技能
- `get-game-text` — 完整方法论
- `aries-xxtea-binghuo` — XXTEA 解密
- `ida-pro-mcp` / `il2cppdumper` / `assetstudio-cli`
