import subprocess

import pytest

from src.code_memory.git_utils import get_current_commit, has_file_changed


@pytest.fixture
def git_repo(tmp_path):
    """Create a temporary git repo with one committed file."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    test_file = tmp_path / "hello.py"
    test_file.write_text("x = 1\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    return tmp_path


def test_get_current_commit(git_repo):
    commit = get_current_commit(str(git_repo))
    assert len(commit) == 40  # full SHA


def test_has_file_changed_no_change(git_repo):
    commit = get_current_commit(str(git_repo))
    assert has_file_changed(str(git_repo), "hello.py", commit) is False


def test_has_file_changed_after_edit(git_repo):
    commit = get_current_commit(str(git_repo))

    # Modify the file and commit
    (git_repo / "hello.py").write_text("x = 2\n")
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "change"],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )

    assert has_file_changed(str(git_repo), "hello.py", commit) is True
