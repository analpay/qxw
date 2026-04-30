---
name: qxw-str
description: 使用 `qxw-str` 命令统计字符串长度。`qxw-str len` 同时给出**字符数（Unicode 码点）**和 **UTF-8 字节数**，支持位置参数和从 stdin 读取，便于 `echo ... | qxw-str len` 或 `cat file | qxw-str len` 的管道用法。`-q / -b` 让脚本可以直接 `LEN=$(qxw-str len -q "...")` 拿到纯数字。当用户问"这段中文几个字 / 几个字符 / 占多少字节 / UTF-8 字节数 / 一行 markdown 多长 / emoji 算几个字符 / 中文 1 个字几字节"，或直接念到 `qxw-str len` 时，使用此 skill。
---

# qxw-str

字符串工具集，目前只有 `len` 子命令。

## qxw-str len

```bash
qxw-str len "hello"                    # 直接传字符串
qxw-str len "你好，世界"                # 中文 / emoji 都按 Unicode 码点算
echo -n "hello world" | qxw-str len    # 从 stdin 读取
cat README.md | qxw-str len            # 文件喂入
```

### 参数

| 参数 | 缩写 | 默认 | 说明 |
|------|------|------|------|
| `<text>` | - | 缺省时从 stdin 读取 | 待统计字符串（可选位置参数） |
| `--quiet` | `-q` | false | 仅输出**字符数**（纯数字），便于 `$(...)` 捕获 |
| `--bytes` | `-b` | false | 仅输出 **UTF-8 字节数**（纯数字），便于 `$(...)` 捕获 |

`--quiet` 与 `--bytes` 互斥；同时指定以错误码 2 退出。

### 默认输出（Rich 表格）

```
$ qxw-str len "你好世界"
   字符串长度统计
┌──────────────┬────┐
│ 字符数        │ 4  │
│ UTF-8 字节数  │ 12 │
└──────────────┴────┘
```

### 脚本场景

```bash
LEN=$(qxw-str len -q "你好世界")
echo "共 $LEN 个字符"          # 共 4 个字符

BYTES=$(qxw-str len -b "你好世界")
echo "占用 $BYTES 字节"        # 占用 12 字节
```

### 统计口径

- **字符数**：Python `len(str)`，按 Unicode 码点计算。一个汉字 = 1，常见 emoji = 1，但**组合 emoji**（如 👨‍👩‍👧‍👦）会被拆成多个码点
- **UTF-8 字节数**：`str.encode("utf-8")` 后的字节长度。ASCII = 1 字节，中文 = 3 字节，大部分 emoji = 4 字节
