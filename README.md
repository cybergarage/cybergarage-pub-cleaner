# cybergarage-pub-cleaner

Tools for compressing PNG assets and cleaning old PNG/JPEG blobs from cybergarage-pub history.

## Usage

Clean one target directory:

```sh
./git-compress cybergarage-pub shared
```

Clean multiple target directories in one history rewrite:

```sh
./git-compress cybergarage-pub shared books/wb/books/act books/wb/golf
```

The command creates a `git-compress-*` work directory in the current directory by default. That work directory contains a mirror backup, reports, and a clean working clone. The command runs PNG compression and git-filter-repo outside the working repository, then pushes the rewritten branch with --force-with-lease after confirmation. Use `--work-dir <path>` to choose an explicit location.

Check a repository after cleanup:

```sh
./git-compress-chk
./git-compress-chk --blob-id e48b4914a5af65e4e8569be8c5aa9cfc05a7b50e
```
