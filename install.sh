#!/usr/bin/env bash
# ============================================================
# QXW 一键安装脚本
#
# 功能：
#   - 自动检测操作系统和包管理器
#   - 自动安装 Python >= 3.10（如缺失）
#   - 自动安装 pipx（如缺失）
#   - 通过 pipx 全局安装 qxw 工具集
#   - 支持开发模式安装（--dev）
#   - 支持强制重装（--force）
#   - 支持可选的 PDF 导出依赖（--pdf）
#
# 用法：
#   bash install.sh              # 标准安装
#   bash install.sh --dev        # 开发模式（editable + dev 依赖）
#   bash install.sh --force      # 强制重装
#   bash install.sh --pdf        # 同时安装 PDF 导出依赖（weasyprint）
#   bash install.sh --uninstall  # 卸载 qxw
# ============================================================

set -euo pipefail

# ======================== 颜色定义 ========================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # 恢复默认

# ======================== 工具函数 ========================

info()    { echo -e "${BLUE}[信息]${NC} $*"; }
success() { echo -e "${GREEN}[完成]${NC} $*"; }
warn()    { echo -e "${YELLOW}[警告]${NC} $*"; }
error()   { echo -e "${RED}[错误]${NC} $*" >&2; }
step()    { echo -e "\n${CYAN}${BOLD}>>> $*${NC}"; }

die() {
    error "$@"
    exit 1
}

# 检查命令是否存在
has_cmd() {
    command -v "$1" &>/dev/null
}

# ======================== 参数解析 ========================

MODE="pipx"          # pipx | dev
FORCE=false
INSTALL_PDF=false
UNINSTALL=false

for arg in "$@"; do
    case "$arg" in
        --dev)       MODE="dev" ;;
        --force)     FORCE=true ;;
        --pdf)       INSTALL_PDF=true ;;
        --uninstall) UNINSTALL=true ;;
        --help|-h)
            echo "用法: bash install.sh [选项]"
            echo ""
            echo "选项:"
            echo "  --dev        开发模式安装（editable + dev 依赖）"
            echo "  --force      强制重装（覆盖已有安装）"
            echo "  --pdf        同时安装 PDF 导出依赖（weasyprint，用于 qxw-serve gitbook 的 PDF 下载）"
            echo "  --uninstall  卸载 qxw"
            echo "  --help, -h   显示此帮助信息"
            exit 0
            ;;
        *)
            die "未知参数: $arg（使用 --help 查看帮助）"
            ;;
    esac
done

# ======================== 环境检测 ========================

detect_os() {
    OS="unknown"
    DISTRO="unknown"
    PKG_MGR="unknown"

    case "$(uname -s)" in
        Darwin)
            OS="macos"
            DISTRO="macos"
            if has_cmd brew; then
                PKG_MGR="brew"
            else
                PKG_MGR="none"
            fi
            ;;
        Linux)
            OS="linux"
            if [ -f /etc/os-release ]; then
                # shellcheck source=/dev/null
                . /etc/os-release
                DISTRO="${ID:-unknown}"
            elif [ -f /etc/redhat-release ]; then
                DISTRO="rhel"
            fi

            if has_cmd apt-get; then
                PKG_MGR="apt"
            elif has_cmd dnf; then
                PKG_MGR="dnf"
            elif has_cmd yum; then
                PKG_MGR="yum"
            elif has_cmd pacman; then
                PKG_MGR="pacman"
            elif has_cmd apk; then
                PKG_MGR="apk"
            elif has_cmd zypper; then
                PKG_MGR="zypper"
            elif has_cmd brew; then
                PKG_MGR="brew"
            else
                PKG_MGR="none"
            fi
            ;;
        *)
            die "不支持的操作系统: $(uname -s)"
            ;;
    esac
}

print_env_info() {
    step "环境检测"
    info "操作系统:   ${OS}"
    info "发行版:     ${DISTRO}"
    info "包管理器:   ${PKG_MGR}"
    info "架构:       $(uname -m)"
    info "安装模式:   ${MODE}"
    [ "$FORCE" = true ]       && info "强制重装:   是"
    [ "$INSTALL_PDF" = true ] && info "PDF 导出:   是"
}

# ======================== 前置依赖安装 ========================

# 根据包管理器执行安装命令
pkg_install() {
    local packages=("$@")
    info "正在安装系统包: ${packages[*]}"

    case "$PKG_MGR" in
        brew)
            brew install "${packages[@]}"
            ;;
        apt)
            sudo apt-get update -qq
            sudo apt-get install -y "${packages[@]}"
            ;;
        dnf)
            sudo dnf install -y "${packages[@]}"
            ;;
        yum)
            sudo yum install -y "${packages[@]}"
            ;;
        pacman)
            sudo pacman -Sy --noconfirm "${packages[@]}"
            ;;
        apk)
            sudo apk add "${packages[@]}"
            ;;
        zypper)
            sudo zypper install -y "${packages[@]}"
            ;;
        *)
            die "无可用的包管理器，请手动安装: ${packages[*]}"
            ;;
    esac
}

# ======================== Homebrew 安装 ========================

ensure_brew() {
    if [ "$OS" = "macos" ] && ! has_cmd brew; then
        step "安装 Homebrew"
        warn "未检测到 Homebrew，正在安装..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

        # Apple Silicon 路径处理
        if [ -f /opt/homebrew/bin/brew ]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
        elif [ -f /usr/local/bin/brew ]; then
            eval "$(/usr/local/bin/brew shellenv)"
        fi

        if has_cmd brew; then
            success "Homebrew 安装成功"
            PKG_MGR="brew"
        else
            die "Homebrew 安装失败，请手动安装: https://brew.sh"
        fi
    fi
}

# ======================== Python 检测与安装 ========================

# 查找可用的 Python >= 3.10，返回完整路径
find_python() {
    local candidates=("python3" "python3.14" "python3.13" "python3.12" "python3.11" "python3.10" "python")
    for cmd in "${candidates[@]}"; do
        if has_cmd "$cmd"; then
            local ver
            ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
            if [ -n "$ver" ]; then
                local major minor
                major=$(echo "$ver" | cut -d. -f1)
                minor=$(echo "$ver" | cut -d. -f2)
                if [ "$major" -eq 3 ] && [ "$minor" -ge 10 ]; then
                    PYTHON_CMD="$cmd"
                    PYTHON_VER="$ver"
                    return 0
                fi
            fi
        fi
    done
    return 1
}

ensure_python() {
    step "检测 Python"

    if find_python; then
        success "已找到 Python ${PYTHON_VER} (${PYTHON_CMD})"
        return 0
    fi

    warn "未找到 Python >= 3.10，正在尝试自动安装..."

    case "$PKG_MGR" in
        brew)
            pkg_install python@3.12
            ;;
        apt)
            # Ubuntu/Debian: 尝试直接安装，若仓库无 3.10+ 则添加 deadsnakes PPA
            if ! sudo apt-get install -y python3.12 python3.12-venv python3.12-dev 2>/dev/null; then
                info "添加 deadsnakes PPA..."
                sudo apt-get install -y software-properties-common
                sudo add-apt-repository -y ppa:deadsnakes/ppa
                sudo apt-get update -qq
                sudo apt-get install -y python3.12 python3.12-venv python3.12-dev
            fi
            ;;
        dnf)
            pkg_install python3.12 python3.12-devel
            ;;
        yum)
            pkg_install python3 python3-devel
            ;;
        pacman)
            pkg_install python
            ;;
        apk)
            pkg_install python3 python3-dev
            ;;
        zypper)
            pkg_install python312 python312-devel
            ;;
        *)
            die "无法自动安装 Python，请手动安装 Python >= 3.10 后重试"
            ;;
    esac

    # 重新检测
    if find_python; then
        success "Python ${PYTHON_VER} 安装成功 (${PYTHON_CMD})"
    else
        die "Python 安装后仍未找到 >= 3.10 版本，请手动检查"
    fi
}

# ======================== pip 确保可用 ========================

ensure_pip() {
    step "检测 pip"

    if "$PYTHON_CMD" -m pip --version &>/dev/null; then
        success "pip 已就绪"
        return 0
    fi

    warn "pip 不可用，正在安装..."

    # 方法 1: ensurepip
    if "$PYTHON_CMD" -m ensurepip --upgrade &>/dev/null; then
        success "pip 通过 ensurepip 安装成功"
        return 0
    fi

    # 方法 2: 系统包管理器
    case "$PKG_MGR" in
        apt)    pkg_install python3-pip ;;
        dnf)    pkg_install python3-pip ;;
        yum)    pkg_install python3-pip ;;
        pacman) pkg_install python-pip ;;
        apk)    pkg_install py3-pip ;;
        zypper) pkg_install python3-pip ;;
        brew)   ;; # brew 安装的 Python 自带 pip
    esac

    # 方法 3: get-pip.py
    if ! "$PYTHON_CMD" -m pip --version &>/dev/null; then
        info "尝试通过 get-pip.py 安装..."
        curl -sSL https://bootstrap.pypa.io/get-pip.py | "$PYTHON_CMD" -
    fi

    if "$PYTHON_CMD" -m pip --version &>/dev/null; then
        success "pip 安装成功"
    else
        die "pip 安装失败，请手动安装"
    fi
}

# ======================== pipx 安装 ========================

ensure_pipx() {
    step "检测 pipx"

    if has_cmd pipx; then
        success "pipx 已就绪 ($(pipx --version 2>/dev/null || echo '版本未知'))"
        return 0
    fi

    warn "未检测到 pipx，正在安装..."

    case "$PKG_MGR" in
        brew)
            brew install pipx
            ;;
        apt)
            # 优先用系统包，fallback 到 pip
            if ! sudo apt-get install -y pipx 2>/dev/null; then
                "$PYTHON_CMD" -m pip install --user pipx
            fi
            ;;
        dnf)
            if ! sudo dnf install -y pipx 2>/dev/null; then
                "$PYTHON_CMD" -m pip install --user pipx
            fi
            ;;
        pacman)
            pkg_install python-pipx
            ;;
        *)
            "$PYTHON_CMD" -m pip install --user pipx
            ;;
    esac

    # 确保 pipx 可执行路径在 PATH 中
    if ! has_cmd pipx; then
        info "执行 pipx ensurepath..."
        "$PYTHON_CMD" -m pipx ensurepath 2>/dev/null || true

        # 尝试常见路径
        local pipx_paths=(
            "$HOME/.local/bin/pipx"
            "$HOME/Library/Python/${PYTHON_VER}/bin/pipx"
        )
        for p in "${pipx_paths[@]}"; do
            if [ -x "$p" ]; then
                export PATH="$(dirname "$p"):$PATH"
                break
            fi
        done
    fi

    if has_cmd pipx; then
        success "pipx 安装成功"
    else
        die "pipx 安装失败。请手动安装后重试：${PYTHON_CMD} -m pip install --user pipx && pipx ensurepath"
    fi
}

# ======================== Git 检测 ========================

ensure_git() {
    if has_cmd git; then
        return 0
    fi
    step "安装 Git"
    pkg_install git
    if has_cmd git; then
        success "Git 安装成功"
    else
        die "Git 安装失败，请手动安装"
    fi
}

# ======================== QXW 安装 ========================

# 获取脚本所在目录（即项目根目录）
get_project_dir() {
    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if [ -f "${script_dir}/pyproject.toml" ]; then
        PROJECT_DIR="$script_dir"
    else
        die "找不到 pyproject.toml，请在 qxw 项目根目录下运行此脚本"
    fi
}

install_qxw_pipx() {
    step "通过 pipx 安装 QXW"

    local pipx_args=("install" "${PROJECT_DIR}")

    if [ "$FORCE" = true ]; then
        pipx_args=("install" "${PROJECT_DIR}" "--force")
    fi

    # 指定 Python 版本
    pipx_args+=("--python" "$PYTHON_CMD")

    info "执行: pipx ${pipx_args[*]}"
    if pipx "${pipx_args[@]}"; then
        success "QXW 通过 pipx 安装成功"
    else
        # 已安装时的友好提示
        if pipx list 2>/dev/null | grep -q "qxw"; then
            warn "QXW 已安装，如需重装请使用 --force 参数"
            return 0
        fi
        die "pipx 安装失败"
    fi

    # 安装可选的 PDF 导出依赖（注入到 pipx 虚拟环境）
    if [ "$INSTALL_PDF" = true ]; then
        step "安装 PDF 导出依赖"
        info "注入 weasyprint 到 qxw 的 pipx 环境..."
        pipx inject qxw weasyprint
        success "PDF 导出依赖安装完成"
    fi
}

install_qxw_dev() {
    step "以开发模式安装 QXW"

    local venv_dir="${PROJECT_DIR}/.venv"

    # 创建虚拟环境
    if [ ! -d "$venv_dir" ]; then
        info "创建虚拟环境: ${venv_dir}"
        "$PYTHON_CMD" -m venv "$venv_dir"
    else
        info "虚拟环境已存在: ${venv_dir}"
    fi

    local pip_cmd="${venv_dir}/bin/pip"

    # 升级 pip
    "$venv_dir/bin/python" -m pip install --upgrade pip

    # 安装开发依赖
    info "安装 QXW（开发模式 + dev 依赖）..."
    "$pip_cmd" install -e ".[dev]"

    if [ "$INSTALL_PDF" = true ]; then
        step "安装 PDF 导出依赖"
        "$pip_cmd" install -e ".[pdf]"
        success "PDF 导出依赖安装完成"
    fi

    success "开发模式安装完成"
    echo ""
    info "激活虚拟环境: source ${venv_dir}/bin/activate"
}

# ======================== 卸载 ========================

uninstall_qxw() {
    step "卸载 QXW"

    if has_cmd pipx && pipx list 2>/dev/null | grep -q "qxw"; then
        pipx uninstall qxw
        success "已通过 pipx 卸载 QXW"
    else
        warn "未检测到 pipx 安装的 QXW"
    fi

    echo ""
    info "注意: 用户配置目录 ~/.config/qxw/ 未被删除，如需清理请手动执行:"
    info "  rm -rf ~/.config/qxw/"
}

# ======================== 安装验证 ========================

verify_install() {
    step "验证安装"

    local all_ok=true

    # 获取所有注册的命令
    local commands=("qxw" "qxw-chat" "qxw-chat-provider" "qxw-serve" "qxw-image" "qxw-markdown" "qxw-str")

    for cmd in "${commands[@]}"; do
        if has_cmd "$cmd"; then
            echo -e "  ${GREEN}✓${NC} ${cmd}"
        else
            echo -e "  ${RED}✗${NC} ${cmd}"
            all_ok=false
        fi
    done

    echo ""
    if [ "$all_ok" = true ]; then
        success "所有命令均可用"
    else
        warn "部分命令不可用"
        if [ "$MODE" = "pipx" ]; then
            info "尝试执行: pipx ensurepath && 重启终端"
        else
            info "请确认已激活虚拟环境: source .venv/bin/activate"
        fi
    fi
}

# ======================== 安装摘要 ========================

print_summary() {
    echo ""
    echo -e "${BOLD}============================================${NC}"
    echo -e "${BOLD}  QXW 安装完成${NC}"
    echo -e "${BOLD}============================================${NC}"
    echo ""
    if [ "$MODE" = "pipx" ]; then
        info "安装方式:  pipx 全局安装"
        info "更新命令:  pipx install ${PROJECT_DIR} --force"
        info "卸载命令:  pipx uninstall qxw"
    else
        info "安装方式:  开发模式（虚拟环境）"
        info "激活环境:  source ${PROJECT_DIR}/.venv/bin/activate"
        info "更新依赖:  pip install -e \".[dev]\""
    fi
    echo ""
    info "快速体验:"
    info "  qxw list           # 查看所有可用命令"
    info "  qxw hello          # 运行示例命令"
    info "  qxw hello --tui    # TUI 交互模式"
    info "  qxw completion install  # 安装 Shell 补全"
    echo ""
}

# ======================== 主流程 ========================

main() {
    echo -e "${BOLD}"
    echo "  ╔═══════════════════════════════════════╗"
    echo "  ║       QXW 命令行工具集 · 安装脚本     ║"
    echo "  ╚═══════════════════════════════════════╝"
    echo -e "${NC}"

    # 环境检测
    detect_os
    get_project_dir

    # 卸载模式
    if [ "$UNINSTALL" = true ]; then
        uninstall_qxw
        exit 0
    fi

    print_env_info

    # macOS 确保 Homebrew 可用
    [ "$OS" = "macos" ] && ensure_brew

    # 前置依赖
    ensure_git
    ensure_python
    ensure_pip

    # 按模式安装
    case "$MODE" in
        pipx)
            ensure_pipx
            install_qxw_pipx
            ;;
        dev)
            install_qxw_dev
            ;;
    esac

    # 验证
    verify_install
    print_summary
}

main "$@"
