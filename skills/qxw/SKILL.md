---
name: qxw
description: QXW 工具集主命令的使用指南。包含 `qxw list`（列出所有 qxw-* 独立命令）、`qxw hello`（验证安装 / 初始化配置目录）、`qxw sbdqf`（致敬 sl 的老鼠穿越动画）、`qxw completion`（为所有 qxw / qxw-* 命令一次性生成并安装 zsh / bash 补全）。当用户问"qxw 怎么用 / 怎么列出所有命令 / 怎么开 tab 补全 / 怎么验证 qxw 装好没 / 怎么初始化配置目录"，或者直接说 `qxw list`、`qxw hello`、`qxw completion install`、`qxw sbdqf`、想为 qxw 启用 shell 补全、想看 qxw 都装了哪些子命令时，使用此 skill。
---

# qxw 主命令

`qxw` 是 QXW 工具集的主命令组（Click command group），承载 4 个内置子命令；其余 `qxw-*` 命令是独立 console_scripts。

## 子命令速查

| 子命令 | 用途 |
|--------|------|
| `qxw list` | 列出所有 `qxw-*` 独立命令（不含本命令组的内置子命令） |
| `qxw hello` | 示例命令；首次运行会自动初始化 `~/.config/qxw/`（配置 / 日志 / sqlite） |
| `qxw sbdqf` | ASCII 老鼠从右往左穿越终端的动画（动画期间 Ctrl+C 无效） |
| `qxw completion` | 一次性生成并安装 `qxw` / 所有 `qxw-*` 的 zsh / bash 补全 |

## qxw list

```bash
qxw list                # 仅展示通过 console_scripts 注册的 qxw-* 独立命令
qxw --help              # 看本命令组的内置子命令（list / hello / sbdqf / completion）
```

## qxw hello（验证安装 + 初始化）

首次运行时会自动：
- 建 `~/.config/qxw/` 配置目录
- 拷贝 `setting.json` 模板
- 建 `logs/` 目录
- 初始化 `qxw.db`（SQLite）

```bash
qxw hello                       # 默认问候 "世界"
qxw hello --name 开发者          # 自定义问候对象
qxw hello --tui                 # Textual TUI 模式（Q 退出 / D 切主题）
```

## qxw sbdqf（致敬 sl）

```bash
qxw sbdqf                # 跑 1 轮
qxw sbdqf -r 3           # 跑 3 轮
qxw sbdqf -d 5           # 最多跑 5 秒后停
```

动画期间会屏蔽 SIGINT，必须等老鼠跑完，行为对齐经典 `sl`。

## qxw completion（shell 补全）

`qxw` 与每个 `qxw-*` 都是 Click 写的，原生支持 `_CMDNAME_COMPLETE=<shell>_source` 生成补全。`qxw completion` 把它们全部枚举一次、合并成单文件，并往 rc 里追加一段被 `# >>> qxw-completion >>>` 包围的 source 行。

```bash
# 自动检测 $SHELL 写入并注入 rc（改 rc 前会确认；-y 跳过）
qxw completion install
qxw completion install -y

# 手动指定 shell（跨 shell 装时用）
qxw completion install --shell zsh
qxw completion install --shell bash -y

# 只打印脚本到 stdout，不落盘
qxw completion show --shell zsh
qxw completion show --shell bash > /tmp/qxw.bash

# 看当前安装状态（路径 / 是否已注入 / 收录了哪些命令）
qxw completion status

# 干净卸载（删脚本文件 + 从 rc 里剔除 source 块）
qxw completion uninstall
qxw completion uninstall -y
```

补全文件落盘到 `~/.config/qxw/completions/qxw.<shell>`。装完执行 `source ~/.zshrc`（或重开终端）即生效。

### 命令更新后

每次新增 / 重命名 / 删除 `qxw-*` 命令后，**重跑一次 `qxw completion install -y`** 即可（脚本整体覆盖，不会重复注入 rc）。

### 常见踩坑

- **zsh + oh-my-zsh 补全没生效**：把 `# >>> qxw-completion >>>` 块整体剪到 `source $ZSH/oh-my-zsh.sh` 之后，或在块前加 `autoload -Uz compinit && compinit`。原因：oh-my-zsh 自带的 compinit 会清掉之前注册的 compdef。
- **macOS 自带 `/bin/bash` 是 3.2，Click 警告 "Shell completion is not supported for Bash versions older than 4.4"**：`brew install bash` 升级到 5.x 即可，或者直接换 zsh。
- **`qxw completion status` 报告"跳过命令"**：某个 `qxw-*` 在 import 阶段抛了异常（多半是可选依赖缺失，比如没装 Pillow / rawpy 却给 `qxw-image` 生成补全）。补全脚本对其它命令仍然有效；跳过原因会打印出来。
- **想自己接管 rc**：`qxw completion show --shell zsh > some/path/qxw.zsh`，然后自己在 rc 里 source，绕开 `qxw completion` 的 rc 管理。

## RC 文件选择规则

| Shell | rc 路径 |
|-------|---------|
| zsh | `~/.zshrc` |
| bash (macOS) | 优先 `~/.bash_profile`，存在同名 `~/.bashrc` 时回退 |
| bash (Linux) | `~/.bashrc` |

不存在时 `install` 会自动创建。
