# cybergarage-pub-cleaner

Tools for compressing PNG assets and cleaning old PNG/JPEG blobs from cybergarage-pub history.

## Usage

```sh
./git-compress cybergarage-pub shared
./git-compress cybergarage-pub books/wb/books/act
```

The command creates a mirror backup and a clean working clone in a temporary directory, runs PNG compression and git-filter-repo outside the working repository, then pushes the rewritten branch with --force-with-lease after confirmation.

Check a repository after cleanup:

```sh
./git-compress-chk
./git-compress-chk --blob-id e48b4914a5af65e4e8569be8c5aa9cfc05a7b50e
```
