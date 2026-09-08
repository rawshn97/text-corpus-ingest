# AGENTS.md: Text Corpus Ingest

Operating rules for AI agents in `rawshn97/text-corpus-ingest`. Single branch: **`main`**.

## Product / purpose

- High-performance multi-network IRC search and automated DCC text corpus ingest engine.
- Concurrently searches Undernet (`#bookz`) and IRC Highway (`#ebooks`), receives DCC SEND offers into `staging/`, and converts EPUBs to styled PDFs.
- Overview: [`README.md`](README.md) · Skill: [`.cursor/skills/text-corpus-ingest/SKILL.md`](.cursor/skills/text-corpus-ingest/SKILL.md)

## Layout

| Path | Role |
|---|---|
| `src/corpus_ingest/archive_fetcher.py` | Multi-network search orchestrator and CLI entrypoint |
| `src/corpus_ingest/irc_client.py` | Low-level socket client (CRLF lines, auto-PONG, stop checks) |
| `src/corpus_ingest/config.py` | Configuration models (`AppConfig`, `NetworkConfig`) and YAML loader |
| `src/corpus_ingest/dcc.py` | DCC SEND parser, IP converters, and TCP streaming receiver |
| `src/corpus_ingest/identd.py` | RFC 1413 ident daemon (TCP 113) |
| `config/irc.yaml` | Default multi-network settings (Undernet `#bookz` + IRC Highway `#ebooks`) |
| `config/irc.local.yaml` | Local machine overrides (gitignored) |
| `scripts/run_fetch.sh` | CLI runner script inside virtual environment |
| `scripts/epub_to_pdf.py` | EPUB to styled PDF converter using headless Chrome |
| `scripts/test.sh` | Test runner (`pytest`) |
| `scripts/lint.sh` | Linter and typechecker (`ruff` + `mypy`) |
| `staging/` | Local destination for downloaded files |

## Commands

```bash
# Setup virtual environment
./scripts/setup.sh

# Run multi-network search (default: Undernet + IRC Highway)
./scripts/run_fetch.sh -q "query"

# Target specific network only
./scripts/run_fetch.sh -q "query" --network irchighway

# Download specific offer and stop immediately
./scripts/run_fetch.sh --raw -q "!bot filename.epub" --hint "filename"

# Convert downloaded EPUB to styled PDF
.venv/bin/python scripts/epub_to_pdf.py "staging/book.epub" -o "staging/book.pdf"

# Run tests and linter
./scripts/test.sh
./scripts/lint.sh
```

## Hard constraints

1. **Never commit credentials**: Keep secrets in `.env` or `config/irc.local.yaml`.
2. **Channel correctness**: Undernet is `#bookz`. IRC Highway is `#ebooks` (never `#books` or `#ebook`).
3. **Ident daemon**: Bind port 113 once per session; do not start conflicting instances across threads.
4. **Cooperative cancellation**: When downloading a specific book, cancel sibling searches cleanly as soon as the first network finishes.
5. **No em dash**: Do not use `\u2014` in any markdown, docs, commits, or code strings. Use hyphens or colons.
6. **Keep repo private**: Do not change visibility to public unless explicitly requested.

## Agent workflow

1. Read this file + [`README.md`](README.md) before making edits.
2. Load skill [`.cursor/skills/text-corpus-ingest/SKILL.md`](.cursor/skills/text-corpus-ingest/SKILL.md) for domain details.
3. For new books: search both networks with `./scripts/run_fetch.sh -q "<book>"`.
4. Inspect search results in `staging/`, pick best bot trigger, and fetch with `--raw`.
5. Run `./scripts/lint.sh` and `./scripts/test.sh` before committing changes.

## Secrets / local-only

- Never commit: `.env`, `config/irc.local.yaml`, `staging/*` (except `.gitkeep`).
- Reference template: [`.env.example`](.env.example).

## Docs

- [`README.md`](README.md) · [`CONTRIBUTING.md`](CONTRIBUTING.md) · [`LICENSE`](LICENSE)
