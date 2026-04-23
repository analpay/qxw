"""qxw.library.services.markdown_service 单元测试

只覆盖纯函数，不触发 java / plantuml.jar / cairosvg。
"""

from __future__ import annotations

import pytest

from qxw.library.services.markdown_service import (
    _inject_svg_background_rect,
    _prepare_plantuml_source,
    extract_plantuml_blocks,
)


class TestExtractPlantumlBlocks:
    def test_支持_plantuml_puml_uml_三种围栏(self) -> None:
        md = (
            "# title\n\n"
            "```plantuml\n@startuml\nA -> B\n@enduml\n```\n\n"
            "段落\n\n"
            "```puml\n@startuml\nC -> D\n@enduml\n```\n\n"
            "```uml\nE -> F\n```\n"
        )
        blocks = extract_plantuml_blocks(md)
        assert len(blocks) == 3
        assert "A -> B" in blocks[0].source
        assert "C -> D" in blocks[1].source
        assert "E -> F" in blocks[2].source

    def test_不匹配其他语言围栏(self) -> None:
        md = "```python\nprint('x')\n```\n"
        assert extract_plantuml_blocks(md) == []

    def test_缩进一致才视为围栏(self) -> None:
        md = (
            "    ```plantuml\n"
            "    @startuml\n"
            "    A -> B\n"
            "    @enduml\n"
            "    ```\n"
        )
        blocks = extract_plantuml_blocks(md)
        assert len(blocks) == 1
        assert blocks[0].indent == "    "

    def test_闭合围栏缩进不一致则整段不匹配(self) -> None:
        md = (
            "    ```plantuml\n"
            "    A -> B\n"
            "```\n"  # 闭合缩进不一致
        )
        assert extract_plantuml_blocks(md) == []

    def test_返回的_start_end_可用于原文替换(self) -> None:
        md = "前\n```plantuml\nA -> B\n```\n后"
        block = extract_plantuml_blocks(md)[0]
        fence = md[block.start : block.end]
        assert fence.startswith("```plantuml")
        assert fence.endswith("```")


class TestPreparePlantumlSource:
    def test_裸内容被_startuml_包裹(self) -> None:
        src = _prepare_plantuml_source("A -> B\n", background="white", font_name="PingFang SC")
        assert src.startswith("@startuml\n")
        assert src.rstrip().endswith("@enduml")
        assert "skinparam backgroundColor white" in src
        assert 'skinparam defaultFontName "PingFang SC"' in src

    def test_已有_startuml_时_skinparam_插在第二行(self) -> None:
        raw = "@startuml\nA -> B\n@enduml\n"
        src = _prepare_plantuml_source(raw, background="black", font_name="HeiTi")

        lines = src.splitlines()
        assert lines[0] == "@startuml"
        assert lines[1] == "skinparam backgroundColor black"
        assert lines[2] == 'skinparam defaultFontName "HeiTi"'
        assert "A -> B" in src
        # 不应重复包裹 @enduml
        assert src.count("@enduml") == 1

    @pytest.mark.parametrize("bg", ["white", "black", "transparent"])
    def test_三种背景都被正确注入(self, bg: str) -> None:
        src = _prepare_plantuml_source("A -> B", background=bg, font_name="X")
        assert f"skinparam backgroundColor {bg}" in src


class TestInjectSvgBackgroundRect:
    def test_普通_SVG_会插入_rect(self) -> None:
        svg = b'<?xml version="1.0"?><svg width="10" height="10"><g/></svg>'
        out = _inject_svg_background_rect(svg, "#ffffff")
        text = out.decode("utf-8")
        assert '<rect width="100%" height="100%" fill="#ffffff"/>' in text
        # rect 应紧跟在 <svg ...> 之后
        assert text.index("<rect") < text.index("<g/>")

    def test_找不到_svg_标签时原样返回(self) -> None:
        raw = b"<notsvg/>"
        assert _inject_svg_background_rect(raw, "#000000") is raw
