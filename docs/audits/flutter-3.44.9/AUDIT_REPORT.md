# Flutter 3.44.9 Termux SDK — Codebase & Release Audit Report

**Date:** 2026-08-23  
**Target Release:** \3.44.9-termux\  
**Target Architecture:** ARM64 / \arch64\ (\rm64-v8a\)  
**Flutter SDK:** 3.44.9  
**Dart SDK:** 3.12.2  
**Engine Commit:** a2a6a42cce67f965cf540fcecf616faca624aa1\  
**Package Artifact:** \lutter_3.44.9_aarch64.deb\  
**Package Size:** |,157,728\ bytes (v.09 MiB\)  
**SHA256:** \8b32041a11452b8d995ba45dcc2bb196e4d841410c46871853a6f4c24acddd20\  

---

## 1. Executive Summary

This document records the comprehensive audit and remediation process for the Flutter 3.44.9 SDK for Termux Android/Bionic ARM64 environment. The audit evaluated shell script security, packaging boundaries, Python build orchestration, version consistency across documentation, release asset cryptography, and cross-platform test resilience.

---

## 2. Release Asset Cryptography & Manifest Consistency

All assets hosted under GitHub Release \3.44.9-termux\ have been cryptographically verified:

| Asset Name | Expected Size | Expected SHA256 | Status |
|---|---|---|---|
| \lutter_3.44.9_aarch64.deb\ | |,157,728\ bytes | \8b32041a11452b8d995ba45dcc2bb196e4d841410c46871853a6f4c24acddd20\ | **MATCH** |
| \lutter_3.44.9_aarch64.deb.sha256\ | Companion text | \8b32041a11452b8d995ba45dcc2bb196e4d841410c46871853a6f4c24acddd20\ | **MATCH** |
| \lutter_3.44.9_aarch64.deb.size.txt\ | Companion text | |157728\ | **MATCH** |
| \inventory.txt\ | Complete binary BOM | N/A | **MATCH** |
| \uild_metadata.json\ | JSON provenance | Matches engine commit, version, and SHA256 | **MATCH** |

---

## 3. Audited Requirements & Verification Matrix

### R1. Shell Script Safety & Termux Bionic Compatibility
- **Syntax and Linting:** 100% of shell scripts in \scripts/\ and root pass \ash -n\ and actionlint.
- **Dynamic Pathing:** Replaced static paths with \\ across \post_install.sh\ and \lutter_project_config.sh\.
- **Engine Stamp Prioritization (P1 Fixed):** \post_install.sh\ reads \/bin/internal/engine.version\ directly before consulting environment variables to guarantee snapshot cache validity across offline operations.

### R2. Python Build System & Bounded Evaluation
- **Stage Receipt Fail-Closed:** \uild.py\ stage receipt verification enforces receipt presence (\xists()\) and validates artifact checksums and sizes before allowing stage skips.
- **Template Safety:** \package.py\ uses bounded template evaluation with recursion limits, property allowlisting, and archive path traversal validation.

### R3. CI/CD Governance & Zero Version Drift
- **Drift Checks:** \check_version_drift.py\ asserts complete consistency across \uild.toml\, \package.yaml\, \README.md\, \README_EN.md\, \BUILD_GUIDE.md\, \INSTALL_GUIDE.md\, and installer scripts.
- **5-Asset Verifier:** \erify_release_asset.py\ validates all 5 companion assets on release tags and cross-checks hashes and byte counts.

### R4. Cross-Platform Test Harness Resilience
- **Runtime-Aware Pathing (P2 Fixed):** \	ests/conftest.py\ provides \is_wsl_bash()\ and \	o_bash_path()\ to dynamically format POSIX paths for WSL (\/mnt/<drive>/...\), Git Bash (\/<drive>/...\), or native Linux environments.
- **Graceful Toolchain Fallback:** PowerShell syntax tests skip cleanly when \pwsh\/\powershell\ is absent on pure Linux hosts.

---

## 4. Verification Commands

\\ash
# 1. Check repo contract and static linters
python scripts/ci/check_repo.py

# 2. Check 0 version drift across all documentation and configurations
python scripts/ci/check_version_drift.py

# 3. Verify acceptance criteria suite
python scripts/ci/verify_all_acceptance_criteria.py

# 4. Verify release assets
python scripts/ci/verify_release_asset.py

# 5. Run full test suite
pytest tests/ -q
\