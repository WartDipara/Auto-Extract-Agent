# Hermes-Auto-Extract

监控 `inbox/` 目录，自动下载 APK 并通过 HermesAgent 进行逆向分析和中文文本提取。

## 架构

```
inbox/ → Hermes-Auto-Extract(python) → hermes chat -q "开始获取文本任务" → CSV
                         ↕                            ↕
                   config/config.yaml          hermes-home/config.yaml
                   config/skills-templates/    hermes-home/skills/
```

严格黑盒契约：
- **外部调用方** = 一份固定的 `hermes chat -q "开始获取文本任务" -v` + 等 CSV
- **Hermes** = 收到指令后自行完成解密、提取、写入 CSV
- 两者之间不传递模型名、provider、skill 等内部参数

## 部署

### 前置依赖

1. **Miniconda**
2. **HermesAgent** — 确保 `hermes` 命令在 PATH
3. **IDA Pro 9+** + **idalib**
4. **AssetStudio.CLI** / **Il2CppDumper**

### 首次安装

```powershell
# 1. 编辑 config/config.yaml — 设置模型、provider、工具路径
# 2. 复制 config/.env.example 为 hermes-home/.env 并填入 API keys
.\setup.ps1
.\launch.ps1
```

### 修改配置后同步

```powershell
.\sync.ps1          # 将 config/config.yaml + skill 模板写入 hermes-home/
```

**不需要打开 Hermes GUI** — `hermes-home/` 就是普通文件目录，编辑后下次运行自动生效。

### 提交任务

将 JSON 放入 `inbox/`：

```json
{"get-texts": {"urls": ["https://example.com/game.apk"]}}
```

## 配置 Hermes 的 AI 和 Skills（无需 GUI）

### 改模型 / Provider

编辑 `config/config.yaml`，然后运行 `.\sync.ps1` 写入 `hermes-home/config.yaml`：

```yaml
model:
  default: deepseek-v4-flash     # 换成任意模型
  provider: custom:ai.14x.cn     # 换成任意 provider
```

Hermes 启动时从 `hermes-home/config.yaml` 读取（因为 `HERMES_HOME` 指向那里），无需 GUI、无需重启服务。

也可以用 `hermes config set` 直接改 `hermes-home/config.yaml`：
```powershell
$env:HERMES_HOME = "$PWD\hermes-home"
hermes config set model.default deepseek-v4-flash
```

### 改 Skills

Skill 就是 `hermes-home/skills/` 目录下的文件夹 + `SKILL.md` 文件：

- **从模板同步**：编辑 `config/skills-templates/` → 运行 `.\sync.ps1`
- **直接编辑**：修改 `hermes-home/skills/` 下的文件，下次 hermes 调用自动生效
- **安装新 skill**：`hermes skills install <url>` 或在 `hermes-home/skills/` 下新建目录

### 改 Provider API Key

编辑 `hermes-home/.env`（由 `setup.ps1` 从 `config/.env.example` 生成）。

## 目录结构

```
Hermes-Auto-Extract/
├── config/
│   ├── config.yaml            ← 编辑这里改模型/provider
│   ├── .env.example
│   └── skills-templates/      ← 编辑这里改 skill
├── hermes-home/               ← Hermes 运行时工作区
│   ├── config.yaml            ← sync.ps1 从 config/ 同步
│   ├── skills/                ← sync.ps1 从 templates/ 渲染
│   ├── .env                   ← API keys
│   ├── apks/                  ← 当前任务的 APK
│   └── outputs/               ← 输出的 CSV
├── inbox/                     ← 放入 JSON 触发任务
├── downloads/                 ← 下载的 APK
├── result/                    ← 最终归档 CSV
├── logs/                      ← 每任务日志
├── state/                     ← 队列状态
├── src/                       ← Python 管线代码
├── setup.ps1                  ← 首次安装（含 conda env）
├── sync.ps1                   ← 轻量同步（配置+技能）
└── launch.ps1                 ← 启动服务
```
