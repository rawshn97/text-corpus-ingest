# Contributing to Text Corpus Ingest

Thank you for your interest in contributing to Text Corpus Ingest!

## Development Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/rawshn97/text-corpus-ingest.git
   cd text-corpus-ingest
   ```

2. Run the setup script to initialize the virtual environment:
   ```bash
   ./scripts/setup.sh
   ```

3. Install development dependencies:
   ```bash
   .venv/bin/pip install -e ".[dev]"
   ```

## Running Tests and Linter

Before submitting changes, ensure all tests and lint checks pass:

```bash
# Run tests
./scripts/test.sh

# Run linter and type checker
./scripts/lint.sh
```

## Pull Request Guidelines

1. Create a descriptive feature branch: `git checkout -b feat/my-feature`.
2. Write unit tests for new functionality in `tests/`.
3. Keep code typed and documented with docstrings.
4. Do not use em dash characters (U+2014) in commits, docs, or code strings: use colons, hyphens, or commas instead.
5. Never commit private credentials or personal `.env` files.
