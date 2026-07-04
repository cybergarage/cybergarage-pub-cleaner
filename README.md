# cybergarage-pub-cleaner

Tools for cleaning old PNG/JPEG blobs from cybergarage-pub history.

## Usage

Clean one target directory:

```sh
./git-compress cybergarage-pub shared
```

Clean multiple target directories in one history rewrite:

```sh
./git-compress cybergarage-pub shared books/wb/books/act books/wb/golf
```

The command creates a `git-compress-*` work directory in the current directory by default. That work directory contains a mirror backup, reports, and a clean working clone. The command uses git-filter-repo outside the working repository to remove historical PNG/JPEG blobs under the target directories while protecting the current HEAD image blobs.

After confirmation, the command preloads the rewritten history through temporary branches before updating the target branch with --force-with-lease. This splits large history rewrites into smaller pushes to avoid GitHub's per-pack size limit. Use `--push-chunk-size <commits>` to change the preload chunk size, or `--push-chunk-size 0` to disable preloading. Use `--work-dir <path>` to choose an explicit work directory.

Remove generated work directories after verification:

```sh
./git-compress-clean
./git-compress-clean --yes
```

Check a repository after cleanup:

```sh
./git-compress-chk
./git-compress-chk --blob-id e48b4914a5af65e4e8569be8c5aa9cfc05a7b50e
```
