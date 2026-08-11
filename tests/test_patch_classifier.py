import os
import sys
import json
import git
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from build import Build


def create_git_repo_with_patch(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    repo = git.Repo.init(repo_dir)

    # Configure user name / email so commits succeed anywhere
    repo.config_writer().set_value("user", "name", "Test Runner").release()
    repo.config_writer().set_value("user", "email", "test@example.com").release()

    # Initial file
    file_a = repo_dir / "file_a.txt"
    file_a.write_text("line 1\nline 2\nline 3\n", encoding="utf-8")
    repo.git.add("file_a.txt")
    commit_1 = repo.index.commit("Initial commit")

    # Create tag
    tag_name = "3.44.2"
    repo.create_tag(tag_name, commit_1)

    # Create remote origin
    repo.create_remote("origin", str(repo_dir))

    # Create a patch file
    patches_dir = tmp_path / "patches" / tag_name
    patches_dir.mkdir(parents=True)
    patch_file = patches_dir / "test.patch"

    # Modify file_a to create a patch
    file_a.write_text("line 1\nline 2 modified\nline 3\n", encoding="utf-8")
    patch_diff = repo.git.diff()
    patch_file.write_text(patch_diff + "\n", encoding="utf-8")

    # Reset repo to clean state
    repo.git.checkout("--", "file_a.txt")

    # Configure build object
    conf_path = tmp_path / "build.toml"
    conf_content = f"""
[flutter]
tag = "{tag_name}"
path = "{repo_dir.as_posix()}"

[build]
root = "{repo_dir.as_posix()}"
release = "{repo_dir.as_posix()}"

[patch]
dir = "{(tmp_path / 'patches').as_posix()}"

[patch.test]
file = "test.patch"
path = "."
"""
    conf_path.write_text(conf_content, encoding="utf-8")

    pkg_yaml = tmp_path / "package.yaml"
    pkg_yaml.write_text("control:\n  Package: flutter\n  Version: 3.44.2\n", encoding="utf-8")

    b = Build(conf=str(conf_path))
    return b, repo, repo_dir, patch_file, tag_name


def test_classifier_clean_checkout(tmp_path):
    b, repo, repo_dir, patch_file, tag_name = create_git_repo_with_patch(tmp_path)

    # Case 1: Clean exact-tag checkout -> accept
    status = b.classify_workspace_patch_state(str(repo_dir))
    assert status['valid'] is True, f"Failed: {status.get('reason')}"
    assert status['state'] == 'clean'
    assert status['patch_digest'] != ''


def test_classifier_applied_patch_checkout(tmp_path):
    b, repo, repo_dir, patch_file, tag_name = create_git_repo_with_patch(tmp_path)

    # Apply the patch
    repo.git.apply([str(patch_file)])

    # Case 2: Checkout containing exactly configured patch postimage -> accept
    status = b.classify_workspace_patch_state(str(repo_dir))
    assert status['valid'] is True, f"Failed: {status.get('reason')}"
    assert status['state'] == 'patched'
    assert 'test' in status['applied_patches']


def test_classifier_unrelated_tracked_modification(tmp_path):
    b, repo, repo_dir, patch_file, tag_name = create_git_repo_with_patch(tmp_path)

    # Make unrelated edit without patch
    (repo_dir / "file_a.txt").write_text("unrelated change\n", encoding="utf-8")

    # Case 3: Unrelated tracked modification -> reject
    status = b.classify_workspace_patch_state(str(repo_dir))
    assert status['valid'] is False
    assert 'dirty' in status['reason'] or 'extra' in status['reason'] or 'invalid' in status['state']


def test_classifier_staged_modification(tmp_path):
    b, repo, repo_dir, patch_file, tag_name = create_git_repo_with_patch(tmp_path)

    # Create new file and stage it
    staged_file = repo_dir / "staged.txt"
    staged_file.write_text("staged content", encoding="utf-8")
    repo.git.add("staged.txt")

    # Case 4: Staged modification -> reject
    status = b.classify_workspace_patch_state(str(repo_dir))
    assert status['valid'] is False


def test_classifier_untracked_file(tmp_path):
    b, repo, repo_dir, patch_file, tag_name = create_git_repo_with_patch(tmp_path)

    # Create untracked file
    untracked = repo_dir / "untracked.txt"
    untracked.write_text("untracked content", encoding="utf-8")

    # Case 5: Untracked file -> reject
    status = b.classify_workspace_patch_state(str(repo_dir))
    assert status['valid'] is False


def test_classifier_partial_unknown_patch_state(tmp_path):
    b, repo, repo_dir, patch_file, tag_name = create_git_repo_with_patch(tmp_path)

    # Partially modify file_a.txt in a way that breaks patch application and reverse application
    (repo_dir / "file_a.txt").write_text("line 1\nconflict line\nline 3\n", encoding="utf-8")

    # Case 6: Partial/unknown patch state -> reject
    status = b.classify_workspace_patch_state(str(repo_dir))
    assert status['valid'] is False


def test_classifier_mixed_expected_patch_plus_unrelated_edit(tmp_path):
    b, repo, repo_dir, patch_file, tag_name = create_git_repo_with_patch(tmp_path)

    # Apply valid patch
    repo.git.apply([str(patch_file)])

    # Also add an unrelated untracked or tracked file
    extra_file = repo_dir / "extra.txt"
    extra_file.write_text("extra edit", encoding="utf-8")

    # Case 7: Mixed expected patch plus unrelated edit -> reject
    status = b.classify_workspace_patch_state(str(repo_dir))
    assert status['valid'] is False
