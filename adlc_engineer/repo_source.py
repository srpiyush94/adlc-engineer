"""Resolves a --repo argument (local path or git URL) to a local directory to scan."""

import contextlib
import os
import subprocess
import tempfile


def _looks_like_git_url(repo_arg: str) -> bool:
    return (
        repo_arg.startswith("http://")
        or repo_arg.startswith("https://")
        or repo_arg.startswith("git@")
        or repo_arg.endswith(".git")
    )


@contextlib.contextmanager
def resolve_repo(repo_arg: str):
    """Yield (local_path, display_name) for the given repo argument.

    If repo_arg is a git URL, shallow-clones it into a temp directory that is
    removed on exit. If it's a local path, yields it directly (no cleanup).
    """
    if _looks_like_git_url(repo_arg):
        with tempfile.TemporaryDirectory(prefix="adlc-engineer-clone-") as tmp_dir:
            try:
                subprocess.run(
                    ["git", "clone", "--depth", "1", repo_arg, tmp_dir],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as exc:
                raise RuntimeError(
                    f"Failed to clone repository '{repo_arg}': {exc.stderr.strip()}"
                ) from exc
            yield tmp_dir, repo_arg
    else:
        local_path = os.path.abspath(repo_arg)
        if not os.path.isdir(local_path):
            raise ValueError(f"Repo path does not exist or is not a directory: {local_path}")
        yield local_path, local_path
