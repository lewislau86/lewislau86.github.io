"""Verify R18 real Git worktrees, preserved changes, ownership and extracted download."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "docs/public/learn-agent-rust"
SOURCE = PUBLIC / "code/worktree-isolation.rs"
README = PUBLIC / "code/worktree-isolation-README.md"
DATA = ROOT / "scripts/data/learn-agent-rust/r18-results.json"
ARCHIVE = PUBLIC / "worktree-isolation-lab.zip"
CHAPTER = ROOT / "docs/learn-agent-rust/worktree-isolation.md"
# bindings, linked worktrees (excluding primary), retained, removed, primary baseline
CASES = {
    "clean": (1, 0, 0, 1, True),
    "parallel": (2, 2, 2, 0, True),
    "tracked": (1, 1, 1, 0, True),
    "staged": (1, 1, 1, 0, True),
    "untracked": (1, 1, 1, 0, True),
    "ignored": (1, 1, 1, 0, True),
    "unmerged": (1, 1, 1, 0, True),
    "accepted": (1, 0, 0, 1, False),
    "conflict": (2, 2, 2, 0, False),
    "busy": (1, 0, 0, 1, True),
    "stale": (1, 1, 0, 0, True),
    "duplicate": (1, 1, 0, 0, True),
    "existing-path": (0, 0, 0, 0, True),
    "branch-exists": (0, 0, 0, 0, True),
    "denied": (0, 0, 0, 0, True),
    "invalid-task": (0, 0, 0, 0, True),
    "unknown": (0, 0, 0, 0, True),
    "locked": (1, 1, 1, 0, True),
    "wrong-branch": (1, 1, 0, 0, True),
}
DETAILS = {
    "clean": ["retire=removed"],
    "parallel": ["writers_ready=2 separate_directories=true", "alpha=startup=alpha beta=startup=beta", "retire_alpha=changes retire_beta=changes"],
    "tracked": ["retire=changes"], "staged": ["retire=changes"],
    "untracked": ["retire=changes"], "ignored": ["retire=changes"],
    "unmerged": ["retire=unmerged"],
    "accepted": ["integration=fast_forward", "retire=removed"],
    "conflict": ["integration=conflict preserved_for_review=true", "retire_alpha=target_dirty retire_beta=target_dirty"],
    "busy": ["before_join=busy", "after_join=removed"],
    "stale": ["writer=stale_owner", "edit=stale_owner retire=stale_owner"],
    "duplicate": ["allocate=duplicate_binding"], "existing-path": ["allocate=path_exists"],
    "branch-exists": ["allocate=worktree_add_failed"], "denied": ["allocate=permission_denied"],
    "invalid-task": ["allocate=invalid_identity"], "unknown": ["retire=unknown_binding"],
    "locked": ["retire=git_refused"], "wrong-branch": ["retire=branch_mismatch"],
}
BASE = b"startup=cargo run\n"


def run(args, cwd, env=None):
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True,
                          check=True, timeout=45).stdout


def git(cwd, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    return run(["git", "-c", "core.autocrlf=false", "-C", str(cwd)] + list(args), cwd, env)


def digest(content):
    return hashlib.sha256(content).hexdigest()


def archive_bytes(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo("worktree-isolation-lab/" + name, (1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            archive.writestr(info, content)
    return buffer.getvalue()


def inspect(name, output, root):
    bindings, linked, retained, removed, baseline = CASES[name]
    stats = "stats bindings={} linked={} retained={} removed={} primary_baseline={}".format(
        bindings, linked, retained, removed, str(baseline).lower())
    if output.splitlines() != ["scenario=" + name] + DETAILS[name] + [stats]:
        raise ValueError("Lifecycle mismatch: " + name + "\n" + output)
    repo = root / "repository"
    workspaces = root / "workspaces"
    listing = git(repo, "worktree", "list", "--porcelain")
    registered = [line[9:] for line in listing.splitlines() if line.startswith("worktree ")]
    if len(registered) != linked + 1:
        raise ValueError("Actual worktree registration count differs: " + name)
    if git(repo, "symbolic-ref", "HEAD").strip() != "refs/heads/main":
        raise ValueError("Primary branch changed unexpectedly")
    primary = (repo / "README.md").read_bytes()
    if (primary == BASE) != baseline:
        raise ValueError("Primary file changed unexpectedly: " + name)
    branches = git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads").splitlines()
    expected_branches = ["main"]
    if bindings or name == "branch-exists":
        expected_branches.append("codex/r18-alpha-a1")
    if name in ("parallel", "conflict"):
        expected_branches.append("codex/r18-beta-a1")
    if name == "wrong-branch":
        expected_branches.append("codex/manual-review")
    if sorted(branches) != sorted(expected_branches):
        raise ValueError("Branch refs were overwritten or removed: " + name)
    expected_dirs = [] if not linked else ["alpha-a1"]
    if name in ("parallel", "conflict"):
        expected_dirs.append("beta-a1")
    if name == "existing-path":
        expected_dirs = ["alpha-a1"]
    if sorted(p.name for p in workspaces.iterdir()) != expected_dirs:
        raise ValueError("Unexpected workspace paths: " + name)
    statuses = {}
    for path in workspaces.iterdir():
        if name == "existing-path":
            if sorted(p.name for p in path.iterdir()) != ["keep.txt"] or (path / "keep.txt").read_bytes() != b"keep\n":
                raise ValueError("Existing path data changed")
            continue
        if not (path / ".git").is_file():
            raise ValueError("Linked checkout must have a .git file")
        common = Path(git(path, "rev-parse", "--git-common-dir").strip())
        if not common.is_absolute():
            common = path / common
        if common.resolve() != (repo / ".git").resolve():
            raise ValueError("Unexpected repository association")
        branch = git(path, "symbolic-ref", "HEAD").strip()
        expected_branch = "codex/manual-review" if name == "wrong-branch" else "codex/r18-" + path.name
        if branch != "refs/heads/" + expected_branch:
            raise ValueError("Wrong checkout branch")
        status = git(path, "status", "--porcelain=v1", "--untracked-files=all", "--ignored")
        statuses[path.name] = status
        expected_status = {
            "parallel": " M README.md\n", "tracked": " M README.md\n",
            "staged": "M  README.md\n", "untracked": "?? notes.txt\n",
            "ignored": "!! scratch/cache.bin\n",
        }.get(name, "")
        if status != expected_status:
            raise ValueError("Staged, untracked or ignored data differs: " + name + repr(status))
        expected_content = BASE
        if name in ("parallel", "tracked", "staged", "unmerged", "conflict"):
            label = "beta" if path.name.startswith("beta") else "alpha"
            expected_content = ("startup=" + label + "\n").encode()
        if (path / "README.md").read_bytes() != expected_content:
            raise ValueError("Workspace content lost: " + name)
    a = workspaces / "alpha-a1"
    if name == "untracked" and (a / "notes.txt").read_bytes() != b"unfinished\n":
        raise ValueError("Untracked file lost")
    if name == "ignored" and (a / "scratch/cache.bin").read_bytes() != b"keep-cache":
        raise ValueError("Ignored file lost")
    if name == "locked" and "locked review in progress" not in listing:
        raise ValueError("Worktree lock removed")
    if name == "unmerged":
        if git(repo, "rev-list", "--count", "main..codex/r18-alpha-a1").strip() != "1":
            raise ValueError("Unmerged commit lost")
        if git(repo, "show", "codex/r18-alpha-a1:README.md") != "startup=alpha\n":
            raise ValueError("Shared object store lost commit")
    target_status = git(repo, "status", "--porcelain=v1", "--untracked-files=all", "--ignored")
    if name == "accepted":
        if primary != b"startup=alpha\n" or git(repo, "rev-parse", "main") != git(repo, "rev-parse", "codex/r18-alpha-a1"):
            raise ValueError("Accepted change not integrated")
    if name == "conflict":
        if target_status != "UU README.md\n" or not all(x in primary for x in (b"<<<<<<< HEAD", b"startup=alpha", b"startup=beta", b">>>>>>>")):
            raise ValueError("Conflict was hidden or overwritten")
        if len(git(repo, "ls-files", "--unmerged").splitlines()) != 3:
            raise ValueError("Expected three index stages in conflict")
    elif target_status:
        raise ValueError("Primary index contaminated: " + name)
    return dict(name=name, bindings=bindings, linked=linked, retained=retained, removed=removed,
                primary_baseline=baseline, branches=sorted(branches), statuses=statuses,
                target_status=target_status, stdout_sha256=digest(output.encode()))


def check_chapter():
    chapter = CHAPTER.read_text()
    source = SOURCE.read_text()
    regions = re.findall(r"<<< @/public/learn-agent-rust/code/worktree-isolation.rs#([\w-]+)", chapter)
    if len(regions) < 4:
        raise ValueError("Expected independently imported source regions")
    for region in regions:
        if source.count("// region " + region + "\n") != 1 or source.count("// endregion " + region + "\n") != 1:
            raise ValueError("Missing source region: " + region)
    for name, counts in CASES.items():
        row = "| `{}` | {} | {} | {} |".format(name, counts[1], counts[2], counts[3])
        if row not in chapter:
            raise ValueError("Missing or stale chapter result row: " + name)
    for name in re.findall(r"<<< @/public/learn-agent-rust/outputs/r18-([\w-]+).txt", chapter):
        if name not in CASES:
            raise ValueError("Unknown R18 output")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    artifacts = {}
    package = {"worktree-isolation.rs": SOURCE.read_bytes(), "README.md": README.read_bytes()}
    with tempfile.TemporaryDirectory(prefix="agent-r18-verify-") as folder:
        root = Path(folder)
        binary = str(root / "worktree-lab")
        tests_binary = str(root / "worktree-tests")
        run(["rustc", "--edition=2024", "-D", "warnings", str(SOURCE), "-o", binary], root)
        run(["rustc", "--edition=2024", "-D", "warnings", "--test", str(SOURCE), "-o", tests_binary], root)
        tests_output = run([tests_binary, "--test-threads=1"], root)
        tests = re.findall(r"^test tests::(\w+) \.\.\. ok$", tests_output, re.M)
        if len(tests) != 12 or "test result: ok. 12 passed; 0 failed;" not in tests_output:
            raise ValueError("Expected 12 Unix Rust regression tests")
        results = []
        for name in CASES:
            workspace = root / name
            output = run([binary, name, str(workspace)], root)
            results.append(inspect(name, output, workspace))
            artifacts[PUBLIC / ("outputs/r18-" + name + ".txt")] = output.encode()
            package["outputs/" + name + ".txt"] = output.encode()
        existing = root / "existing"
        existing.mkdir()
        (existing / "keep").write_bytes(b"keep\n")
        rejected = subprocess.run([binary, "clean", str(existing)], capture_output=True, timeout=10)
        if rejected.returncode != 1 or list(existing.iterdir()) != [existing / "keep"] or (existing / "keep").read_bytes() != b"keep\n":
            raise ValueError("Existing root changed")
        invalid = subprocess.run([binary, "clean"], capture_output=True, timeout=10)
        if invalid.returncode != 2 or b"usage:" not in invalid.stderr:
            raise ValueError("Missing destination must fail")
        # Inherited Git routing must not make a command operate on the external fixture.
        sentinel = root / "clean/repository"
        before = git(sentinel, "show-ref")
        env = dict(os.environ, GIT_DIR=str(sentinel / ".git"), GIT_WORK_TREE=str(sentinel),
                   GIT_INDEX_FILE=str(sentinel / ".git/index"))
        special = root / "space in path"
        output = run([binary, "parallel", str(special)], root, env)
        inspect("parallel", output, special)
        if git(sentinel, "show-ref") != before or git(sentinel, "status", "--porcelain"):
            raise ValueError("Ambient Git routing contaminated sentinel repository")
        environment = dict(rustc=run(["rustc", "--version"], root).strip(),
                           git=run(["git", "--version"], root).strip(), platform=platform.platform())
    check_chapter()
    if args.check and DATA.exists():
        environment = json.loads(DATA.read_text())["environment"]
    evidence = dict(scope="R18 dedicated Git repository and real worktrees; native writers; fixture claims; no model or R17 lease integration",
                    source_sha256=digest(SOURCE.read_bytes()), readme_sha256=digest(README.read_bytes()),
                    environment=environment, regression_tests=tests, scenarios=results)
    serialized = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    artifacts[DATA] = serialized
    package["evidence.json"] = serialized
    artifacts[ARCHIVE] = archive_bytes(package)
    content = ARCHIVE.read_bytes() if args.check and ARCHIVE.exists() else artifacts[ARCHIVE]
    with tempfile.TemporaryDirectory(prefix="agent-r18-download-") as folder:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            archive.extractall(folder)
        project = Path(folder) / "worktree-isolation-lab"
        binary = str(project / "worktree-lab")
        run(["rustc", "--edition=2024", "-D", "warnings", "worktree-isolation.rs", "-o", binary], project)
        for name in CASES:
            workspace = Path(folder) / name
            output = run([binary, name, str(workspace)], project)
            inspect(name, output, workspace)
            if output.encode() != package["outputs/" + name + ".txt"]:
                raise ValueError("Extracted package differs: " + name)
    for path, content in artifacts.items():
        if args.check:
            if not path.exists() or path.read_bytes() != content:
                raise SystemExit("Stale R18 artifact: " + str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    print("R18: 19 scenarios, 12 Rust tests, real Git/files/index checks and extracted download passed; "
          + ("artifacts checked" if args.check else "artifacts saved"))


if __name__ == "__main__":
    main()
