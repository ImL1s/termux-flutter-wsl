# Project: termux-flutter-wsl (Roadmap #44 - 24 GitHub Issues)

## Architecture
- Flutter SDK cross-compilation pipeline for Termux (Android/Bionic ARM64).
- Target host/build: WSL Ubuntu x86-64 -> Host/Target ARM64 Termux.
- Key modules: `build.py` (CLI orchestrator), `build.toml` (version & build config), `sysroot.py` (Termux apt package fetcher), `package.py` & `package.yaml` (.deb packager), `scripts/install/post_install.sh` & `install_flutter_complete.sh` (installer/runtime patches), `.github/workflows/` (CI/CD pipelines).

## Feature Inventory
| # | Feature / Issue | Description | Milestone | Source |
|---|-----------------|-------------|-----------|--------|
| 1 | #22 Release asset verification | Fix `release-check.yml` verification, remove 3.44.0 defaults | M2.2 (Track A) | ORIGINAL_REQUEST §R1.1 |
| 2 | #26 Runtime version integrity | Resolve Dart 3.12.0/3.12.1 discrepancy, provenance manifest | M2.2 (Track A) | ORIGINAL_REQUEST §R1.5 |
| 3 | #23 Build-deb workflow repair | Align `build-deb.yml` with manifest, single packaging step | M4.2 (Track A) | ORIGINAL_REQUEST §R1.2 |
| 4 | #37 Release promotion gate | Immutable candidate handoff, device smoke gate | M4.2 (Track A) | ORIGINAL_REQUEST §R5 |
| 5 | #27 Version single source of truth | Canonical manifest for Flutter/Dart/NDK/patches | M1.1 (Track B) | ORIGINAL_REQUEST §R2.1 |
| 6 | #36 CI semantic tests | Static analysis, linting, YAML schema checks | M1.1 (Track B) | ORIGINAL_REQUEST §R4.3 |
| 7 | #34 Pinned external artifacts | Pin & SHA256 verify all external downloads | M2.1 (Track B) | ORIGINAL_REQUEST §R3.3 |
| 8 | #31 Reproducible sysroot | Sysroot lockfile, staging build, atomic replacement | M2.1 (Track B) | ORIGINAL_REQUEST §R3.1 |
| 9 | #32 Atomic verified .deb | Safe expression resolver in package.yaml, atomic archive | M2.1 (Track B) | ORIGINAL_REQUEST §R3.2 |
| 10 | #42 Atomic workspace | Safe clone/checkout staging, status/activate CLI | M1.2 (Track C) | ORIGINAL_REQUEST §R4.4 |
| 11 | #29 Portable configuration | Env var overrides (NDK_PATH), typed config | M1.2 (Track C) | ORIGINAL_REQUEST §R2.3 |
| 12 | #30 Safe WSL sync | Path-safe sync validation, stale file detection | M1.2 (Track C) | ORIGINAL_REQUEST §R2.4 |
| 13 | #28 Complete build pipeline | Full `build_all()` stage graph without gaps | M1.2 (Track C) | ORIGINAL_REQUEST §R2.2 |
| 14 | #24 Transactional installer | Non-destructive install, preflight, rollback manifest | M3.1 (Track D) | ORIGINAL_REQUEST §R1.3 |
| 15 | #25 Truthful exit codes | Non-zero exit on failures, no `\|\| true` on required steps | M3.1 (Track D) | ORIGINAL_REQUEST §R1.4 |
| 16 | #33 Idempotent post-install engine | Declarative patch engine with preimage/postimage hash | M3.1 (Track D) | ORIGINAL_REQUEST §R4.1 |
| 17 | #39 Consolidated installer | Single installer entry point with shared core | M3.2 (Track D) | ORIGINAL_REQUEST §R6.2 |
| 18 | #43 Per-project configuration | Project-scoped android/gradle config tool | M3.2 (Track D) | ORIGINAL_REQUEST §R6.5 |
| 19 | #38 Deterministic device smoke | Structured JSON evidence output, safe smoke setup | M4.1 (Track E) | ORIGINAL_REQUEST §R6.1 |
| 20 | #35 Mode B validation | Reject stub toolchains for Mode B (API 35+) | M4.1 (Track E) | ORIGINAL_REQUEST §R4.2 |
| 21 | #40 Package metadata/dependencies | Split core/optional deps, fix deb metadata | M4.3 (Track F) | ORIGINAL_REQUEST §R6.3 |
| 22 | #41 Documentation cleanup | Remove stale paths, validate docs against code | M4.3 (Track F) | ORIGINAL_REQUEST §R6.4 |
| 23 | #45 APK size investigation | Investigate ~162MB APK size & libflutter.so compression | M4.3 (Track F) | ORIGINAL_REQUEST §R7 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1.1 | Single Source of Truth & CI Checks | Issues #27, #36 | none | IN_PROGRESS |
| M1.2 | Build Engine & Workspace Isolation | Issues #42, #29, #30, #28 | M1.1 (#27 config) | PLANNED |
| M2.1 | Sysroot Lock & Verified Packaging | Issues #34, #31, #32 | M1.1 | PLANNED |
| M2.2 | Release Verification & Provenance | Issues #22, #26 | M1.1 | PLANNED |
| M3.1 | Transactional Installer & Patch Engine | Issues #24, #25, #33 | M1.1, M2.2 | PLANNED |
| M3.2 | Installer Consolidation & Project Config | Issues #39, #43 | M3.1 | PLANNED |
| M4.1 | Device Smoke Evidence & Mode B Toolchain | Issues #38, #35 | M3.1 | PLANNED |
| M4.2 | Build Workflow Repair & Promotion Gate | Issues #23, #37 | M1.1, M2.1, M2.2, M4.1 | PLANNED |
| M4.3 | Metadata, Docs Cleanup & APK Size Stripping | Issues #40, #41, #45 | M1.1, M2.1, M3.2 | PLANNED |

## Interface Contracts
### Canonical Version Manifest (`build.toml`)
- `version.flutter_tag`: string (e.g. "3.44.2")
- `version.release_tag`: string (e.g. "v3.44.2-termux")
- `version.dart_version`: string (e.g. "3.4.4")
- `version.ndk`: string (e.g. "r27d")
- `version.expected_deb_sha256`: string

### Provenance Manifest (`termux-release.json`)
- Installed to `$PREFIX/share/flutter/termux-release.json`.
- Schema: `{ "flutter_version", "release_tag", "dart_version", "engine_revision", "ndk_version", "build_timestamp", "deb_sha256" }`.

### Patch Engine State (`post_install.sh`)
- Patch entries with preimage_sha256, transformation logic, postimage_sha256.
- Modes: `--check`, `--apply`, `--status`, `--rollback`.

### Device Evidence Schema (`evidence.json`)
- Written to `$HOME/.termux_smoke/evidence.json`.
- Schema: `{ "timestamp", "device_serial", "mode_a": { "status", "apk_build", "apk_size" }, "mode_b": { "status", "aab_build" } }`.

## Code Layout
- `build.py`: Entry point CLI
- `build.toml`: Configuration single source of truth
- `sysroot.py`: Termux sysroot assembly & lockfile manager
- `package.py` & `package.yaml`: Deb package creation
- `utils.py`: Architecture & path utilities
- `scripts/install/`: Installer and post-install scripts
- `scripts/ci/`: CI validation scripts
- `.github/workflows/`: GitHub Actions workflows
