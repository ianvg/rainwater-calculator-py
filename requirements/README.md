# Locked dependencies

`desktop-build.txt` contains the reviewed, hash-locked Windows release-build,
documentation, SBOM, and vulnerability-audit dependencies. `viewer.txt` contains
the reviewed, hash-locked optional viewer dependencies. The project itself is
installed separately with `--no-deps` after its lock has been installed.

Regenerate both locks from a clean Python 3.10 environment whenever
`pyproject.toml` changes:

```powershell
python -m pip install "pip<26" pip-tools==7.5.2
python -m piptools compile pyproject.toml --extra desktop-build --extra docs --extra security --extra lock-bootstrap --generate-hashes --resolver backtracking --strip-extras --allow-unsafe --output-file requirements\desktop-build.txt
python -m piptools compile pyproject.toml --extra viewer --extra lock-bootstrap --generate-hashes --resolver backtracking --strip-extras --allow-unsafe --output-file requirements\viewer.txt
```

Review version changes and their upstream release notes before committing a
regenerated lock. Release installation must retain pip's `--require-hashes`.
Install the project afterward with `--no-build-isolation --no-deps`; do not
install its extras again because that would permit pip to resolve packages
outside the reviewed lock.
