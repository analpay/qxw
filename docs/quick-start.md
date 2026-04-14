# 快速开始

本文档帮助你在 5 分钟内完成 QXW 工具集的安装和首次使用。

## 1. 环境准备

确保你的系统满足以下要求：

- Python >= 3.10
- pip 包管理器

```bash
# 检查 Python 版本
python3 --version
```

## 2. 安装

```bash
# 克隆项目
git clone <仓库地址>
cd qxw

# 安装到系统（开发模式）
pip install -e .
```

## 3. 验证安装

```bash
# 运行示例命令（默认命令行模式）
qxw-hello

# 或使用 TUI 交互模式
qxw-hello --tui
```

如果看到 "你好, 世界！" 的输出，说明安装成功。

## 4. 查看帮助

每个命令都支持 `--help` 参数：

```bash
qxw-hello --help
```

## 5. 下一步

- 阅读 [使用手册](user-guide.md) 了解所有可用命令
- 阅读 [开发手册](development.md) 了解如何开发新命令
