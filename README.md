# Text Corpus Ingest

Lab IRC client for text corpus retrieval: channel search (`@search`) plus DCC (Direct Client-to-Client) file receive into a local staging directory.

Architecture mirrors the Soulseek (`slskd`) sync pattern used in `dj-set-prep`, swapping P2P search for IRC channel monitoring + DCC transfer.

## Directory tree

```
text-corpus-ingest/
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── config/
│   └── irc.yaml              # server, nick, channels, @search, staging
├── scripts/
│   ├── setup.sh              # venv + deps
│   └── run_fetch.sh          # CLI wrapper
├── src/
│   └── corpus_ingest/
│       ├── __init__.py
│       ├── config.py         # YAML + env loader
│       ├── irc_client.py     # socket IRC session
│       ├── dcc.py            # DCC SEND receive stream
│       ├── identd.py         # optional ident responder
│       └── archive_fetcher.py  # orchestrator
├── staging/                  # inbound archives (gitignored)
└── tests/
    └── test_dcc_parse.py
```

## Quick start

```bash
./scripts/setup.sh
cp .env.example .env          # optional nick override
# edit config/irc.yaml with your lab IRC host / channel
./scripts/run_fetch.sh --query "YOUR_SEARCH_TERMS"
```

By default the client joins `#bookz`, waits, then sends `@search {query}` on that channel and to configured search bots (`SearchOok`, `Ook`, `MusicWench`). It accepts the first matching DCC SEND into `staging/`.

Public ebook bots often ignore new or unregistered nicks. Register on Undernet CService (X), then set `IRC_X_PASSWORD` in `.env`. Ident on port 113 also helps if you can bind or port-forward it.

```bash
# default: PRIVMSG "#channel" :@search frankenstein
./scripts/run_fetch.sh -q "frankenstein"

# send the query string verbatim (no @search prefix)
./scripts/run_fetch.sh -q "!botname 12" --raw

# override template for one run
./scripts/run_fetch.sh -q "odyssey" --template "@search {query}"
```

## Lab use

Point `config/irc.yaml` (or gitignored `config/irc.local.yaml`) at your lab IRC daemon and channels. Prefer a local [MiniIRCd](https://github.com/MiniIRCd) instance when developing or validating the client.

## Note on MiniIRCd

MiniIRCd is a lightweight **IRC server**, not a client. This repo implements a **client** (stdlib sockets) that speaks IRC + DCC SEND receive.
