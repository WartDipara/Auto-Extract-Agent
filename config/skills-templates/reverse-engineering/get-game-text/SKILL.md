---
name: get-game-text
description: "Extract Chinese game text from reverse-engineered resources (Unity/UE/cocos2d)."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [game-reversing, text-extraction, chinese, i18n, localization, reverse-engineering]
    related_skills: [assetstudio-cli, il2cppdumper, ida-pro-mcp]
---

# 游戏中文文本提取 - 通用方法论

IDA 分析操作使用 `idalib` MCP 工具集，参考 `ida-pro-mcp` 技能。

## 核心原则
- 只处理大量文本出现的地方（配置表、Translate表、StringConstants）
- 忽略功能代码中的零散中文（debug print、注释、UI标签）
- 只提取中文文本，过滤屏蔽词/随机名库
- 最终输出为纯文本CSV（单列，无引号包裹）

## 引擎识别
| 引擎 | 文本位置 |
|------|---------|
| cocos2dx-lua | `script/config/Translate_*.lua`, `StringConstants.lua` |
| Unity3d | `resources.assets` MonoBehaviour/TextAsset, `StreamingAssets/` |
| Unity IL2CPP | `global-metadata.dat` → Il2CppDumper |
| UE4/UE5 | `.pak` → `.locres`/`Content/Localization/` |

## 加密分析
- 搜索中文字符 `[\u4e00-\u9fff]`，无结果→加密
- IDA 定位文件读取 → 跟踪解密函数 → 提取密钥
- 常见加密：XOR、XXTEA（0x9E3779B9）、AES、RC4

## CSV 输出
```python
with open('output.csv', 'w', encoding='utf-8-sig') as f:
    f.write('text\n')
    for text in texts:
        f.write(text.replace('\r',' ').replace('\n',' ').replace('\t',' ') + '\n')
```

## 运行环境
IDA 操作通过 idalib MCP。Python 解密脚本在 `agent-ida` conda 环境运行。
