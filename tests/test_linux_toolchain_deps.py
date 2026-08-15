import yaml
from pathlib import Path
import pytest

PACKAGE_YAML = Path(__file__).parent.parent / "package.yaml"

def test_package_yaml_tiered_dependencies():
    with open(PACKAGE_YAML, "rb") as f:
        data = yaml.safe_load(f)

    depends_str = data.get("control", {}).get("Depends", "")
    recommends_str = data.get("control", {}).get("Recommends", "")

    core_deps = ["git", "which", "openjdk-21", "wget", "unzip", "binutils", "clang"]
    recommended_tools = ["gtk3", "xorgproto", "ninja", "cmake", "pkg-config"]

    for dep in core_deps:
        assert dep in depends_str, f"Core dependency '{dep}' must be in control.Depends (Depends: '{depends_str}')"

    for tool in recommended_tools:
        assert tool in recommends_str, f"Desktop tool '{tool}' must be in control.Recommends (Recommends: '{recommends_str}')"

def test_clean_install_contract_verifies_tiered_dependencies():
    """Verify that core and desktop tools are cleanly declared across Depends and Recommends."""
    with open(PACKAGE_YAML, "rb") as f:
        data = yaml.safe_load(f)

    depends_list = [t.strip() for t in data["control"]["Depends"].split(",")]
    recommends_list = [t.strip() for t in data["control"]["Recommends"].split(",")]
    all_packages = depends_list + recommends_list

    required_tools = ["git", "which", "openjdk-21", "wget", "unzip", "binutils", "clang", "cmake", "ninja", "pkg-config", "gtk3", "xorgproto"]
    missing = [tool for tool in required_tools if tool not in all_packages]

    assert not missing, f"Packaging contract broken: missing dependencies across Depends/Recommends: {missing}"
