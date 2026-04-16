# 快速开始

本文档帮助你在 5 分钟内完成 QXW 工具集的安装和首次使用。

## 1. 环境准备

确保你的系统满足以下要求：

- Python >= 3.10
- pipx（推荐）或 pip 包管理器

```bash
# 检查 Python 版本
python3 --version

# 安装 pipx（如未安装）
brew install pipx    # macOS
# 或 pip install pipx
```

## 2. 安装

### 方式一：pipx 全局安装（推荐）

使用 pipx 安装后命令全局可用，无需手动激活虚拟环境：

```bash
git clone <仓库地址>
cd qxw
pipx install .
```

代码更新后重新安装：

```bash
pipx install . --force
```

### 方式二：虚拟环境开发模式

```bash
git clone <仓库地址>
cd qxw
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 3. 验证安装

```bash
# 运行示例命令（默认命令行模式）
qxw-hello

# 或使用 TUI 交互模式
qxw-hello --tui
```

首次运行时会自动初始化运行环境（创建配置目录、配置文件、日志目录和数据库），输出类似：

```
检测到运行环境未完成初始化，正在自动初始化...
  已初始化: 配置目录
  已初始化: 配置文件
  已初始化: 日志目录
  已初始化: 数据库
环境初始化完成
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
