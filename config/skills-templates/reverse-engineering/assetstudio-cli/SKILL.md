---
name: assetstudio-cli
description: "Extract resources (TextAsset, Texture2D, etc.) from Unity AssetBundle files."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [unity, assetbundle, game-reversing, resource-extraction, assetstudio]
    related_skills: [il2cppdumper, get-game-text]
---

# AssetStudio.CLI 使用指南

## 工具路径
`{{ASSETSTUDIO_PATH}}`

## 基本用法
```
AssetStudio.CLI <input_path> <output_path> [options]
```

## 常用参数

| 参数 | 说明 |
|------|------|
| `--types <type>` | 指定导出的资源类型。常用：`TextAsset`, `Texture2D`, `Sprite`, `MonoBehaviour` |
| `--export_type Convert` | 转换导出为可读格式（TextAsset 导出为 .txt） |
| `--export_type Raw` | 原始二进制导出 |
| `--group_assets ByContainer` | 按原始资源路径分组导出 |
| `--group_assets ByType` | 按类型分组导出 |
| `--game Normal` | 游戏类型，标准 Unity 游戏用 `Normal` |
| `--unity_version <ver>` | 指定 Unity 版本 |
| `--containers <regex>` | 按容器路径正则过滤 |
| `--names <regex>` | 按资源名称正则过滤 |
| `--silent` | 静默模式 |

## 典型场景
```
AssetStudio.CLI input.bundle output_dir --types TextAsset --export_type Convert --group_assets ByContainer --game Normal
AssetStudio.CLI bundles_dir/ output_dir --types TextAsset --export_type Convert --group_assets ByContainer --game Normal
AssetStudio.CLI input.bundle output_dir --game GenshinImpact --key_index 0
```
