from pathlib import Path


def test_markdown_renderer_contains_safe_rich_blocks():
    source = Path(__file__).parents[2].joinpath("frontend", "src", "MarkdownRenderer.tsx").read_text(encoding="utf-8")
    assert "renderTable" in source
    assert "renderList" in source
    assert "math-block" in source
    assert "safeHref" in source
    assert "dangerouslySetInnerHTML" in source
