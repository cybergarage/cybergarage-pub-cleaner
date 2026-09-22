# Changelog

## 1.0.0 — Unreleased

First general-purpose packaged release, under the name `git-history-cleaner`.

- Add analyze, rewrite, verify, push, rebase and cleanup subcommands.
- Separate remote publication from analysis and isolated history rewriting.
- Preserve the complete current tree and protect unselected historical paths.
- Support literal paths, deleted directories, extensions, exclusions and sizes.
- Handle Unicode, spaces, tabs and newlines in Git paths.
- Add immutable cleanup plans, run records, machine-readable results and errors.
- Keep full mirror backups and retain local rebase backup branches.
- Require explicit backup deletion and validated run directories for cleanup.
- Make preload pushes optional and support histories shorter than a chunk.
- Remove hardcoded organizations, repository URLs and default branch names.
- Package for Python 3.10+, macOS and Linux with MIT licensing.
- Add local Git integration tests and build/publish workflows.

### Breaking changes

The pre-release git-compress command family is replaced by the unified CLI.
See [migration notes](docs/migration.md). 1.0.0 publication is pending; the version
in package metadata prepares the distribution and does not imply a PyPI release.
