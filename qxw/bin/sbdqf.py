"""qxw-sbdqf 命令入口

一只老鼠从终端屏幕上飞速穿过，类似于经典的 sl 命令效果。
就像 sl 一样，Ctrl+C 无法中断——老鼠必须跑完全程！

用法:
    qxw-sbdqf          # 运行动画
    qxw-sbdqf --help   # 查看帮助信息
"""

import curses
import signal
import sys
import time

import click

from qxw import __version__
from qxw.library.base.exceptions import QxwError
from qxw.library.base.logger import get_logger

logger = get_logger("qxw.sbdqf")


# ============================================================
# 老鼠 ASCII 艺术 - 面朝左，从右向左穿过屏幕
# ============================================================

# 两种尾巴波形，交替产生尾巴摆动效果
_TAIL_PATTERNS = [
    "~" * 30,
    "~^" * 15,
]


def _build_frames() -> list[list[str]]:
    """构建老鼠动画帧

    共 2 帧交替展示，尾巴波形交替摆动。
    """
    frames = []
    for tail in _TAIL_PATTERNS:
        frame = [
            "  ()()____",
            "  @@      \\",
            f"o<_.m__m;_/{tail}`",
        ]
        frames.append(frame)
    return frames


# ============================================================
# 动画引擎
# ============================================================


def _run_animation(stdscr: curses.window) -> None:
    """运行老鼠穿越动画

    使用 curses 控制终端，让一只 ASCII 老鼠从屏幕右边跑到左边。
    动画期间屏蔽 SIGINT，必须等老鼠跑完。
    """
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(0)

    original_sigint = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    try:
        frames = _build_frames()
        max_y, max_x = stdscr.getmaxyx()

        mouse_width = max(len(line) for frame in frames for line in frame)
        mouse_height = max(len(frame) for frame in frames)

        if max_y < mouse_height:
            return

        col = max_x
        end_col = -mouse_width
        start_row = (max_y - mouse_height) // 2

        frame_idx = 0

        while col > end_col:
            stdscr.erase()

            # 每 3 步切换帧，腿部动画节奏更自然
            visual_frame = (frame_idx // 3) % len(frames)
            frame = frames[visual_frame]

            for row_offset, line in enumerate(frame):
                row = start_row + row_offset
                if row < 0 or row >= max_y:
                    continue

                if col >= 0:
                    visible_end = min(len(line), max_x - col)
                    if visible_end > 0:
                        try:
                            stdscr.addstr(row, col, line[:visible_end])
                        except curses.error:
                            pass
                else:
                    clip = -col
                    if clip < len(line):
                        visible = line[clip:]
                        try:
                            stdscr.addstr(row, 0, visible[:max_x])
                        except curses.error:
                            pass

            stdscr.refresh()
            time.sleep(0.035)

            col -= 3
            frame_idx += 1

    finally:
        signal.signal(signal.SIGINT, original_sigint)


# ============================================================
# CLI 入口 (Click)
# ============================================================


@click.command(
    name="qxw-sbdqf",
    help="🐭 一只老鼠从终端屏幕上飞速穿过（致敬经典 sl 命令）",
    epilog="和 sl 一样，Ctrl+C 无法中断——老鼠必须跑完全程！",
)
@click.version_option(
    version=__version__,
    prog_name="qxw-sbdqf",
    message="%(prog)s 版本 %(version)s",
)
def main() -> None:
    """老鼠穿越动画命令

    一只大老鼠从屏幕右边飞速跑到左边，模仿经典的 sl 命令效果。
    就像 sl 一样，你必须耐心等待老鼠跑完全程！

    \b
    示例:
        qxw-sbdqf       # 运行动画
    """
    try:
        curses.wrapper(_run_animation)
    except QxwError as e:
        logger.error("命令执行失败: %s", e.message)
        click.echo(f"错误: {e.message}", err=True)
        sys.exit(e.exit_code)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.exception("未预期的错误")
        click.echo(f"未预期的错误: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
