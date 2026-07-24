---
name: hermes-auto-text-extract
description: "Automated text extraction from a single game APK. Trigger by saying '开始获取文本任务'."
version: 1.2.0
author: Hermes Agent
platforms: [windows]
---

# Hermes 自动文本提取协议

用户输入 **"开始获取文本任务"** → 自动执行本流程。

## 边界情况
| 条件 | stdout | outputs/ |
|------|--------|----------|
| apks/ 为空 | "目前没有任务" | 不写入 |
| 成功 | "全部任务已完成" | 移入最终 CSV |
| 超时 | 报告超时 | 写入"解密失败" CSV |
| 解密失败 | 报错 | 写入"解密失败" CSV |

## 执行时间限制
- **硬上限：1 小时**，必须尽全力试满
- 超时由外部进程杀死，解密失败 CSV 由外部写入

## 目录约定
- APK 输入: `{{HERMES_ROOT}}\apks\`
- 工作区: `{{HERMES_ROOT}}\`
- 交付区: `{{HERMES_ROOT}}\outputs\`

## 工作流程
1. 扫描 `apks/` → 0个输出"目前没有任务"，1个进入处理
2. 解包: `work_dir = {{HERMES_ROOT}}\work_{jobid}`
3. 引擎识别 → 定位文本来源
4. IDA 分析 so，找解密逻辑
5. 提取文本 → 写入 CSV（末尾追加 `__SESSION_ID__: {session_id}`）
6. 移入 `outputs/` → 输出 "全部任务已完成"

## 相关技能
- `get-game-text` — 提取规则
- `aries-xxtea-binghuo` — XXTEA 解密
- `ida-pro-mcp` — IDA 分析
