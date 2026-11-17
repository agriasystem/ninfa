"""The closed catalog Mia's model can name: every tool of every area, in the order the model reads
them (product help first, then what the person is looking at, then the numbers, then imports and the
structure). Built once; it holds no per-request state."""

from functools import lru_cache

from app.modules.ai.mia.tools import context, data, decisions, imports, product, structure
from app.modules.ai.mia.tools.base import ToolCatalog, ToolDefinition


def build_tool_catalog() -> ToolCatalog:
    tools: list[ToolDefinition] = []
    for module in (product, context, decisions, data, imports, structure):
        tools.extend(module.TOOLS)
    return ToolCatalog(tools)


@lru_cache(maxsize=1)
def default_tool_catalog() -> ToolCatalog:
    return build_tool_catalog()


__all__ = ["build_tool_catalog", "default_tool_catalog"]
