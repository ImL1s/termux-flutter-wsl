# CI/CD and Device Lab

This repository uses two classes of GitHub Actions:

1. **GitHub-hosted checks** for fast, free, public-repository validation.
2. **Self-hosted workflows** for the expensive Flutter Engine build and Android tablet smoke tests.

The goal is to keep pull requests cheap and safe while still making release builds reproducible.

## GitHub Actions cost and limits

This is a public open-source repository, so standard GitHub-hosted runner
minutes are free for the lightweight `CI` and `Release check` workflows. The
self-hosted build/device workflows also do not consume GitHub-hosted runner
minutes.

That does **not** mean Actions are unlimited:

- GitHub still enforces workflow, queue, API, concurrency, cache, and artifact
  limits. For example, GitHub-hosted jobs have a 6-hour execution limit, and
  self-hosted jobs have a 5-day execution limit.
- Larger GitHub-hosted runners are charged even for public repositories.
- Artifacts and caches should be kept small and short-lived. Large `.deb`
  release payloads belong in GitHub Releases, not as long-retained workflow
  artifacts.
- Self-hosted runner capacity is limited by the maintainer's own WSL/Windows
  machine, disk space, tablet availability, and network.

References:

- [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
- [GitHub Actions limits](https://docs.github.com/en/actions/reference/limits)

## Workflow map

| Workflow | File | Runner | Trigger | Purpose |
|----------|------|--------|---------|---------|
| CI | `.github/workflows/ci.yml` | `ubuntu-latest` | PR, push to `master`, manual | Python/shell/PowerShell syntax, package/docs/workflow sanity, whitespace checks |
| Build deb | `.github/workflows/build-deb.yml` | self-hosted Linux/WSL | manual | Full `build.py` pipeline, `.deb` packaging, optional release publishing |
| Device smoke | `.github/workflows/device-smoke.yml` | self-hosted Windows + ADB tablet | manual | Install deb in Termux, run `post_install.sh`, `flutter doctor`, create/build APK/Linux smoke |
| Release check | `.github/workflows/release-check.yml` | `ubuntu-latest` | release publish/edit, manual | Verify release asset name, size, and SHA256 digest |

## Why the split exists

Public repositories can use standard GitHub-hosted runners for free, but this project's full build is not a normal CI job:

- `gclient sync` downloads tens of GB.
- Flutter Engine builds can take hours.
- The build needs Android NDK r27d at `/opt/android-ndk-r27d`.
- Real release confidence requires an attached Android/Termux tablet.

Therefore:

- **PR CI must stay lightweight** and never touch self-hosted device hardware.
- **Full build and device smoke are manual self-hosted gates** run by a maintainer.
- **Release publishing is manual**, not automatic on every merge to `master`.

## PR / push CI

`ci.yml` runs on every PR and push to `master`:

```text
python -m py_compile build.py package.py sysroot.py utils.py scripts/ci/check_repo.py
bash -n install_flutter_complete.sh scripts/install/*.sh scripts/test/gh_e2e_test.sh scripts/device/termux_smoke.sh
PowerShell parser check for scripts/device/run_termux_smoke.ps1
python scripts/ci/check_repo.py
git diff --check
```

`check_repo.py` validates repo-specific contracts, including:

- workflow YAML parses
- self-hosted workflows are not triggered by `pull_request`
- `package.yaml` still packages `dart`, `dartvm`, `dartaotruntime`, and `post_install`
- `post_install.sh` still contains the Flutter 3.44 `PLATFORM_ABI_LIST` and Android-host patches
- installer defaults remain on Flutter 3.44.2 and NDK r29 for Termux installs
- release/download docs do not regress to stale 3.41.5 commands

## Full deb build

Manual workflow: **Build deb (self-hosted)**

Default inputs:

```text
flutter_version: 3.44.2
arch: arm64
runner_labels_json: ["self-hosted","linux"]
publish_release: false
release_tag: v3.44.2
```

Required self-hosted environment:

- Linux or WSL runner with enough disk space (100GB+ recommended)
- Python 3.12 available through `actions/setup-python`
- `/opt/android-ndk-r27d`
- `git`, `curl`, `ninja`, `pkg-config`, and normal build dependencies
- network access for Flutter/Chromium/Termux downloads

The workflow bootstraps `depot_tools` if `gclient` is missing, then runs:

```bash
python3 build.py clone
python3 build.py sync
python3 build.py patch_engine
python3 build.py patch_dart
python3 build.py patch_skia
python3 build.py patch_flutter_sdk
python3 build.py build_all --arch=arm64
python3 build.py debuild --arch=arm64
```

It uploads:

- `flutter_3.44.2_aarch64.deb`
- `flutter_3.44.2_aarch64.deb.sha256`
- `flutter_3.44.2_aarch64.deb.size.txt`

If `publish_release=true`, it creates or updates `release_tag` and uploads the deb with `--clobber`.

## Release policy

Merging to `master` does **not** publish a GitHub Release. The current release
flow is intentionally maintainer-triggered:

1. Merge only after PR CI passes.
2. Trigger **Build deb (self-hosted)** manually on the chosen commit/tag.
3. Leave `publish_release=false` for a dry build, or set
   `publish_release=true` only when intentionally publishing.
4. Run device smoke against the produced or published `.deb`.
5. Let **Release check** verify the release asset metadata after publish/edit.

This avoids accidental multi-hour engine builds and prevents unreviewed merges
from overwriting a public release asset. A future release pipeline may chain
build → device smoke → publish, but the current project keeps publish as an
explicit maintainer action.

## Device smoke

Manual workflow: **Device smoke (self-hosted)**

Default input tests the published v3.44.2 release asset:

```text
deb_url: https://github.com/ImL1s/termux-flutter-wsl/releases/download/v3.44.2/flutter_3.44.2_aarch64.deb
expected_sha256: 66a7099324c0d7094d604aa92abeec87b7a29b8e0bc697b819e0cd91fc706000
```

Required self-hosted environment:

- Windows runner with ADB installed
- Android tablet connected and authorized for USB debugging
- Termux installed and launchable as `com.termux`
- Tablet awake/unlocked before the run; secure lock screens block ADB text injection into Termux
- Enough tablet storage for the deb, Android SDK/NDK, Gradle caches, APK, and Linux build

The PowerShell driver intentionally keeps the tablet awake:

```powershell
adb shell svc power stayon true
adb shell input keyevent 224
adb shell wm dismiss-keyguard
```

It then pushes the deb and `scripts/device/termux_smoke.sh`, launches Termux, injects:

```text
sh /sdcard/Download/termux_ci_smoke.sh
```

and polls `/sdcard/Download/termux_ci_smoke.txt` until `DONE` or timeout.

Required success markers:

```text
INSTALL_STATUS=0
POST_INSTALL_STATUS=0
FLUTTER_VERSION_STATUS=0
DART_VERSION_STATUS=0
DARTVM_VERSION_STATUS=0
DOCTOR_STATUS=0
CREATE_STATUS=0
BUILD_APK_STATUS=0
BUILD_LINUX_STATUS=0
DONE
```

The workflow turns `svc power stayon` back off before exiting.

## Release check

`release-check.yml` verifies release metadata from GitHub:

- expected tag exists
- expected asset exists
- asset size is plausible
- asset digest matches the expected SHA256 when GitHub exposes the digest

This workflow is safe to run on GitHub-hosted runners because it only reads public release metadata.

## Security model

- Fork PRs only get `ci.yml` on GitHub-hosted runners.
- Self-hosted build/device workflows are `workflow_dispatch` only.
- Device smoke does not run untrusted PR code automatically.
- Release publishing requires `contents: write` and only happens from the manual self-hosted build workflow when `publish_release=true`.

## Local equivalents

Fast local checks:

```bash
python -m py_compile build.py package.py sysroot.py utils.py scripts/ci/check_repo.py
bash -n scripts/install/post_install.sh
python scripts/ci/check_repo.py
git diff --check
```

Manual Termux release E2E test inside Termux:

```bash
bash scripts/test/gh_e2e_test.sh
```

Manual Windows-to-tablet smoke:

```powershell
scripts/device/run_termux_smoke.ps1 `
  -AdbPath "C:\Users\aa223\AppData\Local\Android\Sdk\platform-tools\adb.exe" `
  -DebUrl "https://github.com/ImL1s/termux-flutter-wsl/releases/download/v3.44.2/flutter_3.44.2_aarch64.deb"
```
