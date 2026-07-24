---
name: get-game-text
description: "Extract Chinese game text from reverse-engineered resources (Unity/UE/cocos2d). Includes engine identification, encryption detection, IDA-based key discovery, and text extraction strategies."
version: 2.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [game-reversing, text-extraction, chinese, i18n, localization, reverse-engineering]
    related_skills: [assetstudio-cli, il2cppdumper, ida-pro-mcp, extract-game-text-csv]
---

# 游戏中文文本提取 - 通用方法论

IDA 分析操作（搜索字符串、反编译、交叉引用、查找密钥等）请使用 `idalib` MCP 工具集，参考 `ida-pro-mcp` 技能。

## 1. 核心原则

- **只处理大量文本出现的地方**：配置表（lua/csv/xml/json）、Translate表、StringConstants、Name生成库等。
- **忽略功能代码中的零散中文**：debug print、代码注释、UI工具标签、埋点统计、音效注释等非玩家文本。
- **只提取中文文本**：多语言游戏中，只关注 Zh_CN 字段或包含大量中文字符（\\u4e00-\\u9fff）的字符串。
- **不处理屏蔽词/ForbiddenName**：这类文件直接跳过。
- **最终输出必须是纯文本CSV**：单列，无引号包裹，无转义，无额外列（如key、sourcefile）。
- **不处理X7相关的部分**：X7是我们自己注入的插件。libtranslator_plugin.so、libspeedup_tool.so、libx7NativeEncrypt.so 等插件都是我们注入的，assets中 translator_conf、plugin-manager、plugin-release.zip 也是，忽略它们。
- **不处理随机名库或者注释**：如果确认为文件内容为随机名以及注释，则可以直接跳过，鉴定为垃圾文本，不加入最后的csv。

## 2. 游戏引擎识别与文本存储位置

### 2.1 引擎快速判断

通过解包后的目录结构判断引擎类型：

| 引擎 | 典型目录结构 | 文本常见位置 |
|------|------------|------------|
| **cocos2dx-lua** | `assets/` + `res/` + `smali/`，大量 `.luac`/`.lua` | `script/config/Translate_*.lua`, `script/config/*.lua`（CN_Name/Name/Desc字段）, `script/snk/assets/StringConstants.lua` |
| **cocos2dx（加密资源）** | `assets/data/` 下大量 `.nice`/`.dat`/无扩展名文件，文件名常为 MD5 哈希 | 解密后通常是 Lua 配表、PNG、JSON、XML 等，文本在 csv2lua 生成的 `csv['xxx']` 配置表中 |
| **Unity3d** | `assets/bin/Data/`，`.dll`/`.so`, `Managed/Assembly-CSharp.dll` | `resources.assets`中的MonoBehaviour/TextAsset, `StreamingAssets/` 中的 `.json`/`.csv`/`.bytes`, `il2cpp` 情况需找 `global-metadata.dat` |
| **Unity3d + ToLua** | `assets/` 下有 `.bin`/`.lua` 文件，`libtolua.so` 或 `Assembly-CSharp.dll` 中有 `lua_State` 相关符号 | LuaJIT 字节码 `.bin`（需反编译），反编译后在 `data/syslang_*_cn.lua` 等配置表中 |
| **UE4/UE5** | `assets/` 中 `.pak`/`.ucas`/`.utoc` | `.pak` 解压后的 `.locres`/`.locmeta`, `Content/Localization/` 目录 |
| **自研引擎** | 不规律，常见 `.db`/`.dat`/`.bin`/`.ab` | 需通过文件头（magic bytes）和字符串搜索定位 |

### 2.2 关键发现路径

1. **先找 Translate/Localization 表**：绝大多数商业游戏都有集中的多语言表，文件名通常含 `Translate`, `Localization`, `Lang`, `StringTable`, `TextData`。
2. **再找配置表**：`Item`, `Skill`, `Hero`, `Stage`, `Quest`, `Achievement` 等配置中常有 `CN_Name`, `Name`, `Desc`, `Title` 等中文字段。
3. **字符串常量文件**：`StringConstants`, `GameStrings`, `UIStrings`, `TipStrings` 等硬编码UI文本。
4. **随机名/称号库**：`NameFirst`, `NameLast`, `TitleLib`, `Nickname` 等玩家自定义名称的素材库。

## 3. 加密检测与解密

### 3.1 如何判断文本是否加密

- **直接搜索中文字符**：用 `grep -r` 或 Python 在解包后的资源中搜索 `[\\u4e00-\\u9fff]`。如果完全搜不到或搜出来是乱码，说明加密或压缩。
- **检查文件头**：正常文本文件（UTF-8）以 `EF BB BF`（BOM）或纯文本开头；加密文件通常以随机字节开头。
- **检查已知格式**：`.luac` 应以 `1B 4C 4A`（LuaJIT）或 `1B 4C 75`（Lua 5.x）开头；`.json` 以 `{` 或 `[` 开头；`.csv` 以可读文本开头。

### 3.2 在 IDA 中寻找解密手段

当发现资源文件被加密/混淆时，按以下思路在 IDA 中定位解密逻辑：

1. **定位文件读取函数**：搜索 `fopen`, `AssetManager::get`, `FileUtils::getData`, `Resources::Load` 等文件 IO 相关 API 的引用。
2. **跟踪数据流**：从文件读取点出发，向上/向下跟踪哪个函数对读取到的字节流做了变换（XOR、AES、zlib、自定义算法）。
3. **寻找密钥特征**：
   - 搜索代码中硬编码的字符串常量（Shift+F12），关键词如 `"AES"`, `"DES"`, `"rc4"`, `"xor"`, `"key"`。
   - 关注函数中连续出现的 16/24/32 字节数组（可能是 AES 密钥）。
   - 关注函数中出现固定魔数（如 `0x789C` 是 zlib，`0x04034b50` 是 ZIP）前的变换逻辑。
   - **搜索全局变量**：用 IDA 搜索所有可能的密钥变量。如果找到多个同名/相似名变量，必须逐一检查 `size` 和数据内容。
   - **检查数据内容**：获取变量原始字节，观察是否有异常模式。真正的随机密钥不会出现连续递增/递减序列（如 `E0 E1 E2 E3`）。
   - **确认数据格式**：C++ 中 `static const int hash_bits[]` 编译后可能变成 uint32 数组（每个值占 4 字节），需按每 4 字节取低字节还原为实际密钥。
4. **常见加密模式**：
   - **简单 XOR**：固定单字节/多字节密钥与文件内容异或。IDA 中表现为循环中反复出现的 `xor eax, imm8/imm32`。
   - **AES/RC4**：通常调用了 OpenSSL、mbedtls 或自实现算法。IDA 中搜索 `AES_set_decrypt_key`, `RC4` 等符号。
   - **XXTEA**：常见于cocos2dx游戏（脚本加密）。标准版特征是有固定魔数 `0x9E3779B9` 出现在循环中。注意修改版：有些游戏会修改 DELTA 常量（如改为 `0x12345678`），此时标准 XXTEA 库无法解密，需从 IDA 中提取实际 DELTA 值。
   - **文件名派生密钥**：某些游戏不直接使用硬编码密钥，而是用 `MD5(文件名)` 或 `文件名前 N 字符` 派生密钥。需要从 `FileUtils::getData` 的调用链中跟踪密钥派生逻辑。
   - **zlib/gzip**：解密后接解压。寻找 `inflate`, `uncompress` 调用。
5. **验证候选密钥（关键！）**：
   - 用候选密钥解密**多种长度**的文本。短文本可能只用到密钥前半部分，长文本（如道具描述、技能说明）才能暴露密钥后半部分的错误。
   - 确认解密索引：`BasicDecrypt` 函数中通常为 `i % key_len`，需反编译确认不是硬编码的 `i % 16`。
   - 如果部分表解密正确、部分表出现乱码，**不要假设数据格式问题**，首先怀疑密钥不完整或索引错误。
6. **动态调试验证**：在怀疑的解密函数处下断点，运行游戏加载资源时观察内存中的数据变化，确认解密前后的字节流。

### 3.3 解密后的处理

解密后可能得到：
- 明文 Lua/CSharp/JSON/CSV/XML — 直接解析。
- 明文二进制 + 自定义结构 — 需要分析结构（字段长度 + 字段值）。
- Unity AssetBundle — 用 AssetStudio / UABE 等工具提取 TextAsset。
- 压缩包（zip/pak）— 解压后继续分析内部文件。

## 4. 文本提取策略

### 4.1 按文件类型选择提取器

| 文件类型 | 提取目标 | 方法 |
|---------|---------|------|
| **Translate_*.lua** | `Zh_CN` 字段 | 逐条匹配 `Key = { Id="...", Zh_CN="...", ... }` 结构 |
| **配置 Lua（Item/Hero 等）** | `CN_Name`, `Name`, `Desc`, `Title` 等 | 正则匹配 `FieldName = "..."` |
| **LuaJIT 反编译后的配置表** | `syslang_*_cn.lua` 中的 desc/name/dialogue 等 | 解析 `fieldNames` 和 `dataStrs` 结构，按字段名关键词提取 |
| **Unity TextAsset** | `resources.assets` 中提取出的 `.txt`/`.csv`/`.json` | 用 AssetStudio 提取后按对应格式解析 |
| **StringConstants.lua** | 所有 `Contents.XXX = "..."` 中的中文字符串 | 全局匹配 `= "..."` 并筛选含中文的 |
| **随机名库** | `NameFirst`, `NameLast` 字段 | 正则匹配对应字段 |
| **CSV/JSON/XML** | 中文列/字段 | 用标准库解析后提取目标列 |
| **C# DLL (Unity)** | 硬编码字符串 | 用 dnSpy/ILSpy 反编译后搜索中文字符串常量 |

### 4.2 过滤规则

以下内容的文件/条目**必须跳过**：
- `ForbiddenName*`, `屏蔽词*`, `BanWord*` 等屏蔽词库。
- 文件名含 `debug/`, `statistic/`, `test/` 的调试/统计代码。
- 音效/动画备注（如"点击音效（废弃）"）。

**中文阈值**：只需 **2 个以上**中文字符（U+4E00-U+9FFF）即应纳入。很多有价值文本是短词：`关羽`、`一贫`、`伤害+`、`%d元宝`、`VIP礼包`、`100%反击`，不能因过严过滤而漏掉。

## 5. CSV 输出规范

详见 `extract-game-text-csv` 技能。

## 6. 快速决策流程

```
1. 解包 APK/IPA → 观察目录结构 → 判断引擎类型
2. 全局搜索中文 [\\u4e00-\\u9fff]
   ├─ 能搜到大量明文 → 直接进入提取阶段
   └─ 搜不到或乱码 → 进入加密分析阶段
3. 加密分析
   ├─ 检查文件头 magic bytes
   ├─ IDA 定位文件读取 → 跟踪解密函数 → 提取密钥/算法
   └─ 解密后回到步骤2
4. 定位文本集中文件
   ├─ 找 Translate/Localization 表
   ├─ 找配置表（Item, Hero, Skill 等）
   ├─ 找 StringConstants
   └─ 找 Name 生成库
5. 按文件类型选用提取器 → 过滤代码垃圾 → 去重
6. 写入 CSV（utf-8-sig, 单列, 无引号转义）
```

## 7. 运行环境要求

IDA 分析操作（反编译、搜索、xref 等）通过 idalib MCP 工具完成，无需手动操作 IDA GUI。详见 `ida-pro-mcp` 技能。

Python 解密脚本在 `agent-ida` conda 环境中运行：

```powershell
conda activate agent-ida
python decrypt_script.py
```

## 相关技能

- `extract-game-text-csv` — CSV 输出规范与字段级提取策略
- `ida-pro-mcp` — IDA Pro MCP 工具用法
- `aries-xxtea-binghuo` — XXTEA 解密参考
- `cocos2d-xxtea-key-discovery` — XXTEA 密钥发现方法论
- `hermes-auto-text-extract` — 自动文本提取主流程
