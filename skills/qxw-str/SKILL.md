---
name: qxw-str
description: 使用 `qxw-str` 命令做字符串处理。`qxw-str len` 同时给出**字符数（Unicode 码点）**和 **UTF-8 字节数**；`qxw-str encrypt` / `qxw-str decrypt` 用 **AES-256-GCM** 对称加解密，密钥来自环境变量 `QXW_STR_ENCRYPT_KEY`，缺省回退到 `"sbdqf"`，也可用 `-k` 显式指定。支持位置参数和从 stdin 读取，便于 `echo ... | qxw-str len` 或管道 `CT=$(qxw-str encrypt -q "secret")` 的用法。当用户问"这段中文几个字 / 几个字符 / 占多少字节 / UTF-8 字节数"，或要"加密一段字符串 / 解密一段密文 / AES 加密 / 对称加密 / GCM 加密 / 给字符串加个密 / 还原密文 / 加密 secret / 解开 base64 密文"，或直接念到 `qxw-str len` / `qxw-str encrypt` / `qxw-str decrypt` 时，使用此 skill。
---

# qxw-str

字符串工具集，提供 `len` / `encrypt` / `decrypt` 三个子命令。

## 子命令一览

| 子命令 | 用途 |
|--------|------|
| `len` | 统计输入字符串的字符数（Unicode 码点）与 UTF-8 字节数 |
| `encrypt` | 用 AES-256-GCM 加密字符串，输出 base64 密文 |
| `decrypt` | 用 AES-256-GCM 解密 base64 密文，还原明文 |

---

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

---

## qxw-str encrypt

```bash
qxw-str encrypt "hello"               # 表格输出密文
qxw-str encrypt "secret" -q           # 仅输出密文（单行 base64）
echo "hello" | qxw-str encrypt -q     # 从 stdin 读取
qxw-str encrypt "x" -k "mykey" -q     # 显式指定密钥
```

### 参数

| 参数 | 缩写 | 默认 | 说明 |
|------|------|------|------|
| `<text>` | - | 缺省时从 stdin 读取 | 待加密明文（可选位置参数） |
| `--quiet` | `-q` | false | 仅输出密文（单行 base64），便于 `$(...)` 捕获 |
| `--key` | `-k` | None | 显式指定加密密钥；缺省读取环境变量，再缺省回退 `"sbdqf"` |

### 密钥来源（按优先级）

1. `--key` 参数显式传入
2. 环境变量 `QXW_STR_ENCRYPT_KEY`
3. 默认值 `"sbdqf"`

用户传入的任意长度密钥都会经 **SHA-256 派生**为 32 字节 AES-256 密钥，因此短密钥（如 `"sbdqf"`）也能安全使用。

### 算法与密文格式

- 算法：**AES-256-GCM**（带认证标签的对称加密）
- 密文格式：`base64(nonce || ciphertext || tag)`
  - `nonce`：12 字节随机数
  - `ciphertext`：与明文等长的密文
  - `tag`：16 字节认证标签
- 每次加密使用随机 nonce，因此**同一明文多次加密会得到不同密文**
- 密文可直接传给 `qxw-str decrypt` 还原，无需单独保存 nonce

### 脚本场景

```bash
CT=$(qxw-str encrypt -q "secret")
echo "$CT"                          # 一行 base64 密文

# 用环境变量指定密钥
export QXW_STR_ENCRYPT_KEY="my-secret-key"
qxw-str encrypt "data" -q
```

---

## qxw-str decrypt

```bash
qxw-str decrypt "base64密文"              # 表格输出明文
qxw-str decrypt "base64密文" -q          # 仅输出明文
qxw-str decrypt "$CT" -k "mykey" -q      # 显式指定密钥
echo "$CT" | qxw-str decrypt -q          # 从 stdin 读取
```

### 参数

| 参数 | 缩写 | 默认 | 说明 |
|------|------|------|------|
| `<text>` | - | 缺省时从 stdin 读取 | 待解密密文（可选位置参数） |
| `--quiet` | `-q` | false | 仅输出明文，便于 `$(...)` 捕获 |
| `--key` | `-k` | None | 显式指定解密密钥；缺省读取环境变量，再缺省回退 `"sbdqf"` |

密钥来源与 `encrypt` 一致。**解密时密钥必须与加密时一致**，否则会因 GCM 认证标签校验失败而报错。

### 往返示例

```bash
CT=$(qxw-str encrypt -q "hello")
PT=$(qxw-str decrypt -q "$CT")
echo "$PT"                          # hello
```

---

## 退出码

| 退出码 | 含义 |
|--------|------|
| 0 | 成功 |
| 1 | 未预期的错误 |
| 2 | 参数缺失 / 参数冲突 / 未提供输入且非 stdin |
| 6 | 校验错误（解密失败、密钥不匹配、密文非法、密文被篡改、密文为空等） |
| 130 | 用户 Ctrl-C 中断 |

## 常见踩坑

- **解密报"密钥不匹配或密文已被篡改"**：加密与解密使用的密钥不一致。检查 `-k` 参数或 `QXW_STR_ENCRYPT_KEY` 环境变量是否一致。
- **解密报"密文不是合法的 base64"**：密文在复制粘贴时被截断或混入了非法字符。
- **解密报"密文长度不足"**：密文至少需要 28 字节（12 nonce + 16 tag），过短说明密文不完整。
- **加密后无法用环境变量密钥解密**：加密时用了默认密钥 `"sbdqf"`，但解密时设置了不同的 `QXW_STR_ENCRYPT_KEY`。两边保持一致即可。
- **同一明文每次加密结果不同**：这是 AES-GCM 随机 nonce 的正常行为，不是 bug。
