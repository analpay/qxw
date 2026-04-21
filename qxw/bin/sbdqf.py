"""qxw sbdqf 子命令入口

一只老鼠从终端屏幕上飞速穿过，类似于经典的 sl 命令效果。
就像 sl 一样，Ctrl+C 无法中断——老鼠必须跑完全程！

作为 ``qxw`` 命令组的子命令使用（原 ``qxw-sbdqf`` 独立命令已合并）：

用法:
    qxw sbdqf          # 运行动画
    qxw sbdqf --help   # 查看帮助信息
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
    _bubble_text = " mimimimimimimimi...... "
    _bubble_border = "_" * len(_bubble_text)
    frames = []
    for tail in _TAIL_PATTERNS:
        frame = [
            f"  {_bubble_border}",
            f" <{_bubble_text}>",
            f"  {_bubble_border}",
            " /",
            "  ()()____",
            "  @@      \\",
            f"o<_.m__m;_/{tail}`",
        ]
        frames.append(frame)
    return frames


# ============================================================
# 动画引擎
# ============================================================


def _run_single_pass(
    stdscr: curses.window,
    frames: list[list[str]],
    mouse_width: int,
    mouse_height: int,
    deadline: float,
) -> bool:
    max_y, max_x = stdscr.getmaxyx()
    col = max_x
    end_col = -mouse_width
    start_row = (max_y - mouse_height) // 2
    frame_idx = 0

    while col > end_col:
        if time.monotonic() >= deadline:
            return True

        stdscr.erase()

        # 每 3 步切换帧，尾巴动画节奏更自然
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

    return False


def _run_animation(stdscr: curses.window, rounds: int | None, duration: int | None) -> None:
    """运行老鼠穿越动画"""
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(0)

    original_sigint = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    try:
        frames = _build_frames()
        mouse_width = max(len(line) for frame in frames for line in frame)
        mouse_height = max(len(frame) for frame in frames)
        max_y, _ = stdscr.getmaxyx()

        if max_y < mouse_height:
            return

        deadline = time.monotonic() + duration if duration else float("inf")
        max_rounds = rounds if rounds else (1 if not duration else None)
        completed = 0

        while max_rounds is None or completed < max_rounds:
            timed_out = _run_single_pass(stdscr, frames, mouse_width, mouse_height, deadline)
            if timed_out:
                break
            completed += 1

    finally:
        signal.signal(signal.SIGINT, original_sigint)


# ============================================================
# CLI 入口 (Click)
# ============================================================


@click.command(
    name="sbdqf",
    help="🐭 一只老鼠从终端屏幕上飞速穿过（致敬经典 sl 命令）",
    epilog="和 sl 一样，Ctrl+C 无法中断——老鼠必须跑完全程！",
)
@click.version_option(
    version=__version__,
    prog_name="qxw sbdqf",
    message="%(prog)s 版本 %(version)s",
)
@click.option("-r", "--rounds", default=None, type=click.IntRange(min=1), help="老鼠跑过屏幕的轮次（不填则不限轮次）")
@click.option("-d", "--duration", default=None, type=click.IntRange(min=1), help="动画最长持续时间/秒（不填则不限时间）")
def main(rounds: int | None, duration: int | None) -> None:
    """老鼠穿越动画命令

    一只大老鼠从屏幕右边飞速跑到左边，模仿经典的 sl 命令效果。
    就像 sl 一样，你必须耐心等待老鼠跑完全程！

    \b
    示例:
        qxw sbdqf              # 跑 1 轮
        qxw sbdqf -r 5         # 跑 5 轮
        qxw sbdqf -d 30        # 最多跑 30 秒
        qxw sbdqf -r 100 -d 10 # 跑 100 轮或 10 秒，先到先停
    """
    try:
        curses.wrapper(lambda stdscr: _run_animation(stdscr, rounds, duration))
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
