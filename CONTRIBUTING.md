# Contributing

Thanks for looking. This is a small project built around one real installation, so changes are easiest to review when they are small and tested.

1. Open an issue first for anything bigger than a fix: say what you want and how you would test it.
2. Branch from `main` (`feat/*`, `fix/*`, `docs/*`) and use Conventional Commits (`feat`, `fix`, `docs`, `test`, `chore`, `infra`).
3. Run the whole suite before you push:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests
```

4. Update the documentation in the same change. Each volatile fact has one owner file; see the Documentation standard in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md). `tests/test_docs.py` fails with the file to fix.
5. Never commit secrets, media, databases or real credentials. Enable the hook with `git config core.hooksPath .githooks`; it scans staged changes, and `scripts/secret-scan.sh --range origin/main..HEAD` scans what you are about to push.
6. Security problems: do not open a public issue; see [SECURITY.md](SECURITY.md).

By contributing you agree your work is released under the project's GPL-3.0 license.
