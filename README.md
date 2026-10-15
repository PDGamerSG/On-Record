# On Record

A meeting assistant that connects what was said to the person who said it.

This repository is being assembled in feature-sized PRs from [Who Said What Brain](https://github.com/Hydra-Of-Malice/hack-october-who-said-what-brain). The first change adds project settings, branding, and the shared Python package. Graph storage, recording, the assistant, and the web interface follow in separate branches.

The display name lives in `brand.json`. `.env.example` lists the configuration the application will use; keep local values in an ignored `.env` file.

See [the source notes](docs/UPSTREAM.md) for the original snapshot and attribution. The code is licensed under [Apache 2.0](LICENSE).

## Python setup

Install [uv](https://docs.astral.sh/uv/), then run from the repository root:

```bash
uv sync --project apps/api --frozen
uv run --project apps/api python -c "from wsw_brain.brand import product_name; print(product_name())"
```

The package uses Python 3.12. It currently provides configuration, shared data contracts, and an in-process event bus. The HTTP server and web interface arrive in later PRs, so there is no application to start yet.
