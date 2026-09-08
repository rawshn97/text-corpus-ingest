---
name: text-corpus-ingest
description: Search and retrieve text corpora and eBooks across IRC networks (Undernet and IRC Highway) via automated DCC SEND and convert EPUBs to publication-ready PDFs. Use when searching for books, running IRC ingest, operating archive fetcher, or converting document formats.
---

# Text Corpus Ingest Skill

This skill guides AI agents and developers on how to operate, maintain, and extend the Text Corpus Ingest repository.

## 1. Core Architectural Mental Model

Text Corpus Ingest is a high-performance Python engine designed to search for and ingest document archives and eBooks from IRC networks into a local `staging/` directory via automated DCC (Direct Client-to-Client) file transfers.

### Key Pillars
- **Multi-Network Concurrency (`MultiNetworkArchiveFetcher`)**: Coordinates simultaneous connections across multiple IRC networks (default: Undernet on `irc.undernet.org:6667` and IRC Highway on `irc.irchighway.net:6667`).
- **Channel Targets**:
  - Undernet: `#bookz` (search bots: `SearchOok`, `Ook`, `MusicWench`).
  - IRC Highway: `#ebooks` (search bots: `Search`, `SearchOok`).
- **RFC 1413 Ident Daemon (`IdentDaemon`)**: Binds port 113 to answer ident queries, preventing IRC servers from flagging connections as unverified.
- **DCC SEND Protocol (`dcc.py`)**: Parses CTCP DCC SEND offers, initiates direct TCP connections, streams data with 32-bit chunk acknowledgements, and safely writes files to `staging/`.
- **Cooperative Cancellation**: When searching for a specific file (`--hint` or `--raw`), the first network to complete transfer signals sibling networks to disconnect cleanly.
- **EPUB to PDF Pipeline (`scripts/epub_to_pdf.py`)**: Unpacks EPUB containers, inlines media assets as base64 data URIs, applies clean typographic styling, and invokes headless Chrome/Chromium to generate publication-grade PDFs.

---

## 2. Directory Roadmap

| Path | Role |
|---|---|
| `config/irc.yaml` | Base multi-network configuration (servers, channels, bots, identity). |
| `config/irc.local.yaml` | Gitignored local machine overrides (nicks, passwords). |
| `src/corpus_ingest/archive_fetcher.py` | Core search engine and CLI entrypoint (`MultiNetworkArchiveFetcher`). |
| `src/corpus_ingest/config.py` | Dataclass models (`AppConfig`, `NetworkConfig`) and YAML/env loader. |
| `src/corpus_ingest/dcc.py` | CTCP DCC SEND offer parser, IP integer converters, and TCP streaming receiver. |
| `src/corpus_ingest/identd.py` | RFC 1413 TCP 113 ident daemon. |
| `src/corpus_ingest/irc_client.py` | Low-level blocking socket IRC client with line parsing, PING auto-replies, and cancellation callbacks. |
| `scripts/run_fetch.sh` | Shell wrapper for running the ingest CLI inside `.venv`. |
| `scripts/epub_to_pdf.py` | Standalone EPUB to styled PDF converter using headless Chrome. |
| `scripts/test.sh` | Test runner executing `pytest`. |
| `scripts/lint.sh` | Static analysis and format checker (`ruff` + `mypy`). |
| `staging/` | Local staging target directory for downloaded archives, search results, and books. |

---

## 3. Critical Invariants and Agent Operating Rules

1. **No Hardcoded Credentials**:
   - Never commit passwords or nick registration keys.
   - Use `config/irc.local.yaml` or `.env` (`IRC_X_PASSWORD`, `IRC_SERVER_PASSWORD`).
2. **Channel Authenticity**:
   - Undernet active channel: `#bookz`.
   - IRC Highway active channel: `#ebooks` (do not use `#books` or `#ebook`).
3. **Bot Trigger Syntaxes**:
   - General search: `@search <query>` broadcasted to channel and search bots.
   - Raw download trigger: `!bot filename` or `!bot <token>` passed via `--raw`.
   - When using `--raw`, `ArchiveFetcher` transmits the trigger verbatim to the channel.
4. **DCC Filename Normalization**:
   - IRC bots frequently replace spaces with underscores (e.g. `Title_Author.epub`).
   - Filename matching must normalize whitespace, dots, and hyphens.
5. **No Em Dash Character**:
   - Do not emit `\u2014` in any markdown, docstrings, CLI output, or commits. Use colons or hyphens instead.

---

## 4. Key Recipes for Agents

### Search Both Networks for an eBook
```bash
./scripts/run_fetch.sh -q "Eckhart Tolle"
```

### Search a Specific Network Only
```bash
./scripts/run_fetch.sh -q "babok" --network irchighway
```

### Trigger a Specific Bot Download and Stop Immediately
```bash
./scripts/run_fetch.sh --raw -q "!Bsk Business Analysis for Practitioners.epub" --hint "Business Analysis"
```

### Convert Downloaded EPUB to PDF
```bash
.venv/bin/python scripts/epub_to_pdf.py "staging/book.epub" -o "staging/book.pdf"
```

### Run Validation Checks
```bash
./scripts/test.sh
./scripts/lint.sh
```
