"""Git snapshots, selection, rewriting and verified publication."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import uuid

FORMAT = "git-history-cleaner/1"
DOCUMENT_EXTS = [".doc", ".docx", ".jpeg", ".jpg", ".pdf", ".png"]


def git(repo, *args, data=None):
    env = os.environ.copy()
    # Caller Git environment must not redirect operations away from our clone.
    for key in list(env):
        if key.startswith("GIT_"):
            del env[key]
    env["GIT_NO_REPLACE_OBJECTS"] = "1"
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    proc = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-C", str(repo), *args],
        input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace").strip())
    return proc.stdout


def text(repo, *args):
    return git(repo, *args).decode("utf-8", "surrogateescape").strip()


def save(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def literal_path(value):
    if not value or "\0" in value or value.startswith("/") or ".." in value.split("/"):
        raise ValueError("paths must be repository-relative without '..'")
    path = str(PurePosixPath(value))
    if ".git" in path.split("/"):
        raise ValueError("paths must not include .git")
    return path


def within(path, prefix):
    return prefix == "." or path == prefix or path.startswith(prefix + "/")


def selected(path, rules):
    return (any(within(path, p) for p in rules["paths"])
            and not any(within(path, p) for p in rules["exclude"])
            and (not rules["extensions"] or PurePosixPath(path).suffix.lower() in rules["extensions"]))


def tree(repo, revision):
    entries = {}
    for record in git(repo, "ls-tree", "-rz", "-r", revision).split(b"\0"):
        if record:
            meta, path = record.split(b"\t", 1)
            mode, kind, oid = meta.split()
            if kind == b"blob":
                entries[path.decode("utf-8", "surrogateescape")] = oid.decode()
    return entries


def inventory(repo, revision):
    """Read each distinct tree once; NUL framing preserves literal filenames."""
    trees = set(text(repo, "log", "--format=%T", revision).splitlines())
    paths = {}
    for tree_id in sorted(trees):
        for path, oid in tree(repo, tree_id).items():
            paths.setdefault(path, set()).add(oid)
    return paths


def selection(repo, revision, rules):
    current = tree(repo, revision)
    history = inventory(repo, revision)
    protected = set(current.values())
    outside = {oid for path, ids in history.items() if not selected(path, rules) for oid in ids}
    targets = {path: ids for path, ids in history.items() if selected(path, rules)}
    candidates = set().union(*targets.values()) if targets else set()
    sizes = {}
    if candidates:
        output = git(repo, "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)",
                     data=("\n".join(sorted(candidates)) + "\n").encode())
        sizes = {parts[0].decode(): int(parts[2]) for parts in map(bytes.split, output.splitlines())}
    eligible = {oid for oid in candidates if sizes[oid] >= rules["min_bytes"]}
    # Global blob deletion is allowed only if no unselected historical path uses it.
    strip = eligible - protected - outside
    # Removing an absent path is safe even when its content is retained elsewhere.
    deleted = sorted(path for path, ids in targets.items() if path not in current and ids <= eligible)
    return {"strip_blobs": sorted(strip), "deleted_paths": deleted,
            "protected_head_blobs": len(candidates & protected),
            "protected_outside_blobs": len(candidates & outside),
            "selected_blob_bytes": sum(sizes[oid] for oid in strip),
            "matched_paths": len(targets)}


def analyze(args):
    source = args.repo
    local = Path(source).expanduser()
    if local.exists():
        source = str(local.resolve())
    if source.startswith("-"):
        raise ValueError("repository must not start with '-'")
    extensions = []
    for value in args.ext:
        for ext in value.split(","):
            ext = ext.strip().lower().lstrip(".")
            if not ext or "/" in ext:
                raise ValueError("invalid extension")
            extensions.append("." + ext)
    if args.preset:
        extensions.extend(DOCUMENT_EXTS)
    if not (args.path or extensions or args.min_bytes):
        raise ValueError("specify --path . explicitly, a path, extension, preset or size threshold")
    rules = {"paths": [literal_path(p) for p in args.path] or ["."],
             "exclude": [literal_path(p) for p in args.exclude],
             "extensions": sorted(set(extensions)), "min_bytes": args.min_bytes}
    if args.work_dir:
        root = Path(args.work_dir).absolute()
        root.mkdir(parents=True, exist_ok=False)
        root = root.resolve()
    else:
        root = Path(tempfile.mkdtemp(prefix=".git-history-cleaner-", dir=Path.cwd())).resolve()
    manifest = {"format": FORMAT, "run_id": str(uuid.uuid4()), "root": str(root), "state": "analyzing"}
    save(root / "run.json", manifest)
    try:
        git(root, "clone", "--mirror", "--no-local", "--", source, "backup.git")
        backup = root / "backup.git"
        if text(backup, "rev-parse", "--is-shallow-repository") == "true":
            raise ValueError("shallow history is unsupported; use a full repository")
        branch = args.branch or text(backup, "symbolic-ref", "--short", "HEAD")
        git(backup, "check-ref-format", "refs/heads/" + branch)
        ref = "refs/heads/" + branch
        old = text(backup, "rev-parse", "--verify", ref + "^{commit}")
        plan = {"format": FORMAT, "run_id": manifest["run_id"], "source": source,
                "branch": branch, "old_head": old, "old_tree": text(backup, "rev-parse", old + "^{tree}"),
                "rules": rules, "selection": selection(backup, old, rules),
                "snapshot_refs": text(backup, "for-each-ref", "--format=%(refname)").splitlines()}
        save(root / "plan.json", plan)
        manifest.update(state="analyzed", plan_digest=digest(plan))
        save(root / "run.json", manifest)
        return {"run": str(root), "plan": str(root / "plan.json"), **plan["selection"]}
    except Exception as exc:
        manifest.update(state="failed", error=str(exc))
        save(root / "run.json", manifest)
        raise


def load_run(value):
    requested = Path(value).absolute()
    if requested.is_symlink():
        raise ValueError("run directory must not be a symlink")
    root = requested.resolve()
    marker = root / "run.json"
    if marker.is_symlink():
        raise ValueError("run manifest must not be a symlink")
    manifest = json.loads(marker.read_text(encoding="utf-8"))
    if manifest.get("format") != FORMAT or manifest.get("root") != str(root):
        raise ValueError("not a recognized run directory at its recorded location")
    uuid.UUID(manifest["run_id"])
    return root, manifest


def load_plan(root, manifest):
    plan = json.loads((root / "plan.json").read_text(encoding="utf-8"))
    if plan.get("run_id") != manifest["run_id"] or digest(plan) != manifest.get("plan_digest"):
        raise ValueError("plan changed; create a new analysis instead of editing the plan")
    return plan


def safe_repo(root, name):
    repo = root / name
    if repo.is_symlink() or repo.resolve().parent != root:
        raise ValueError("run repositories must not be symlinks")
    if name == "rewritten" and repo.exists() and (
            (repo / ".git").is_symlink() or not (repo / ".git").is_dir()):
        raise ValueError("rewritten .git must be an ordinary directory")
    return repo


def rewrite(plan_path):
    path = Path(plan_path).resolve()
    root, manifest = load_run(path.parent)
    if path.name != "plan.json" or manifest["state"] != "analyzed":
        raise ValueError("rewrite requires an analyzed run and its plan.json")
    plan = load_plan(root, manifest)
    backup = safe_repo(root, "backup.git")
    ref = "refs/heads/" + plan["branch"]
    if text(backup, "rev-parse", ref) != plan["old_head"]:
        raise ValueError("backup branch changed; analyze again")
    actual = selection(backup, plan["old_head"], plan["rules"])
    if actual != plan["selection"]:
        raise ValueError("backup no longer matches the plan")
    manifest["state"] = "rewriting"
    save(root / "run.json", manifest)
    try:
        repo = safe_repo(root, "rewritten")
        git(root, "clone", "--no-local", "--no-tags", "--single-branch", "--branch", plan["branch"],
            str(backup), str(repo))
        chosen = plan["selection"]
        if chosen["deleted_paths"] or chosen["strip_blobs"]:
            ids = root / "strip-blobs.txt"
            ids.write_text("\n".join(chosen["strip_blobs"]) + "\n", encoding="ascii")
            removed = {p.encode("utf-8", "surrogateescape") for p in chosen["deleted_paths"]}
            callback = f"return None if filename in {removed!r} else filename"
            # A file avoids argv limits when many paths were deleted.
            callback_path = root / "filename-callback.py"
            callback_path.write_text(callback, encoding="ascii")
            git(repo, "filter-repo", "--force", "--filename-callback", str(callback_path),
                "--strip-blobs-with-ids", str(ids), "--replace-refs", "delete-no-add",
                "--prune-empty", "never", "--prune-degenerate", "never")
        manifest.update(state="rewritten", new_head=text(repo, "rev-parse", "HEAD"))
        save(root / "run.json", manifest)
        return verify(root)
    except Exception as exc:
        manifest.update(state="failed", error=str(exc))
        save(root / "run.json", manifest)
        raise


def verify(value):
    root, manifest = load_run(value)
    if manifest["state"] not in {"rewritten", "verified", "pushed", "push-failed"}:
        raise ValueError("run has no completed rewrite to verify")
    plan = load_plan(root, manifest)
    repo = safe_repo(root, "rewritten")
    if text(repo, "rev-parse", "HEAD") != manifest["new_head"]:
        raise ValueError("rewritten HEAD changed")
    if text(repo, "status", "--porcelain"):
        raise ValueError("rewritten working tree is dirty")
    if text(repo, "rev-parse", "HEAD^{tree}") != plan["old_tree"]:
        raise ValueError("verification failed: HEAD tree changed")
    git(repo, "fsck", "--full")
    history = inventory(repo, "HEAD")
    all_ids = set().union(*history.values()) if history else set()
    if set(plan["selection"]["strip_blobs"]) & all_ids:
        raise ValueError("verification failed: selected blobs remain reachable")
    if set(plan["selection"]["deleted_paths"]) & set(history):
        raise ValueError("verification failed: deleted paths remain reachable")
    if manifest["state"] != "pushed":
        manifest["state"] = "verified"
    save(root / "run.json", manifest)
    result = {"run": str(root), "verified": True, "head_tree_preserved": True,
              "old_head": plan["old_head"], "new_head": manifest["new_head"],
              "scope": "selected branch only"}
    save(root / "verification.json", result)
    return result


def confirm(message, yes):
    if yes:
        return
    import sys
    if not sys.stdin.isatty() or input(message + " [y/N] ").strip().lower() != "y":
        raise ValueError("not confirmed; use --yes for non-interactive operation")


def push(value, remote, yes=False, chunk_size=0):
    verify(value)
    root, manifest = load_run(value)
    plan = load_plan(root, manifest)
    if manifest.get("temporary_refs"):
        raise ValueError("temporary refs from an earlier push remain; resolve them first")
    repo = safe_repo(root, "rewritten")
    # Resolve before git -C changes the meaning of a relative local destination.
    destination = str(Path(remote).resolve()) if Path(remote).exists() else remote
    if destination.startswith("-"):
        raise ValueError("remote must not start with '-'")
    ref = "refs/heads/" + plan["branch"]
    advertised = text(repo, "ls-remote", "--refs", destination, ref).split()
    if not advertised or advertised[0] != plan["old_head"]:
        raise ValueError("destination branch differs from analyzed HEAD; analyze again")
    confirm(f"Rewrite {destination} {ref}?", yes)
    pending = []
    uploaded = {}
    manifest.update(destination=destination, temporary_refs=pending)
    save(root / "run.json", manifest)
    try:
        if chunk_size:
            commits = text(repo, "rev-list", "--topo-order", "--reverse", "HEAD").splitlines()
            checkpoints = commits[chunk_size - 1::chunk_size]
            if commits and (not checkpoints or checkpoints[-1] != commits[-1]):
                checkpoints.append(commits[-1])
            for index, oid in enumerate(checkpoints):
                temporary = f"refs/heads/git-history-cleaner-{manifest['run_id']}-{index}"
                pending.append(temporary)
                uploaded[temporary] = oid
                manifest["temporary_ref_oids"] = uploaded
                save(root / "run.json", manifest)
                git(repo, "push", f"--force-with-lease={temporary}:", destination, f"{oid}:{temporary}")
        git(repo, "push", f"--force-with-lease={ref}:{plan['old_head']}",
            destination, f"{manifest['new_head']}:{ref}")
        manifest["state"] = "pushed"
    except Exception as exc:
        manifest.update(state="push-failed", error=str(exc))
        raise
    finally:
        for temporary in pending[:]:
            try:
                # Delete only the value we uploaded, never a concurrently changed ref.
                current = text(repo, "ls-remote", "--refs", destination, temporary).split()
                if current:
                    git(repo, "push", f"--force-with-lease={temporary}:{uploaded[temporary]}", destination, ":" + temporary)
                pending.remove(temporary)
            except RuntimeError:
                pass
        save(root / "run.json", manifest)
    return {"pushed": True, "destination": destination, "temporary_refs_remaining": pending}


def cleanup(value, yes=False, include_backup=False):
    root, manifest = load_run(value)
    if not include_backup:
        raise ValueError("cleanup deletes the mirror backup; specify --include-backup")
    if manifest.get("temporary_refs"):
        raise ValueError("temporary remote refs remain; resolve them before deleting this run")
    allowed = {"run.json", "plan.json", "backup.git", "rewritten", "strip-blobs.txt",
               "filename-callback.py", "verification.json"}
    if any(p.name not in allowed or p.is_symlink() for p in root.iterdir()):
        raise ValueError("run contains unexpected files or symlinks; refusing recursive deletion")
    confirm(f"Delete run and mirror backup at {root}?", yes)
    shutil.rmtree(root)
    return {"deleted": str(root)}
