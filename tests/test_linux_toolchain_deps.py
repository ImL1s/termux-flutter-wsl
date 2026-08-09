import yaml
from pathlib import Path
import pytest

PACKAGE_YAML = Path(__file__).parent.parent / "package.yaml"

def test_package_yaml_depends_contains_all_linux_build_tools():
    with open(PACKAGE_YAML, "rb") as f:
        data = yaml.safe_load(f)

    depends_str = data.get("control", {}).get("Depends", "")
    recommends_str = data.get("control", {}).get("Recommends", "")

    required_linux_tools = ["gtk3", "xorgproto", "ninja", "cmake", "clang", "pkg-config"]

    # Verify every required Linux build tool is in Depends
    for tool in required_linux_tools:
        assert tool in depends_str, f"Tool '{tool}' must be in control.Depends, but was missing (Depends: '{depends_str}')"

    # Verify none of the required tools remain in Recommends
    for tool in required_linux_tools:
        assert tool not in recommends_str, f"Tool '{tool}' must NOT be in control.Recommends"

def test_clean_install_contract_verifies_all_required_linux_commands_and_libs():
    """Verify that every tool needed for 'flutter build linux' is declared as a hard dependency."""
    with open(PACKAGE_YAML, "rb") as f:
        data = yaml.safe_load(f)

    depends_list = [t.strip() for t in data["control"]["Depends"].split(",")]

    # Essential tools needed for flutter build linux --release
    linux_build_requirements = {
        "cmake": "CMake build system",
        "ninja": "Ninja build engine",
        "clang": "C/C++ compiler toolchain",
        "pkg-config": "Package compiler flag configuration",
        "gtk3": "GTK3 headers and libraries",
        "xorgproto": "X11 protocol headers",
    }

    missing = []
    for req, desc in linux_build_requirements.items():
        if req not in depends_list:
            missing.append(f"{req} ({desc})")

    assert not missing, f"Clean-install contract broken: missing Linux build dependencies in control.Depends: {missing}"

def test_fails_when_required_tool_is_in_recommends():
    """Contract check: simulating a configuration where a tool is in Recommends fails contract."""
    mock_control = {
        "Depends": "git, which, openjdk-21",
        "Recommends": "gtk3, xorgproto, ninja, cmake, clang, pkg-config"
    }

    required_tools = ["gtk3", "xorgproto", "ninja", "cmake", "clang", "pkg-config"]
    depends_list = [t.strip() for t in mock_control["Depends"].split(",")]

    missing_tools = [t for t in required_tools if t not in depends_list]
    assert len(missing_tools) == 6, f"Expected 6 tools missing from Depends, found: {missing_tools}"
