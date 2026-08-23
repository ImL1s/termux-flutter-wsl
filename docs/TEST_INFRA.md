# E2E Test Infra: flutter_termux Post-v3.44.9 Roadmap (#47-#59)

## Test Philosophy
- Requirement-driven, opaque-box, and hermetic.
- Verification covers all 13 issues (#47-#59) using 4-tier testing hierarchy (Unit, Boundary/Corner, Cross-Feature/Integration, Adversarial/Stress & E2E).
- Verification tools: `pytest tests/`, `python scripts/ci/check_repo.py`, `python scripts/ci/check_version_drift.py`, `bash -n`, `python -m py_compile`.

## Feature Inventory & Test Mapping
| # | Feature | Requirement Source | Tier 1 (Unit) | Tier 2 (Boundary) | Tier 3 (Integration/Adversarial) | Tier 4 (E2E / Contract) |
|---|---|---|---|---|---|---|
| 1 | #47 NDK Rollback & Staging | ORIGINAL_REQUEST § R1 | `tests/test_installer_rollback.py` | Staging abort & partial 7z cleanup | Byte-exact pre-existing NDK restoration | Simulated failure rollback integration |
| 2 | #55 Workspace Safety & Cleanup | ORIGINAL_REQUEST § R1 | `tests/test_installer.py` | Temp collision in `/tmp` | `mktemp -d` isolation, zero `$HOME` spill | `.gitignore` tracking validation |
| 3 | #48 Multi-Block Gradle Idempotency | ORIGINAL_REQUEST § R2 | `tests/test_flutter_project_config.py` | Multi-flavor `defaultConfig`, commented lines | Groovy vs Kotlin DSL, multi-line braces | Idempotent 100-run convergence |
| 4 | #49 AAPT2 Override & SDK Transaction | ORIGINAL_REQUEST § R2 | `tests/test_flutter_project_config.py` | Missing `gradle.properties`, missing `targetSdk` | Spaced regex replacement, Mode A/B switch | Trap-based rollback on crash |
| 5 | #50 Build Pipeline Freshness | ORIGINAL_REQUEST § R3 | `tests/test_build_freshness.py` | Stale deb mtime, deleted target binary | Receipt hash invalidation, output mode ordering | Full build dependency graph validation |
| 6 | #51 Package Architecture & Tar Normal | ORIGINAL_REQUEST § R3 | `tests/test_package.py`, `test_package_overlay.py` | Path traversal, forbidden dir filtering | Tar UID/GID 0, reproducible timestamp | Executable bit validation (`0o111`) |
| 7 | #52 Sysroot Determinism & Lockfile | ORIGINAL_REQUEST § R3 | `tests/test_sysroot.py` | Tree hash mismatch, corrupted archive | Atomic sysroot activation & backup recovery | Pthread/glib shim transformation |
| 8 | #53 Installer Convergence & Staging | ORIGINAL_REQUEST § R4 | `tests/test_installer.py` | SHA256 checksum mismatch | `dpkg-repack` backup & package recovery | Multi-package staging transaction |
| 9 | #54 Dual-Preimage Patching & Post-Install | ORIGINAL_REQUEST § R4 | `tests/test_post_install.py` | Already patched vs unpatched source | `patch_state.json` dual-preimage state | Read-only tree hash invariance |
| 10 | #56 Release Asset Governance | ORIGINAL_REQUEST § R4 | `tests/test_release.py` | SHA256 64-hex format, companion json | Checksum format fuzzing | `verify_release_asset.py` contract |
| 11 | #57 Version Drift Governance | ORIGINAL_REQUEST § R4 | `tests/test_ci.py` | Version drift injection | Cross-file version synchronization | `check_version_drift.py` 0-drift contract |
| 12 | #58 CI/CD Workflow Hardening | ORIGINAL_REQUEST § R4 | `tests/test_ci.py` | Missing workflow permissions | YAML syntax, trigger validation | `check_repo.py` sanity check |
| 13 | #59 Offline Cache Repair & Diagnostics | ORIGINAL_REQUEST § R4 | `tests/test_offline_cache_repair.py`, `test_linux_toolchain_deps.py` | Missing toolchain binaries | Mode A vs Mode B detection | `check_toolchain.sh` diagnostic pass |

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised |
|---|---|---|
| S1 | Simulated installer crash during NDK extraction with pre-existing custom NDK | #47, #53, #55 |
| S2 | Applying project configuration to a complex multi-flavor Flutter Kotlin DSL project with comments | #48, #49 |
| S3 | Packaging `.deb` archive and validating reproducibility, file permissions, and directory exclusions | #50, #51, #52 |
| S4 | Full CI sanity check and version drift validation across all repository files | #56, #57, #58, #59 |
| S5 | Complete test suite execution (`pytest tests/`) ensuring 100% pass rate with zero regressions | All (#47-#59) |
