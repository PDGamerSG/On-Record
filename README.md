# On Record

A meeting assistant that connects what was said to the person who said it.

This repository is being assembled in feature-sized PRs from [Who Said What Brain](https://github.com/Hydra-Of-Malice/hack-october-who-said-what-brain). It currently includes the shared Python package, a local FalkorDB service, and the graph query definitions. The application store, recording, assistant, and web interface follow in separate branches.

The display name lives in `brand.json`. `.env.example` lists the configuration the application will use; keep local values in an ignored `.env` file.

See [the source notes](docs/UPSTREAM.md) for the original snapshot and attribution. The code is licensed under [Apache 2.0](LICENSE).

## Python setup

Install [uv](https://docs.astral.sh/uv/), then run from the repository root:

```bash
uv sync --project apps/api --frozen
uv run --project apps/api python -c "from wsw_brain.brand import product_name; print(product_name())"
```

The package uses Python 3.12. It currently provides configuration, shared data contracts, and an in-process event bus. The HTTP server and web interface arrive in later PRs, so there is no application to start yet.

## Offline text embeddings

`HashEmbedder` converts meeting text and search queries into repeatable, normalised vectors without a model download. It uses word and word-pair overlap, so it is useful for local tests and offline search; it does not provide a language model's semantic understanding. Its tokenizer handles ASCII letters and digits. Empty or punctuation-only text receives a fixed unit vector so it remains valid for cosine indexes.

```bash
uv run --project apps/api python -c "from wsw_brain.brain import HashEmbedder; e = HashEmbedder(); print(e.name, len(e.embed_query('pricing deck')))"
```

The default dimension is 768. Pass a positive integer to `HashEmbedder(dim)` to match an existing vector index. The model-backed embedder and configured provider selection will arrive in a later PR.

## Local graph database

Start Docker, then run:

```bash
docker compose up -d --wait falkordb
```

FalkorDB is available at `127.0.0.1:6379`, with its browser at <http://localhost:3000>. Both ports bind to this machine only. Database files are kept in the `falkordb_data` volume when the container stops. If you use Colima without making it your default Docker context, use `docker --context colima compose` for these commands.

The schema definitions in `apps/api/wsw_brain/graph/cypher.py` cover range, full-text, and vector indexes. To verify them against the running database:

```bash
uv run --project apps/api pytest apps/api/tests/test_graph_schema.py -q
```

These checks create and delete their own temporary graphs. They verify that reapplying indexes preserves existing records, and that full-text and vector searches return the expected utterances. Set `WSW_FALKORDB_URL` in the command environment to test a different server. The checks fail if the database is unavailable.

Stop the service with `docker compose stop falkordb`. The application store will create indexes for the configured application graph when it is added in the next PR.
