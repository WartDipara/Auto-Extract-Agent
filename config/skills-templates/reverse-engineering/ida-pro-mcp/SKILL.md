---
name: ida-pro-mcp
description: "Reverse engineer binaries via IDA Pro MCP tools (decompile, xref, patch, rename)."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [ida, reverse-engineering, decompilation, binary-analysis, mcp, idalib]
    related_skills: [get-game-text, il2cppdumper, assetstudio-cli]
---

# IDA Pro MCP 逆向分析

通过 idalib-mcp MCP 服务器连接 IDA Pro。在 HermesAgent 中已配置为自动启动。

## 核心工具
| 工具 | 说明 |
|------|------|
| `survey_binary()` | 二进制概览 |
| `decompile(addr)` | 反编译函数 |
| `analyze_function(addr)` | 紧凑分析 |
| `xrefs_to(addrs)` | 查交叉引用 |
| `trace_data_flow(addr, direction)` | 数据流追踪 |
| `rename(batch)` | 批量重命名 |
| `set_comments(items)` | 注释 |
| `patch_asm(items)` / `patch(patches)` | Patch |
| `get_bytes/string/int(..)` | 数据读取 |
| `find_bytes/find_regex(..)` | 搜索 |
| `int_convert(inputs)` | 数字格式转换 |
| `idb_open/list/save(..)` | 会话管理 |
| `make_signature_for_function(addrs)` | 创建签名 |

## 工作流
1. `survey_binary()` → 了解架构
2. `analyze_function()` / `decompile()` → 分析函数
3. `trace_data_flow()` → 数据流追踪
4. `rename()` + `set_comments()` → 标记

## 注意
- 每个工具必须带 `database` 参数
- `int_convert` 避免 LLM 手动算错进制
- `force_recompile()` 刷新反编译缓存
