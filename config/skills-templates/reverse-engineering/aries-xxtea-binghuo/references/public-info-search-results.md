# 公开信息检索结果：冰火游戏 / Aries 加密 / X7 渠道

> 此文件记录的是**已经做过的失败检索**和**已验证的密钥**，目的是让后续 session 直接复用、不浪费时间。

## 结论先行

**`aries-wow-sign` 这个字符串在公网上零公开记录**。所有搜索引擎、GitHub 仓库搜索、API 调用都没有命中任何"公开密钥"或"默认 key"。冰火游戏 SDK + X7 渠道的 Aries 加密属于**封闭商业 SDK**，密钥在每个 APK 里都不同，硬编码在 `libcocos2dlua.so` 的 init 函数中（通过 std::string operator+ 拼接）。

## 已验证可用的 key（多版本共用，2026-07-23 验证）

| Key | 长度 | 验证样本 | 备注 |
|---|---|---|---|
| `wowaries5102wow` | 15 字节 | 16976_5_2-4-1 冰火 X7 APK (1500/1502 解密成功) | **最常用**，先试这个 |
| `wowaries2015wow` | 15 字节 | 历史变体（未在本批次验证） | 数字部分可能变化 |

**Key 构造模式**（在 `libcocos2dlua.so` 的 init 函数中通过 std::string 拼接）：
```c
"wow" + "aries" + "<4位数字>" + "wow"
```

变体：4位数字可能是 `5102` / `2015` / 其他年份/日期。

## 已验证 0 命中的检索

### GitHub 仓库搜索（`api.github.com/search/repositories`）

| 查询关键词 | total_count | 备注 |
|---|---|---|
| `aries-wow-sign` | 0 | — |
| `aries-wow-sign xxtea` | 0 | — |
| `xxtea-wow-sign` | 0 | — |
| `brgame` | 0 | — |
| `libbrgame` | 0 | — |
| `brplug` | 0 | — |
| `com.binghuo` | 0 | — |
| `com.brplug.brgame` | 0 | — |
| `cocos2dx aries decrypt` | 0 | — |
| `cocos2dx+xxtea+key` | 0 | — |
| `xxtea+key+apk+lua+game` | 0 | — |
| `setXXTEAKeyAndSign` | 0 | — |
| `cocos+xxtea+lua+%E5%8A%A0%E5%AF%86` | 0 | — |
| `cocos2d+xxtea+%E5%8A%A0%E5%AF%86` | 1 (`mengtest/cocos2dx_xxtea_asset` — 通用工具，无密钥) | — |

**注意**：GitHub API 在 IP `14.136.16.66` 上**会触发 rate limit**，持续时间数十分钟 → 后续调用返回 `{"message": "API rate limit exceeded for 14.136.16.66"}`。看到这个错误就不要再调，等或换 IP。

### GitHub 代码搜索（`api.github.com/search/code`）

全部 401：搜索 code 端点需要认证 token，未认证 IP 直接拒。

### 搜索引擎结果（0 相关命中）

- **Bing** `site:52pojie.cn "aries-wow-sign"`：返回的是 Bing 自己的搜索结果页面，无内容
- **Bing** `"aries-wow-sign" xxtea`：返回的全是 Word 文档教程、Daum 韩文门户、抖音问答 — 完全无相关
- **Bing** `cocos2dx aries 加密 xxtea`：返回 cocos2dx 官网/GitHub/CSDN 入门教程，无 aries 加密具体内容
- **Bing** `"冰火游戏" SDK lua xxtea`：返回 Daum 韩国门户（完全无关）
- **Bing** `cdqj aemyzg`：返回 Zalo 越南聊天工具（完全无关）
- **DuckDuckGo HTML** `?q="aries-wow-sign"`：返回空 HTML（限流）
- **searx.be** `?q="aries-wow-sign" xxtea&format=json`：403 Forbidden
- **52pojie** 站内搜索：跳转到 Bing 自身结果
- **CSDN** `so.csdn.net/so/search?q=cdqj`：JS 渲染，无服务端结果

## 找到的有用资源（无密钥但相关）

| 仓库 | 用途 |
|---|---|
| `jujuo0/COCOS2dx-LUAC-Decryptor` | Frida hook `xxtea_decrypt` 自动批量解密 .luac，需用户提供 key/sign |
| `chrisli-03/cocos2dx-game-reverse-engineer` | Frida hook `luaL_loadbuffer` 从内存截获解密后的 lua，**不需要 key**（首选方案） |
| `2666fff/xxtea_decryptor` | 通用 XXTEA 加解密工具（C# WinForms，配置 sign/header/key） |
| `mengtest/cocos2dx_xxtea_asset` | XXTEA 命令行工具 + shell 脚本（默认密钥示例 `-s xxtea -k 123456`） |

## 其他候选密钥列表（如果已知 key 失败，按概率排序）

经验：冰火/X7 渠道 SDK 的 key 是 15 字节 ASCII 字符串，**通常就是 SDK 名字或包名**。建议从这些候选开始试：

| 候选密钥 | ASCII | 备注 |
|---|---|---|
| `cocos2d-x` | `cocos2d-x...` | cocos 默认值 |
| `cdqj` | `cdqj...` | 包名首字母（不推荐——太短） |
| `x7sy` | `x7sy...` | 渠道标识 |
| `com.aemyzg` | `com.aemyzg...` | 包名前缀 |
| `aemyzg_cdqj` | `aemyzg_cdqj...` | 包名拼写 |
| `BinghuoGame` | `BinghuoGame...` | SDK 厂商名（部分版本） |
| `BingHuoGameSdk` | `BingHuoGameSdk` | 完整 SDK 名（部分版本） |
| `smwl_smsdk` | `smwl_smsdk...` | X7 渠道容器（部分版本） |

每个候选配合 SKILL.md 的"批量试解验证"脚本，5 分钟可扫完。

## 16976_5_2-4-1 样本的关键静态事实（供下次直接复用）

如果下次用户再拿 `16976_5_2-4-1*.apk` 这种格式的 APK：

- 嵌入 `assets/plugin-release.zip`，含 `appPlugin-plugin-release.apk`（200MB+，**不是游戏内容**）
- 真正的游戏逻辑在外层 APK 的 `assets/res/data/*.luac`（**1502 个文件**，全是 14 字节 `aries-wow-sign` 头，跳过 Name.luac/Sensitive.luac 解密 1500 个）
- 外层 `lib/arm64-v8a/libbrgame.so` 含 `F3AES` + base64 字母表 + `Password decrypt fail.`——这是给**非 Lua 资源**（图片、atlas、json）加密的，与 .luac 的 key 无关
- 外层 `lib/arm64-v8a/libcocos2dlua.so` 含 `xxtea_decrypt`、`setXXTEAKeyAndSign`、`cleanupXXTEAKeyAndSign` 三个导出符号——这是 .luac 解密用的
- **Key 构造在 `sub_8D82A8`**（init 函数）——通过 std::string operator+ 拼接 `wow + aries + 5102 + wow`
- `assets/x7PluginConfig.properties`：`rhVersion=2, x7VersionForCN=8.48.0, sdkChannel=0, qyVersion=2, wxVersion=8, x7LatestVersion=8.74.0`
- `assets/brsdk_channel.json`：含 `XQPublicKey`（RSA 公钥）和 `XQAppKey`（32 字符 hex）——这两个**不是** Lua XXTEA key，是 X7 平台协议用

## 上层 APK aapt 看包名时常被误导

`aapt dump badging appPlugin-plugin-release.apk` 会显示 `com.smwl.smsdk.plugin`——这是 X7 框架包名，**不是游戏的真名**。要拿真游戏名得看外层 APK 的 `AndroidManifest.xml`：

```bash
aapt dump xmltree game.apk AndroidManifest.xml | grep -A1 'application'
# 或
aapt dump badging game.apk | grep application-label
```

## 备忘：cocos2dx 默认值 vs SDK 覆盖

cocos2dx 2.x 默认调用 `setXXTEAKeyAndSign("", 0, "", 0)`（无加密），冰火 SDK 在 `cocos2d::LuaStack::init` 时覆盖。如果 APK 内有 `assets/src/cocos/cocos2d/LuaStack.cpp` 或类似痕迹，那是没被改过的 cocos —— 不会有 aries-wow-sign 加密。有 `aries-wow-sign` 一定是被 SDK 改过。

## 验证样本（2026-07-23 batch）

- **APK**: `D:\test_games_file\hermes-test\16976_5_2-4-1_20260626145353_3232.apk` (625MB)
- **包名**: `com.aemyzg.cdqj.zf17.x7sy`
- **结果**: 1500/1502 解密成功，提取 106,791 条唯一中文
- **输出**: `D:\test_games_file\hermes-test\texts\texts.csv` (utf-8-sig)
- **验证脚本**: `D:\test_games_file\hermes-test\decrypt_and_extract.py`
