---
name: extract-game-text-csv
description: "Extract all player-facing Chinese (and other) game text from reverse-engineered mobile game resources into a single-column texts.csv. Apply this whenever the user asks to extract, pull, get, or scrape in-game text from APK/IPA assets."
version: 2.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [game-reversing, text-extraction, chinese, i18n, csv, output-format]
    related: [get-game-text, ida-pro-mcp]
---

# Game Text Extraction → texts.csv 规范

## 1. 输出文件（硬性要求）

| 项目 | 要求 |
|------|------|
| 文件名 | **必须**是 `texts.csv` |
| 路径 | 交付区（hermes-home/outputs/） |
| 编码 | **utf-8-sig**（带 BOM，Excel 打开不乱码） |
| 列数 | **1 列** |
| 列名 | **`text`**（第一行表头） |
| 行数 | 任意（N≥10 到 100K+ 都正常） |
| 包裹 | 文本**不加引号**、不转义内部 `"` 或 `,` |
| 换行处理 | 句内 `\n` **必须保留** |

**Python 写入模板**：
```python
with open('texts.csv', 'w', encoding='utf-8-sig', newline='') as f:
    f.write('text\n')
    for s in texts:
        f.write(s + '\n')
```

## 2. 提取什么（KEEP）

- **富文本**（必须有开有闭的成对标签/占位符）：`[color=green size=42]...[/]`, `<color=#FF0000>...</color>`, `[765D42]...[/765D42]`
- **占位符文本**（保留 `%s` `%d` `{}` `{0}` `{1}` 等）：`"可领取次数%s"`, `"第%s期"`
- **单行 UI 标签**："开服盛典"、"7日登陆"、"月卡"、"确 认"、"已领取"
- **名字/角色名**："蔷薇帝国"、"灵主"、"米哈伊尔"
- **技能/装备/物品描述**：从 `Story.luac` 的 `Desc` 字段、`Item.luac` 的 `Desc`/`Desc2` 字段
- **剧情对白**（单行）："哼。"、"嗯？"、"你好，大卫。"
- **剧情段落**（多句段）："茫茫之野，在彼之原；濯日洗月，别于黄泉。……"
- **任务说明**（含数字编号与换行占位符）
- **配置 ID/枚举中文名**（如 `ggv.funcUnlock.corps` → "军团"，但要的是中文值）
- **公告/系统消息**："服务器维护中"、"请阅读并勾选同意..."

## 3. 过滤掉什么（SKIP）

| 类型 | 例子 |
|------|------|
| 乱码 | 单字节无意义字符、`\\xc3\\x28`、`???` |
| 纯英文/纯数字 | "function"、"Hello World"、"12345" |
| 纯英文+数字混杂 | "lua_script_1"、"v1.2.3" |
| 变量名 | `playerId`、`max_count`、`tabLua` |
| 注释 | `-- 注释`、`/** 注释 */`、`// 注释`、`@param` |
| 代码片段 | `function(x) return x end`、`local t={}`、`require("...")` |
| 路径/URL | `activity_icon/leijidenglu.png`、`https://...` |
| 资源名 | `comm_big/heroShow_cs.jpg`、`heroill/1044.png` |
| 调试输出 | `print(...)`、`assert(...)`、`log(...)` |
| Lua 整段代码 | `ggv.EquipType = { HEAD = 1, BODY = 2, ... }` |
| 屏蔽词库 | `Sensitive.luac`、`Forbidden.luac`、`BanWord*` |
| 随机名库 | `Name.luac`、`NameFirst.luac`、`NameLast.luac` |
| 完整 Lua 配表 | `{1,"7日登陆","activity_icon/...",...}` 这种整行 |

**过滤启发式**：
```
KEEP = 至少含 1 个中文字符
       且中文字符占比 ≥ 20%
       且不含代码关键字（function/local=/require(/setmetatable/@param/@return/...）
       且不含 .png/.jpg/.mp3 等资源后缀
       且不含 http://https:// 链接
       且长度 ≥ 2
```

## 4. 解密后的字段级提取策略

游戏配表通常是 `tabLua={name={fields}, typeDef={types}, data={rows}}` 结构。**不要把整段 Lua 代码塞进 CSV**——只提取字段值。

**步骤**：
1. 用正则 `name\\s*=\\s*\\{([^{}]*)\\}` 提取字段名列表
2. 识别**文本字段**（按字段名判断）：
   - KEEP：`name`, `desc`, `title`, `dialogue`, `dialog`, `tip`, `content`, `text`, `str`, `cn_name`, `cn_desc`, `zh_cn`, `show_name`, `nickname`, `label`, `caption`, `prompt`, `message`, `words`, `sentence`, `reminder`, `introduce`, `unlock_desc`, `button_tips`, `get_way`, `use_tips`, `type_desc`, `attr_name`
   - SKIP：`sid`, `id`, `type`, `order`, `state`, `time`, `icon`, `iconurl`, `picture`, `figureimg`, `url`, `path`, `res`, `mp3`, `audio`, `csb`, `price`, `num`, `count`, `level`, `rank`, `score`, `bg`, `turn`, `skip`, `quality`, `star`, `reset_counter`, `pop_type`, `coef1-4`, `getway1-4`, `value1-3`, `min`, `max`, `day`, `hour`, `sec`, `unlock`, `composite_id`, `marker`, `key_data`
3. 用正则 `data\\s*=\\s*\\{` 找到数据块，按 `{}` 平衡分割每个 row
4. 解析 row：识别 `[N]="value"` 索引对 + `{N,"value",...}` 位置对 + 跳过 `nil`
5. 对**每个文本字段索引**，提取对应值，应用第 3 节过滤

**特殊结构**（如 `assets/res/data/lang/Chinese.luac`）：
- 字段：`name={"sid","str"}`，每行 `{N,"中文"}`
- **必须**把 `str` 加到 KEEP 字段集（容易漏掉！）
- 同样处理 `name={"sid","translate"}`、`name={"sid","value"}`

## 5. 多种文件类型的提取器选择

| 文件类型 | 提取方法 |
|---------|----------|
| **cocos2dx-lua 加密 .luac** | XXTEA/RC4/AES 解密 → 字段级解析 |
| **明文 .lua** | 字段级解析同上 |
| **Unity TextAsset (.txt/.csv)** | 直接按行/字段提取中文 |
| **Unity .json** | 递归遍历 JSON 树，提取所有 string 字段值 |
| **Unity .xml** | XPath 或正则提取 `<string>...</string>` |
| **UE4 .locres** | 用 UE4 localizations editor 或 il2cppdumper 转 CSV |
| **il2cpp metadata** | `il2cppdumper` → `dump.cs` + `script.json` → 提取字符串常量 |
| **自研引擎 .db/.dat/.bin** | 先看文件头 magic bytes，结构自定义 |

## 6. 通用提取脚本模板

```python
import os, re

DELTA = 0x9E3779B9  # 替换为游戏实际 DELTA（标准 XXTEA=0x9E3779B9）
KEY = b'...15字节'    # 替换为游戏实际 key
SIGN = b'aries-wow-sign'  # 替换为游戏实际 sign 头（去掉则 0 字节）

SKIP_FIELDS = {'sid','id','type','order','state','time','icon','iconurl',
               'picture','figureimg','url','path','res','mp3','csb','price',
               'num','count','level','rank','score','bg','turn','quality','star',
               'reset_counter','pop_type','coef1','coef2','coef3','coef4',
               'getway1','getway2','getway3','getway4','value1','value2','value3',
               'min','max','day','hour','sec','unlock','composite_id','marker',
               'key_data','random','last_times','role_name','map1','map2'}

TEXT_FIELDS = {'name','desc','title','dialogue','dialog','tip','content','text',
               'str','cn_name','cn_desc','zh_cn','show_name','nickname','label',
               'caption','prompt','message','words','sentence','reminder',
               'introduce','unlock_desc','button_tips','get_way','use_tips',
               'type_desc','attr_name','value','fragment','piece','word'}

CODE_KEYWORDS = re.compile(
    r'\b(function|local\s+\w+\s*=|require\s*\(|setmetatable|@param|@return|'
    r'/\*\*|\*/|print\s*\(|assert\s*\(|log\s*\()\b'
)

SKIP_FILES = {'Sensitive', 'Forbidden', 'Name', 'NameFirst', 'NameLast', 'BanWord'}

def parse_row(row):
    tokens = []  # list of (field_idx_1based, value)
    i = 0
    cur_field = 0
    while i < len(row):
        ch = row[i]
        if ch.isspace() or ch == ',': i += 1; continue
        if ch == '[':
            m = re.match(r'\[(\d+)\]\s*=\s*\"((?:[^\"\\]|\\.)*)\"', row[i:])
            if m:
                tokens.append((int(m.group(1)), m.group(2)))
                i += m.end(); continue
            m2 = re.match(r'\[(\d+)\]', row[i:])
            if m2:
                cur_field = int(m2.group(1))
                i += m2.end(); continue
        if ch == '"':
            m = re.match(r'"((?:[^\"\\]|\\.)*)"', row[i:])
            if m:
                val = m.group(1)
                if cur_field > 0:
                    tokens.append((cur_field, val)); cur_field = 0
                else:
                    if tokens: tokens.append((tokens[-1][0]+1, val))
                    else: tokens.append((2, val))
                i += m.end(); continue
        if ch.isdigit() or (ch == '-' and i+1 < len(row) and row[i+1].isdigit()):
            m = re.match(r'-?\d+', row[i:])
            if m:
                if not tokens: tokens.append((1, m.group(0)))
                else: tokens.append((tokens[-1][0]+1, m.group(0)))
                i += m.end(); cur_field = 0; continue
        if ch == 'n' and row[i:i+3] == 'nil':
            if tokens: cur_field = tokens[-1][0] + 1
            i += 3; continue
        i += 1
    return tokens

def cn_count(s):
    return sum(1 for c in s if '\u4e00' <= c <= '\u9fff' or '\u3400' <= c <= '\u4dbf')

# Main loop
seen = set()
texts = []
for root, _, files in os.walk(src_root):
    for f in files:
        if not f.endswith('.luac'): continue
        if os.path.splitext(f)[0] in SKIP_FILES: continue
        fp = os.path.join(root, f)
        with open(fp, 'rb') as fh: data = fh.read()
        if SIGN and data[:len(SIGN)] != SIGN: continue
        # xxtea_decrypt...
        result = data  # placeholder - call actual decrypt
        if result is None: continue
        text = result.decode('utf-8', errors='replace')
        # Parse fields + data block, extract text values...
        # Apply filtering rules, dedup, append to texts list

# Sort by length desc, then Chinese count desc
texts.sort(key=lambda s: (-len(s), -cn_count(s), s))

with open('texts.csv', 'w', encoding='utf-8-sig', newline='') as f:
    f.write('text\n')
    for s in texts:
        f.write(s + '\n')
```

## 7. 验证清单

写完 CSV 后**必须自查**：

- [ ] 文件名是 `texts.csv`（不是 `output.csv`、`text.csv` 等）
- [ ] 编码是 utf-8-sig（`hexdump -C texts.csv | head -1` 应以 `EF BB BF` 开头）
- [ ] 只有 1 列，表头是 `text`
- [ ] 没有任何引号包裹（`grep '^"' texts.csv` 应为空）
- [ ] 没有 Lua 整段代码（`grep 'local tabLua' texts.csv` 应为空）
- [ ] 没有 .png/.jpg 等资源路径（`grep '\.png' texts.csv` 应为空或极少）
- [ ] `Sensitive.luac`/`Name.luac`/`Forbidden.luac` 内容**没**出现
- [ ] 至少有 1 条富文本
- [ ] 至少 5,000+ 条有效文本

## 8. 相关技能

- **`get-game-text`** — 完整的加密检测 / 解密 / 提取方法论
- **`aries-xxtea-binghuo`** — 冰火游戏修改版 XXTEA 解密
- **`ida-pro-mcp`** — IDA Pro 静态分析
- **`il2cppdumper`** — Unity il2cpp metadata 提取
- **`assetstudio-cli`** — Unity AssetBundle 资源提取
