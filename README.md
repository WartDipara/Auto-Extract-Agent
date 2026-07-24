# Hermes-Auto-Extract

监控 `inbox/` 目录，自动下载 APK 并通过 HermesAgent 进行逆向分析和中文文本提取。

## 部署

### 前置依赖

1. **Miniconda**
2. **HermesAgent** — 确保 `hermes` 命令在 PATH
3. **IDA Pro 9+** + **idalib**
4. **AssetStudio.CLI** / **Il2CppDumper**

### 安装

```powershell
# 修改 config/config.yaml 中的工具路径和 API provider
# 复制 config\.env.example 为 hermes-home\.env 并填入密钥
.\setup.ps1
.\launch.ps1
```

### 提交任务

将 JSON 放入 `inbox/`：

```json
{"get-texts": {"urls": ["https://example.com/game.apk"]}}
```

## 配置

`config/config.yaml` — 工具路径和 hermes 配置
`config/.env.example` — API key 模板
`config/skills-templates/` — 8 个 SKILL.md 模板