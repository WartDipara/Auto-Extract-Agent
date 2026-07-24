---
name: il2cppdumper
description: "Dump C# class structures and strings from Unity IL2CPP binaries."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [unity, il2cpp, game-reversing, dump, metadata, reverse-engineering]
    related_skills: [assetstudio-cli, get-game-text]
---

# Il2CppDumper 使用指南

## 工具路径
`{{IL2CPP_PATH}}`

## 配置
`{{IL2CPP_CONFIG_PATH}}`

## 标准执行流程
```
Il2CppDumper.exe libil2cpp.so global-metadata.dat output
```

## 输出文件
| 文件 | 说明 |
|------|------|
| `dump.cs` | C# 类定义（字段、方法、属性、枚举等） |
| `stringliteral.json` | 所有字符串字面量地址和值 |
| `script.json` | 完整脚本元数据 |
| `DummyDll/` | 可反编译的 C# Dummy DLL 文件 |

## 关键应用场景

### 搜索加密密钥
在 `stringliteral.json` 或 `dump.cs` 中搜索：
```
Select-String -Pattern "key|encrypt|decrypt|xxtea|aes|password|secret" -Path dump.cs
```

### 定位文本/配置加载类
在 `dump.cs` 中搜索 `Translate`, `Localize`, `Language`, `ConfigManager`, `TableManager`, `CsvReader`。
