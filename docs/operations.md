# 运维手册

本文档介绍 QXW 工具集的部署、配置和运维相关内容。

## 安装部署

### 生产环境安装

```bash
pip install .
```

### 开发环境安装

```bash
pip install -e ".[dev]"
```

## 配置管理

### 环境变量

QXW 使用 `QXW_` 前缀的环境变量进行配置：

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `QXW_APP_NAME` | qxw | 应用名称 |
| `QXW_DEBUG` | false | 是否开启调试模式 |
| `QXW_DB_URL` | sqlite:///qxw.db | 数据库连接地址 |
| `QXW_LOG_LEVEL` | INFO | 日志级别 (DEBUG/INFO/WARNING/ERROR) |
| `QXW_LOG_DIR` | ~/.qxw/logs | 日志文件目录 |
| `QXW_CONFIG_DIR` | ~/.qxw | 配置文件目录 |

### .env 文件

也可以在项目根目录创建 `.env` 文件：

```env
QXW_DEBUG=true
QXW_LOG_LEVEL=DEBUG
QXW_DB_URL=sqlite:///data/qxw.db
```

## 目录说明

| 路径 | 说明 |
|------|------|
| `~/.qxw/` | 用户配置目录 |
| `~/.qxw/logs/` | 日志文件目录 |
| `qxw.db` | SQLite 数据库文件（默认位置） |

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

默认使用 SQLite，数据库文件位于当前目录的 `qxw.db`。

可通过环境变量修改：

```bash
export QXW_DB_URL="sqlite:///path/to/custom.db"
```

## 故障排查

1. **命令未找到**: 确认已执行 `pip install -e .`
2. **权限错误**: 检查 `~/.qxw/` 目录权限
3. **数据库错误**: 检查 `QXW_DB_URL` 配置是否正确
