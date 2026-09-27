"""Gate 19 review items 65-70: vendor isolation, enforced by scanning REAL source files - not a
naming convention a future contributor could quietly violate (the same "not by convention, by
construction" posture `test_recommendation_scope.py` already established for Gate 16).

`app/modules/ai/gateway/anthropic_provider.py` is the ONE file in `services/api/app/` allowed to
import `anthropic` at all - checked by walking every `.py` file under `app/` and parsing its
imports with `ast`, never a brittle string grep.
"""

import ast
from pathlib import Path

from app.api.v1.decisions.schemas import AskResponse, RecommendedActionResponse
from app.modules.ai.ask_ninfa.service import AskNinfaService
from app.modules.ai.gateway.protocol import LanguageModelProvider

_APP_ROOT = Path(__file__).resolve().parents[1] / "app"
_ALLOWED_ANTHROPIC_IMPORTER = _APP_ROOT / "modules" / "ai" / "gateway" / "anthropic_provider.py"


def _imported_top_level_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module.split(".")[0])
    return modules


def _all_app_python_files() -> list[Path]:
    return list(_APP_ROOT.rglob("*.py"))


# --- 65-68: no Anthropic import anywhere except the one adapter file -----------------------------


def test_65_to_68_only_the_anthropic_adapter_file_imports_anthropic() -> None:
    offenders = [
        path
        for path in _all_app_python_files()
        if path != _ALLOWED_ANTHROPIC_IMPORTER and "anthropic" in _imported_top_level_modules(path)
    ]
    assert offenders == [], [str(p.relative_to(_APP_ROOT)) for p in offenders]


def test_65_ask_ninfa_service_specifically_never_imports_anthropic() -> None:
    service_file = _APP_ROOT / "modules" / "ai" / "ask_ninfa" / "service.py"
    assert "anthropic" not in _imported_top_level_modules(service_file)


def test_66_context_builder_specifically_never_imports_anthropic() -> None:
    builder_file = _APP_ROOT / "modules" / "ai" / "ask_ninfa" / "context_builder.py"
    assert "anthropic" not in _imported_top_level_modules(builder_file)


def test_67_decisions_domain_never_imports_anthropic() -> None:
    for path in (_APP_ROOT / "modules" / "decisions").rglob("*.py"):
        assert "anthropic" not in _imported_top_level_modules(path), path


def test_68_recommendations_module_never_imports_anthropic() -> None:
    for path in (_APP_ROOT / "modules" / "recommendations").rglob("*.py"):
        assert "anthropic" not in _imported_top_level_modules(path), path


# --- 69: no Anthropic type in the Protocol itself -------------------------------------------------


def test_69_language_model_provider_protocol_has_no_anthropic_type() -> None:
    protocol_file = _APP_ROOT / "modules" / "ai" / "gateway" / "protocol.py"
    assert "anthropic" not in _imported_top_level_modules(protocol_file)
    assert LanguageModelProvider.__module__ == "app.modules.ai.gateway.protocol"


# --- 70: no vendor object/name in the public API schema shapes -----------------------------------


def test_70_public_api_schemas_carry_no_vendor_object_or_name() -> None:
    for model in (AskResponse, RecommendedActionResponse):
        for field_name, field in model.model_fields.items():
            text = f"{field_name} {field.annotation}"
            assert "anthropic" not in text.lower(), (model.__name__, field_name)
    assert AskNinfaService.__init__.__annotations__["provider"] is LanguageModelProvider
