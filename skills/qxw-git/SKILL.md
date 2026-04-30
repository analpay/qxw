---
name: qxw-git
description: 使用 `qxw-git archive` 把 git 工作树打包为 tar / tar.gz / tar.bz2 / tar.xz / zip。包内**不含 `.git` 目录**（仅 `git ls-files` 跟踪的文件，自动跳 `.gitignore` 命中的与未跟踪文件），git-lfs 文件会先 `git lfs pull` **实体化为真实内容**（不是指针文件），默认还会自动排除 `.gitattributes`，可叠加 `-e/--exclude` 排除更多文件 / 目录 / glob。`-r/--ref` 指定分支 / tag / commit 时通过临时 worktree 签出，**主工作树不被切换或污染**。当用户说"把仓库打个包给同事 / 打 tar / 不要 .git / 排除 docs / 排除 .md / git 仓库归档 / LFS 文件实体化打包 / 打某个 tag 的源码 / 不切分支的前提下打包另一个分支 / git archive 但要带 LFS"，或直接念到 `qxw-git archive` 时，使用此 skill。
---

# qxw-git

git 仓库工具集，目前只有 `archive` 子命令。

## qxw-git archive

把 git 工作树（或某个 ref）打包成 tar / zip。**自动排除 `.git` 与未跟踪文件**，**LFS 自动 pull**，主工作树不被切换。

### 基本用法

```bash
qxw-git archive                                # 当前 git 仓库 → ../<repo>.tar
qxw-git archive -f tar.gz                      # 换格式
qxw-git archive -f tar.bz2
qxw-git archive -f tar.xz
qxw-git archive -f zip

qxw-git archive -f zip -o /tmp/myrepo.zip --prefix release-1.0   # 自定义输出 + 包内顶层目录名
qxw-git archive --no-lfs                       # 跳过 git lfs pull
qxw-git archive /path/to/repo                  # 接受工作树内任意子路径，自动定位仓库根

# 指定 ref（不动主工作树）
qxw-git archive -r main
qxw-git archive -r v1.2.0 -f tar.gz
qxw-git archive --ref feature/foo              # / 会被 sanitize 进文件名

# 排除项（默认已排 .gitattributes）
qxw-git archive -e docs                        # 整个 docs/ 目录
qxw-git archive -e '*.md' -e tests/fixtures
qxw-git archive -e config/local.yaml           # 单文件精确路径

# 脚本场景：仅输出包路径
ARCHIVE=$(qxw-git archive --quiet)
echo "$ARCHIVE"
```

### 参数

| 参数 | 缩写 | 默认 | 说明 |
|------|------|------|------|
| `[REPO]` | - | 当前工作目录 | 仓库路径（接受工作树内任意子路径，会 `git rev-parse --show-toplevel` 找仓库根） |
| `--format` | `-f` | `tar` | `tar` / `tar.gz` / `tar.bz2` / `tar.xz` / `zip` |
| `--output` | `-o` | `<repo父目录>/<repo名>.<格式>`；带 `--ref` 时为 `<repo>-<sanitized_ref>.<格式>` | 输出文件路径 |
| `--prefix` | - | 仓库目录名 | 包内顶层目录名（同 `git archive --prefix=`） |
| `--ref` | `-r` | 当前工作树 | 分支 / tag / commit-ish；任何 `git rev-parse` 能解析的引用都行 |
| `--no-lfs` | - | false | 跳过 `git lfs pull`；仓库引用 LFS 但 git-lfs 不可用时用此项绕过 |
| `--exclude` | `-e` | `.gitattributes`（默认追加） | 可重复。精确路径（`a/b.txt`）、目录前缀（`docs`）、glob（`*.md` / `test_*.py`） |
| `--quiet` | `-q` | false | 仅输出生成包路径 |

### 打包规则

- **不含 .git**：内容由 `git ls-files -z` 决定，自动跳过 `.git`、未跟踪文件、`.gitignore` 命中的文件
- **LFS 实体化**：先尝试 `git lfs ls-files`（可用时直接判仓库是否有 LFS 文件）；不可用时再扫 `.gitattributes` 是否含 `filter=lfs`
- **子模块 / 缺失文件**：静默跳过 + 写一条 warning，不会让整个打包失败
- **顶层目录**：默认 = 仓库目录名，可用 `--prefix` 覆盖（语义同 `git archive --prefix=release/`）
- **`--ref` 内部实现**：`git worktree add --detach <ref> <临时目录>` 在临时目录里签出，**主工作树不被切换 / 污染**；签出后在临时目录里跑 LFS pull、打包，结束自动 `git worktree remove --force` 清理。共享 `.git/objects` 与 `.git/lfs`，已 pull 过的对象不会重复下载
- **`--ref` 输出名**：缺省 `<repo>-<sanitized_ref>.<fmt>`；`/` `\` `:` 与空白 → `_`（`feature/foo` → `feature_foo`）
- **排除规则**：默认追加 `.gitattributes`；`-e` 可叠加：
  1. 含 `*` `?` `[` 视为 glob（`*.md` 既匹配 `readme.md` 也匹配 `docs/readme.md`）
  2. 否则按路径精确匹配 `a/b/c.txt` 或目录前缀 `docs` 命中 `docs/...`
  3. 路径含 `..` 直接拒绝
  4. 所有跟踪文件都被排除时报错（避免空包）

### 输出示例

```
$ qxw-git archive -r v1.2.0 -f zip -o /tmp/myrepo.zip
                  git 仓库打包结果
┌─────────────┬─────────────────────────────────┐
│ 输出路径    │ /tmp/myrepo.zip                 │
│ Ref         │ v1.2.0                          │
│ 文件数      │ 128                             │
│ 包大小      │ 4.32 MB                         │
│ LFS 已 pull │ 是                              │
│ 已排除      │ 1                               │
└─────────────┴─────────────────────────────────┘
```

### 退出码

| 退出码 | 触发场景 |
|--------|----------|
| 0 | 打包成功 |
| 2 | Click 参数校验失败（如 `--format` 不在允许列表内） |
| 4 | git 命令执行失败：不在 git 仓库 / 找不到 git 命令 / 仓库需要 LFS 但 git-lfs 不可用 / 排除规则把所有文件都过滤掉（`CommandError`） |
| 6 | 路径不存在 / 路径不是目录 / 不支持的打包格式 / 空 prefix / `--ref` 不存在 / 排除项含 `..` 越界（`ValidationError`） |
| 130 | 用户 Ctrl-C |
| 1 | 未预期的内部错误 |

> 仓库引用了 LFS 但当前环境没装 git-lfs 时，命令**会拒绝继续**——避免输出"看起来是 LFS 文件、实际只是指针"的损坏包。如果你确实只想要个普通 tar，加 `--no-lfs` 即可。

## 与 `git archive` 的区别

| 维度 | `git archive` | `qxw-git archive` |
|------|--------------|-------------------|
| 含 `.git`？ | 否 | 否 |
| 自动 pull LFS | ❌（输出指针文件） | ✅（默认开） |
| 默认排除 `.gitattributes` | ❌ | ✅ |
| 自定义排除 glob / 路径 | 仅靠 `.gitattributes export-ignore` | `-e` 直接传 |
| 跨 ref 打包 | ✅ | ✅（用临时 worktree，主工作树不动） |
| 输出路径默认 | stdout / `-o` | 自动派生到 `<repo父目录>/...` |
