"""Fetch the pinned dependencies from a Git checkout or a source archive."""

import subprocess
import tempfile
from pathlib import Path


DEPENDENCY_REVISIONS = {
    "harbor": "3efb47fcd4cbd8d9fb8cf636bad5ade19208c717",
    "openclaw": "4bd3469324e85b2153d5ac23de04ac256e5cba40",
    "workspace-bench": "83689946b4de655df212195ead4f46458e3bc8e6",
}


def git(root, *args):
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True
    ).strip()


def is_checkout_root(path):
    if not (path / ".git").exists():
        return False
    return Path(git(path, "rev-parse", "--show-toplevel")).resolve() == path.resolve()


def bootstrap(root):
    root = Path(root).resolve()
    if is_checkout_root(root):
        subprocess.run(
            ["git", "-C", str(root), "submodule", "update", "--init", "--recursive"],
            check=True,
        )
        return

    for name, revision in DEPENDENCY_REVISIONS.items():
        target = root / name
        if target.exists() and (not target.is_dir() or any(target.iterdir())):
            if not is_checkout_root(target):
                raise RuntimeError(f"{target} is not an empty directory or a Git checkout; leaving it unchanged.")
            if git(target, "rev-parse", "HEAD") != revision:
                raise RuntimeError(f"{target} is not at the required revision {revision}; leaving it unchanged.")
            if git(target, "status", "--porcelain", "--untracked-files=all"):
                raise RuntimeError(f"{target} has local changes; leaving it unchanged.")
            continue

        url = git(root, "config", "--file", str(root / ".gitmodules"), "--get", f"submodule.{name}.url")
        print(f"Fetching {name} at {revision}", flush=True)
        # Publish the checkout only after a successful fetch; failures are retryable.
        with tempfile.TemporaryDirectory(prefix=f".{name}-bootstrap-", dir=root) as temporary:
            checkout = Path(temporary) / name
            subprocess.run(["git", "init", "--quiet", str(checkout)], check=True)
            git(checkout, "remote", "add", "origin", url)
            git(checkout, "fetch", "--depth", "1", "origin", revision)
            git(checkout, "checkout", "--quiet", "--detach", "FETCH_HEAD")
            git(checkout, "submodule", "update", "--init", "--recursive")
            if git(checkout, "rev-parse", "HEAD") != revision:
                raise RuntimeError(f"Unexpected revision fetched for {name}")
            if target.exists():
                target.rmdir()
            checkout.rename(target)


if __name__ == "__main__":
    try:
        bootstrap(Path(__file__).resolve().parents[1])
    except (RuntimeError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Dependency setup failed: {error}") from error
