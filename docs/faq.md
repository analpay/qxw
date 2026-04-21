# FAQ - 常见问题

## 安装相关

### Q: 安装后执行 `qxw hello` 或其他命令提示 "command not found"

确保已正确安装：

```bash
pip install -e .
```

如果使用了虚拟环境，确保已激活：

```bash
source .venv/bin/activate
```

### Q: 安装时提示 Python 版本不满足要求

QXW 要求 Python >= 3.10。请升级 Python 版本：

```bash
# macOS (Homebrew)
brew install python@3.12

# Ubuntu
sudo apt install python3.12
```

### Q: pip install 时报依赖冲突

尝试在虚拟环境中安装：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 使用相关

### Q: TUI 界面显示乱码

确保终端支持 UTF-8 编码：

```bash
export LANG=en_US.UTF-8
```

推荐使用支持 Unicode 的终端模拟器（如 iTerm2、Windows Terminal）。

### Q: 如何退出 TUI 界面

按 `Q` 键或 `Ctrl+C` 退出。

### Q: 如何切换 TUI 暗色/亮色主题

在 TUI 界面中按 `D` 键切换。

### Q: qxw-image svg 转出来的 PNG 中文全是方块（□）

cairosvg 按 SVG 声明的 `font-family` 选字体，若该字体不含 CJK 字形，中文就会渲染成方块。`svg` 子命令默认会向 SVG 注入 CSS，把文本字体强制覆盖为跨平台 CJK 字体栈（PingFang / YaHei / Noto CJK 等），已经可修复绝大多数场景。

若仍有问题：

- 指定你本机实际安装的 CJK 字体：`qxw-image svg --font-family '"Noto Sans CJK SC", sans-serif'`
- 检查系统是否安装了任一 CJK 字体（macOS 一般自带 PingFang SC；Linux 可安装 `fonts-noto-cjk`）
- 如果 SVG 是把文字当 `<image>` 位图嵌入的，则此选项无效，需要回到设计工具导出矢量文字

## 开发相关

### Q: 如何添加新命令

参考 [开发手册](development.md) 中的 "新增命令步骤" 章节。

### Q: 数据模型应该放在哪里

使用 Pydantic 定义的数据模型放在对应的命令文件或 `qxw/library/` 下的相关模块中。
ORM 模型放在 `qxw/library/models/` 目录下。
