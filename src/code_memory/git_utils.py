import subprocess


def get_current_commit(repo_path: str) -> str:
    """Return the current HEAD commit hash."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def has_file_changed(repo_path: str, file_path: str, since_commit: str) -> bool:
    """Check if a file has changed since a given commit."""
    result = subprocess.run(
        ["git", "diff", "--name-only", since_commit, "HEAD", "--", file_path],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    return len(result.stdout.strip()) > 0


def get_changed_files(repo_path: str, since_commit: str, extension: str = ".py") -> list[str]:
    """Return list of files changed since a commit, filtered by extension."""
    result = subprocess.run(
        ["git", "diff", "--name-only", since_commit, "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    files = [f for f in result.stdout.strip().splitlines() if f]
    if extension:
        files = [f for f in files if f.endswith(extension)]
    return files
