# 运维手册

本文档介绍 QXW 工具集的部署、配置和运维相关内容。

## 安装部署

### 一键安装（推荐）

项目提供了自动安装脚本 `install.sh`，会自动检测环境并安装所有依赖：

```bash
bash install.sh
```

脚本支持以下选项：

| 选项 | 说明 |
|------|------|
| `--dev` | 开发模式安装（虚拟环境 + dev 依赖） |
| `--force` | 强制重装（覆盖已有安装） |
| `--gitbook` | 同时安装 gitbook PDF 导出依赖（weasyprint） |
| `--uninstall` | 卸载 qxw |
| `--help` | 显示帮助信息 |

脚本自动完成：
1. 检测操作系统和包管理器（macOS Homebrew / Ubuntu apt / CentOS dnf/yum / Arch pacman / Alpine apk / openSUSE zypper）
2. 安装 Python >= 3.10（如缺失，macOS 会先安装 Homebrew）
3. 安装 pip（如缺失）
4. 安装 pipx（如缺失）
5. 通过 pipx 全局安装 qxw
6. 验证所有命令是否可用

### 手动全局安装

使用 pipx 安装，命令全局可用，自动隔离依赖，无需手动激活虚拟环境：

```bash
pipx install .

# 更新（代码改动后重新安装）
pipx install . --force

# 卸载
pipx uninstall qxw
```

### 手动开发环境安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## 配置管理

### 环境变量

QXW 使用 `QXW_` 前缀的环境变量进行配置：

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `QXW_APP_NAME` | qxw | 应用名称 |
| `QXW_DEBUG` | false | 是否开启调试模式 |
| `QXW_DB_URL` | sqlite:///$HOME/.config/qxw/qxw.db | 数据库连接地址 |
| `QXW_LOG_LEVEL` | INFO | 日志级别 (DEBUG/INFO/WARNING/ERROR) |
| `QXW_LOG_DIR` | ~/.config/qxw/logs | 日志文件目录 |
| `QXW_CONFIG_DIR` | ~/.config/qxw | 配置文件目录 |

### .env 文件

也可以在项目根目录创建 `.env` 文件：

```env
QXW_DEBUG=true
QXW_LOG_LEVEL=DEBUG
QXW_DB_URL=sqlite:///data/qxw.db
```

### 配置文件 (setting.json)

QXW 支持从 `~/.config/qxw/setting.json` 读取配置，首次运行命令时会自动基于内置模板生成。也可以手动创建，参考 `qxw/config/setting.json.example`：

```json
{
    "app_name": "qxw",
    "app_version": "0.1.0",
    "debug": false,
    "db_url": "sqlite:///~/.config/qxw/qxw.db",
    "log_level": "INFO",
    "log_dir": "~/.config/qxw/logs",
    "config_dir": "~/.config/qxw",
    "zenmux_api_key": "",
    "zenmux_base_url": "https://zenmux.ai/api/vertex-ai",
    "zenmux_image_model": "google/gemini-3-pro-image-preview"
}
```

与 `qxw-markdown cover` 相关的三个字段用于通过 ZenMux 调用 Gemini 3 Pro Image Preview（Nano Banana Pro）生成 Markdown 封面图，也可用环境变量 `ZENMUX_API_KEY` 覆盖 `zenmux_api_key`。

配置优先级（从高到低）：环境变量 > .env 文件 > setting.json > 代码默认值。

## 环境初始化

首次运行 `qxw-hello` 时会自动检测并初始化运行环境，包括：

| 初始化项 | 路径 | 说明 |
|----------|------|------|
| 配置目录 | `~/.config/qxw/` | 所有配置和数据的根目录 |
| 配置文件 | `~/.config/qxw/setting.json` | 基于内置模板自动生成 |
| 日志目录 | `~/.config/qxw/logs/` | 日志文件存放目录 |
| 数据库 | `~/.config/qxw/qxw.db` | SQLite 数据库文件 |

如需重新初始化，删除 `~/.config/qxw/` 目录后重新运行命令即可。

## 目录说明

| 路径 | 说明 |
|------|------|
| `~/.config/qxw/` | 用户配置目录 |
| `~/.config/qxw/setting.json` | JSON 配置文件 |
| `~/.config/qxw/logs/` | 日志文件目录 |
| `~/.config/qxw/qxw.db` | SQLite 数据库文件（默认位置） |

## 日志

日志同时输出到 stderr 和文件（如已配置）。

日志格式：
```
2024-01-01 12:00:00 [INFO] qxw.hello: 启动 qxw-hello 命令
```

### 调整日志级别

```bash
export QXW_LOG_LEVEL=DEBUG
```

## 数据库

默认使用 SQLite，数据库文件位于 `~/.config/qxw/qxw.db`。

可通过环境变量修改：

```bash
export QXW_DB_URL="sqlite:///path/to/custom.db"
```

## 故障排查

1. **命令未找到**: 确认已通过 `pipx install .` 或 `pip install -e .`（虚拟环境内）安装
2. **pipx 安装后命令不可用**: 执行 `pipx ensurepath` 并重启终端
3. **权限错误**: 检查 `~/.config/qxw/` 目录权限
4. **数据库错误**: 检查 `QXW_DB_URL` 配置是否正确
