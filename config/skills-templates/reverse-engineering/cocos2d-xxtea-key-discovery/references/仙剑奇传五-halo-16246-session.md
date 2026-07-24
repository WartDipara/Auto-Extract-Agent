# Session: 仙剑奇传五 (halo) 16246_5_7-1-53

## APK Info

| Field | Value |
|-------|-------|
| APK path | `D:\test_games_file\hermes-test\16246_5_7-1-53_20251205104655_halo.apk` |
| Package | X7 pluginized (com.smwl.smsdk.plugin) |
| Game | 仙剑奇传五 (Chinese Paladin / Sword and Fairy 5) |
| Engine | cocos2d-x (old version, class names: CCLuaEngine, CCLuaStack, CCLayer, CCSprite) |
| Arch | ARM32 (armeabi-v7a) |

## File Structure

```
APK/
├── assets/
│   ├── scripts/            ← 1010 plaintext Lua files (14MB)
│   ├── res/data/*.txt      ← 245 encrypted config files (10.5MB)
│   ├── res/edata/*.txt     ← 239 encrypted files (same data, 10.5MB)
│   ├── translator/          ← X7 plugin (skip)
│   └── plugin-release.zip  ← X7 plugin (skip)
├── lib/armeabi-v7a/
│   ├── libgame.so          ← 7.8MB, cocos2d-x game engine + XXTEA
│   ├── libEncrypt.so       ← 3DES/EncryptUtils (qipa SDK, skip)
│   ├── libtranslator_plugin.so  ← X7 (skip)
│   └── ...
└── classes*.dex            ← 6 dex files (~200MB total)
```

## Decryption Details

| Item | Value |
|------|-------|
| Sign | `"libai"` (5 bytes, in .rodata at 0x69280f) |
| Key | `"dtou4guxiang"` (11 bytes, zero-padded to 16) |
| Algorithm | Standard XXTEA (DELTA = 0x9E3779B9) |
| Decryption function | `cocos2d::CZHelperFunc::getFileData` at 0x318c8c |
| Key discovery method | Adjacent .rodata strings: `"dtou4gu"` + `"xiang"` |
| Decrypted format | UTF-8 BOM + Tab-separated CSV (3 header rows + data) |
| Total decrypted | 484 files (data/ + edata/) |

### .rodata Hex (at 0x692800)

```
34 00            → "4\0"
64 74 6f 75 34 67 75 00  → "dtou4gu\0"
78 69 61 6e 67 00         → "xiang\0"
6c 69 62 61 69 00         → "libai\0"  ← SIGN
78 69 61 6e 6a 69 61 6e 35 00  → "xianjian5\0"
74                         → "t" (start of "toutiao" or similar)
```

## Lua Script Text Extraction

- 1,010 .lua files scanned, 371 contained Chinese
- 1,510 unique Chinese text entries (before dedup)
- Most text is UI strings, error messages, battle logs
- Config table text (item names, skills, descriptions) is in encrypted data files

## Data File Text Extraction

- 26,161 unique Chinese text entries from decrypted config tables
- Content: skill descriptions, item names, NPC dialogue, store items, quest text, battle effects, leveling info, faction/guild text, equipment descriptions, etc.

## Output Files

| File | Path |
|------|------|
| Chinese text CSV | `D:\test_games_file\hermes-test\work_16246\Chinese_Text_All_Clean.csv` |
| Decrypted tables | `D:\test_games_file\hermes-test\work_16246\decrypted_data\` (478 files) |
| Lua texts | `D:\test_games_file\hermes-test\work_16246\Chinese_Text.csv` |
