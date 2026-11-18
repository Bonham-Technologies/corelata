"""Renderers: pure functions of Report + resolved pack + sources (spec §9)."""

from corelata.render.docx import RenderError, render_docx
from corelata.render.html import render_html
from corelata.render.markdown import render_markdown
from corelata.render.outline import build_outline

__all__ = ["RenderError", "build_outline", "render_docx", "render_html", "render_markdown"]
