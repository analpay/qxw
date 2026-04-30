---
name: qxw-image
description: 使用 `qxw-image` 处理图片：把相机 RAW（CR2/CR3/NEF/ARW/DNG/ORF/RW2/PEF/RAF）批量转 JPG（默认沿用相机内嵌预览，画质对齐 Finder/Preview）；把 SVG 批量栅格化为同名 PNG（自动注入 CJK 字体栈避免中文方块）；对已有位图套用调色滤镜（内置 `fuji-cc` 富士经典正片、`ghibli` 吉卜力风，可注册自定义）；按 `subtle/balanced/punchy` 档位自动调整亮度/对比/饱和（默认带 HDR 局部 tone mapping）；原地擦除 EXIF/IPTC/XMP/ICC 元数据。当用户说"把 RAW 转成 JPG / 套个胶片滤镜 / 富士色 / 宫崎骏色 / SVG 转 PNG / 中文 SVG 渲染成方块怎么办 / 自动加曝光对比 / HDR 修图 / 去 EXIF / 去 GPS 元数据 / 发图前匿名化"，或者直接念到 `qxw-image raw`、`qxw-image svg`、`qxw-image filter`、`qxw-image change`、`qxw-image clear` 时，使用此 skill。图片画廊 HTTP 服务已迁到 `qxw-serve image-web`，本 skill 不覆盖。
---

# qxw-image

```bash
pip install "qxw[image]"           # Pillow + rawpy + cairosvg
pip install pillow-heif            # 可选：HEIC 支持
```

| 子命令 | 用途 |
|--------|------|
| `raw` | RAW → JPG，可一步 `--filter` 调色 |
| `svg` | SVG → 同名 PNG，自动注入 CJK 字体栈 |
| `filter` | 已有位图套调色滤镜（与 `raw --filter` 共享插件库） |
| `change` | 自动亮度 / 对比 / 饱和 + 可选 HDR 局部 tone mapping |
| `clear` | **原地**擦除 EXIF / IPTC / XMP / ICC 元数据（不可逆） |

> 图片画廊（缩略图 / 灯箱 / 15 档调色）请用 `qxw-serve image-web`。

## raw：RAW 批量转 JPG

```bash
qxw-image raw                                  # 当前目录 → ./jpg/
qxw-image raw -d ~/Photos -r                   # 递归
qxw-image raw -d ~/Photos -o ~/Photos/converted --overwrite
qxw-image raw --filter fuji-cc                 # 走 rawpy 路径调色
qxw-image raw --filter ghibli
```

| 参数 | 缩写 | 默认 | 说明 |
|------|------|------|------|
| `--dir` | `-d` | `.` | 输入目录 |
| `--output` | `-o` | `<src>/jpg` | 输出目录（保持相对路径） |
| `--recursive` | `-r` | false | 递归 |
| `--quality` | `-q` | 92 | JPEG 质量（仅 rawpy 路径） |
| `--overwrite` / `--no-overwrite` | - | `--no-overwrite` | |
| `--use-embedded` / `--no-use-embedded` | - | `--use-embedded` | 优先用相机内嵌 JPEG 预览 |
| `--fast` | - | false | 线性去马赛克 + 半分辨率（rawpy 路径，约 8–10× 加速） |
| `--filter` | - | `default` | 调色滤镜插件名（详见下文） |
| `--workers` | `-j` | `min(CPU, 4)` | 并行线程；`-j 1` 串行 |

### 两条转换路径

1. **`--use-embedded`（默认）**：直接写相机内嵌 JPEG 预览的原始字节。色彩 / 色调 / EXIF 与相机直出（Finder / Preview 看到的效果）一致。`--quality` 与 `--fast` **不影响**这条路径。仅在内嵌预览长边 ≥ 1000px 时启用，否则自动降级到 rawpy。
2. **`--no-use-embedded` / 内嵌不可用**：rawpy 解码（sRGB / 8bit / 相机白平衡 / 自动亮度），`--quality` 生效。无相机厂商色调，画面偏平但便于后期；`--fast` 切到线性 demosaic + 半分辨率。

### 与 `--filter` 的交互

- `--filter default`（默认值）→ 不调色，对 `--use-embedded / --no-use-embedded` 完全无影响。
- `--filter <非 default>` → 必须解码后的像素，所以会自动切到 `--no-use-embedded`。如果用户**同时显式**写了 `--use-embedded`，命令直接报错并退出码 2，避免静默覆盖意图。

## filter：已有位图批量调色

与 `raw --filter` 共享同一套滤镜插件，区别在于输入：

| 入口 | 输入 | 流水线 |
|------|------|--------|
| `qxw-image raw --filter <name>` | RAW | RAW → rawpy → 调色 → JPEG（**单遍，画质最佳**） |
| `qxw-image filter -n <name>` | JPG/PNG/TIFF/HEIC | PIL → 调色 → JPEG |

```bash
qxw-image filter --list                            # 列出所有可用滤镜
qxw-image filter -n fuji-cc -d ~/Photos/exports    # → ~/Photos/exports/filtered/
qxw-image filter -n ghibli -d ./raw-out -r         # 递归；自动跳过输出目录的旧产物
```

| 参数 | 缩写 | 默认 |
|------|------|------|
| `--dir` | `-d` | `.` |
| `--output` | `-o` | `<src>/filtered` |
| `--recursive` | `-r` | false |
| `--name` | `-n` | 必填（除非 `--list`）；不接受 `default` |
| `--quality` | `-q` | 92 |
| `--overwrite` / `--no-overwrite` | - | `--no-overwrite` |
| `--workers` | `-j` | `min(CPU, 4)` |
| `--list` | - | false（列出所有滤镜后退出） |

输入：JPG / JPEG / PNG / WebP / BMP / TIFF / HEIC / HEIF。统一输出 JPG。**要保留 RAW 最佳画质就用 `raw --filter`，不要先转 JPG 再 filter**。

### 内置滤镜

| 名称 | 风格 |
|------|------|
| `default` | 不调色（保留名，无法被覆盖） |
| `fuji-cc` | 富士 Classic Chrome 近似：S 曲线 + 整体降饱和 + 红橙再降饱和 + 暖阴影 / 冷高光 split-tone + 绿向青微偏 |
| `ghibli` | 吉卜力近似：水彩抬黑压白 + 整体淡暖 + 天空推向粉彩蓝（#D2E3EF）+ 暖饱和绿植 + 冷紫阴影 |

> 这些不是精确色彩科学还原，只是 numpy 后处理凑出来的近似风格。

### 注册自定义滤镜

```python
import numpy as np
from qxw.library.services.color_filters import register_filter

@register_filter("my-cool-look")
def _my_look(rgb: np.ndarray) -> np.ndarray:
    arr = rgb.astype(np.float32) / 255.0
    # ... 调色 ...
    return np.clip(arr * 255.0, 0, 255).astype(np.uint8)
```

只要在命令执行前 import 触发注册（项目 `__init__.py` 里），`--filter my-cool-look` / `-n my-cool-look` 就生效。`default` 是保留名，不可占用。

## change：自动亮度 / 对比 / 饱和（含 HDR）

目标是**"看着舒服"**（自然、保留肤色与高光、不要 neon/halo），而不是最大化对比。

```bash
qxw-image change                               # 当前目录 → ./changed/，balanced + HDR
qxw-image change -i punchy                     # 灰阴天 / 室内手机直出 / 低对比截图
qxw-image change --no-hdr                      # 关 HDR，纯传统流水线（更保守）
qxw-image change -i subtle --no-preserve-exif  # 温和 + 匿名化
qxw-image change -q 95 -j 8 --overwrite        # 高质量 + 多线程
```

| 参数 | 缩写 | 默认 | 说明 |
|------|------|------|------|
| `--dir` | `-d` | `.` | |
| `--output` | `-o` | `<src>/changed` | |
| `--recursive` | `-r` | false | 自动跳过输出目录的旧产物 |
| `--intensity` | `-i` | `balanced` | `subtle` / `balanced` / `punchy` |
| `--hdr` / `--no-hdr` | - | `--hdr` | 默认开 |
| `--preserve-exif` / `--no-preserve-exif` | - | `--preserve-exif` | orientation 会被强制设为 1 |
| `--quality` | `-q` | 92 | |
| `--overwrite` / `--no-overwrite` | - | `--no-overwrite` | |
| `--workers` | `-j` | `min(CPU, 4)` | |

### 档位

| 档位 | 强度 | 适用场景 |
|------|------|---------|
| `subtle` | 温和 | 本身曝光对比不错，只想轻度加分 |
| `balanced`（默认） | 平衡 | 日常 90% 情况；自动检测暗光分支做针对性提亮 |
| `punchy` | 强烈 | 灰度大 / 对比低 / 压缩明显的手机直出或截图 |

### 算法流水线

1. sRGB → LAB，主要在 L 通道操作
2. **中位数亮度检测**：低于阈值走 IAGCWD-style 暗光分支（加权 CDF 反函数抬暗部）；否则走 Auto-Levels（百分位拉伸，Limare 等的 Simplest Color Balance）
3. **CLAHE**：L 通道局部对比度增强，clipLimit / tileGrid 按档位调；避免全局均衡的"塑料感"
4. **中位数 Gamma**：把处理后的 L 中位数贴近目标
5. `--hdr` 开启时：对 L 做高斯低通得 base，log-domain 压缩 base 动态范围，再按系数放大 detail（Durand-Dorsey lite）
6. LAB → sRGB → HSV，用**肤色软 mask**（H/S/V 三维 smoothstep）做非线性 vibrance（低饱和加得多 / 高饱和几乎不动 / 肤色区域 boost 打折）
7. HSV → RGB，clip 回 uint8

### EXIF 处理

- 默认保留 EXIF；orientation tag (0x0112) 强写为 1（处理前已 `ImageOps.exif_transpose` 物理旋转过；不清理会被查看器二次旋转 → 双重旋转）
- `--no-preserve-exif` 清空所有 EXIF，输出最小化

输入：JPG / JPEG / PNG / WebP / BMP / TIFF / HEIC / HEIF；输出 JPG。**不支持 RAW 输入**——要 RAW 自动增强先 `qxw-image raw` 解码再 `qxw-image change`。

## clear：原地擦除元数据

**不可逆**。常见使用场景：发图前去 GPS / 拍摄设备 / 编辑历史 / 版权水印；批量"消毒"下载图片。

```bash
qxw-image clear                            # 默认会要求二次确认
qxw-image clear -d ~/Photos/exports -r --yes   # 递归 + 跳过确认
qxw-image clear -d ~/Photos -j 8 --yes
qxw-image clear -d ~/Photos -j 1 --yes     # 串行（更易调试）
```

| 参数 | 缩写 | 默认 |
|------|------|------|
| `--dir` | `-d` | `.` |
| `--recursive` | `-r` | false |
| `--yes` | `-y` | false（必须输入 yes 才继续） |
| `--workers` | `-j` | `min(CPU, 4)` |

### 擦除范围（容器级，**不动像素**）

- **EXIF**：拍摄参数 / GPS / 相机型号 / orientation
- **IPTC**：版权 / 关键字
- **XMP**：Adobe / 编辑历史
- **ICC profile**：色彩配置文件
- **JPEG COM 注释 / PNG text chunk**（Author / Copyright / Description / Software / 自定义文本）

### 画质策略

| 格式 | 策略 | 像素无损？ |
|------|------|-----------|
| JPEG | `quality="keep"` 沿用原量化表 + DCT 系数，仅清 APP1/APP2/APP13/COM marker | ✅ |
| PNG | 重编码（不写 text/iTXt/zTXt/eXIf/iCCP chunk） | ✅ |
| TIFF | 沿用原压缩重编码，仅删 user-metadata tag | 取决于压缩 |
| WebP | 强制 `lossless=True` 重编码 | ✅ |

> ⚠️ **WebP 体积**：原本是有损 WebP 的文件经 lossless 重编码后体积可能涨 3–10 倍。这是无损重写元数据的代价。

### 安全保证

- **临时文件 + `os.replace`** 原子替换：编码失败时源文件保持原样
- 文件本来就没有任何元数据时直接跳过、不重写源文件（mtime 不变）
- 默认要求"即将覆盖 N 个文件"二次确认，输入 yes 才继续；`--yes` 跳过

### 已知限制

- **不支持 HEIC/HEIF**：libheif 的 HEIC 编码依赖带 x265 的构建，环境差异大。要去 HEIC 元数据请先转 JPEG
- **TIFF 仅清"用户级 tag"**：结构性 tag（ImageWidth / Compression / StripOffsets 等）必须保留，否则文件无法解码
- **不可逆**：成功擦除后无法找回原 EXIF。重要照片提前备份

输入：JPG / JPEG / PNG / TIFF / TIF / WebP。

输出统计：`已清理` / `无元数据` / `失败`。

## svg：批量栅格化

```bash
qxw-image svg                                          # 当前目录递归 → 同名 PNG，2× 缩放，白底
qxw-image svg -d ./assets
qxw-image svg --no-recursive -s 1.0 --no-overwrite    # 仅顶层 + 1× + 不覆盖
qxw-image svg --font-family '"Noto Sans CJK SC", sans-serif'
qxw-image svg -b transparent                           # 透明底
qxw-image svg -b dark                                  # #0f172a 深色底
```

| 参数 | 缩写 | 默认 | 说明 |
|------|------|------|------|
| `--dir` | `-d` | `.` | |
| `--recursive` / `--no-recursive` | `-r` | `--recursive` | |
| `--scale` | `-s` | 2.0 | 1.0 = 原始；高 DPI 屏建议 2.0+ |
| `--overwrite` / `--no-overwrite` | - | `--overwrite` | |
| `--font-family` | - | 跨平台 CJK 字体栈 | CSS font-family；传 `""` 禁用注入 |
| `--background` | `-b` | `white` | `white` / `transparent` / `dark` |
| `--workers` | `-j` | `min(CPU, 4)` | |

PNG 与源 SVG **同目录、同名**（仅扩展名不同），保持原目录结构。

### 中文渲染（重要）

cairosvg 走 cairo + fontconfig 选字体。SVG 里写的 `font-family`（如 `Arial` / `serif`）若在当前系统解析到的字体不含 CJK 字形，中文就会变方块（豆腐 □）。

`svg` 子命令默认会向源 SVG 注入一段内联 CSS，把 `<text> / <tspan> / <textPath>` 的 `font-family` 以 `!important` 覆盖为跨平台 CJK 字体栈：

- macOS：PingFang / Hiragino
- Windows：YaHei / SimHei
- Linux：Noto CJK / Source Han / WenQuanYi
- 兜底：`sans-serif`

完全保留原 SVG 字体：`--font-family ""`；指定字体：`--font-family '"Noto Sans CJK SC", sans-serif'`。

> 注入仅对 SVG 的 `<style>` 规则生效；如果原 SVG 用 `<image>` 嵌入了位图文字，本参数无能为力。

## 加速建议

- 默认已开 `min(CPU, 4)` 个线程并行；批量大时 `-j 8` 或更高；内存吃紧 `-j 2` / `-j 1`
- **嵌入预览路径极快**：只写字节、无解码，几百张 RAW 秒级完成
- **rawpy 解码慢**：AHD demosaic 是 CPU 密集，单张数秒。要快加 `--fast`（半分辨率 + 线性 demosaic）

## 常见踩坑

- **RAW 转出来的 JPG 看起来比 Preview 里灰**：默认 `--use-embedded` 沿用相机内嵌预览，颜色对齐 Preview。如果你看到偏色 / 偏灰，说明走到了 rawpy 路径——可能是内嵌预览长边 < 1000px，自动降级；或者你显式 `--no-use-embedded` / `--filter <非 default>` 强制了 rawpy。
- **`--filter` 和 `--use-embedded` 冲突报错**：意料之中，二选一。
- **SVG 里中文还是方块**：检查 `--font-family ""` 是否被传了空串导致禁用注入；或者 SVG 本身用 `<image>` 嵌的位图文字（无法修复）。
