from __future__ import annotations

from pathlib import Path

from tool_installer.errors import (
    CliError,
    ConfigError,
    DependencyError,
    InstallationError,
    ManifestError,
    StrategyError,
    ToolInstallerError,
)
from tool_installer.models import (
    Environment,
    InstallPlan,
    MergedStrategy,
    ModuleSpec,
    PlanItem,
    ToolReference,
    ToolSpec,
    ToolsConfig,
)


def test_core_models_represent_plan_item() -> None:
    reference = ToolReference(raw="node@20", name="node", version="20")
    tool = ToolSpec(reference=reference, desc="Node runtime", allow_fail=True)
    module = ModuleSpec(name="dev", depends=["base"], tools=[tool])
    config = ToolsConfig(
        path=Path("tools.toml"),
        manifest_path=Path("manifest.toml"),
        modules={"dev": module},
    )
    env = Environment(os="linux", arch="x86_64")
    strategy = MergedStrategy(
        tool_name="node",
        manager="mise",
        fields={"manager": "mise", "plugin": "node"},
    )
    item = PlanItem(module_name="dev", tool=tool, strategy=strategy, environment=env)
    plan = InstallPlan(items=[item])

    assert config.modules["dev"].tools[0].reference.version == "20"
    assert plan.items[0].tool.allow_fail is True
    assert plan.items[0].strategy.manager == "mise"
    assert plan.items[0].environment.os == "linux"


def test_error_types_share_base_class() -> None:
    for error_type in [
        CliError,
        ConfigError,
        DependencyError,
        ManifestError,
        StrategyError,
        InstallationError,
    ]:
        assert issubclass(error_type, ToolInstallerError)
