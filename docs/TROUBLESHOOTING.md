# Troubleshooting

Common setup problems and how to fix them. Commands run from the repository root unless a
folder is shown.

## Docker and the graph database

The graph database (FalkorDB) runs in Docker. Start it with:

```
docker compose up -d --wait falkordb
```

### "Cannot connect to the Docker daemon"

Docker is not running. Start Docker Desktop, or if you use Colima:

```
colima start
```

Then run the compose command again.

### Colima: `docker compose` cannot find the daemon

Colima only works with plain `docker` commands when it is your default Docker context.
If you have not made it the default, name the context on each command:

```
docker --context colima compose up -d --wait falkordb
docker --context colima compose stop falkordb
```

Or switch once with `docker context use colima`. `docker context ls` shows which context is
active.

### Port 6379 or 3000 is already in use

The compose file publishes FalkorDB on `127.0.0.1:6379` and its browser on
`127.0.0.1:3000`. If another Redis (or any other program) already uses either port, the
container fails to start. Find what is using the port:

```
lsof -i :6379
```

Stop that program, or change the left-hand port number in `docker-compose.yml` and set
`WSW_FALKORDB_URL` to match, for example `falkor://127.0.0.1:6380`. Do not commit that local
port change.

### `--wait` times out or the container is unhealthy

The health check runs `redis-cli ping` every 5 seconds. Look at what the container reported:

```
docker compose ps --all
docker compose logs --no-color --tail=200 falkordb
```

### Tests fail because the database is unavailable

The graph and retrieval tests need a running database and fail rather than skip when it is
missing. Start FalkorDB first, then rerun the tests. To test against a different server, set
`WSW_FALKORDB_URL` in the command environment:

```
WSW_FALKORDB_URL=falkor://127.0.0.1:6379 uv run --project apps/api pytest -q
```

Only `test_graph.py`, `test_graph_schema.py`, `test_retrieve_graph.py` and `test_documents_ingest.py`
need the database, and they are marked `live`. To run everything else without it:

```
uv run --project apps/api pytest -q -m "not live"
```

### Starting over with a clean database

`docker compose stop falkordb` keeps your data in the `falkordb_data` volume. To delete the
data as well:

```
docker compose down -v
```

## Node and the web app

### Which Node version?

The web app needs Node 20.19 or later, or Node 22.12 or later. Check yours:

```
node -v
```

If it is older, install a newer one with your version manager (for example `nvm install 22`
then `nvm use 22`) and run the install again.

### Installing dependencies

Use `npm ci` rather than `npm install`. It installs exactly what `package-lock.json` lists
and does not rewrite the lockfile:

```
cd apps/web
npm ci
npm run dev
```

If an install fails partway, delete `apps/web/node_modules` and run `npm ci` again.

### The dev server is not on port 5173

If 5173 is busy, Vite moves to the next free port. Open the address it prints in the
terminal.

### The app shows demo meetings, not my data

The UI uses two bundled demo meetings when no API answers on `/api/health`, and the HTTP
server is not part of this repository yet. You can force a mode:

- add `?demo=1` to the URL, or set `VITE_DEMO=1`, to always use demo data
- add `?demo=0`, or set `VITE_DEMO=0`, to always call the API

### Proxy errors for `/api` or `/ws` in the terminal

With `?demo=0` and no API running, requests to `/api` and `/ws` are proxied to
`http://127.0.0.1:8000` and fail. Remove `?demo=0`, or point the proxy at your API:

```
WSW_API_URL=http://127.0.0.1:9000 npm run dev
```

To start the API itself on the default port, run this from the repository root:

```
uv run --project apps/api python -m wsw_brain.cli
```

Add `--port 9000` (or any free port) to run it elsewhere, and set `WSW_API_URL` to match.

It serves `/api/status`, `/api/capabilities` and `/api/events`, but not the meeting routes yet, so the
meeting pages still fail with `?demo=0`. Leave demo mode on for them until the meeting API arrives.

### Build or lint errors

`npm run build` type-checks with TypeScript before bundling, so a type error stops the
build. `npm run lint` runs oxlint.

## Python and uv

The API package needs Python 3.12 or 3.13. [uv](https://docs.astral.sh/uv/) installs and
uses the right version:

```
uv python install
uv sync --project apps/api --frozen
```

`--frozen` installs exactly what `apps/api/uv.lock` lists. Always pass `--project apps/api`
when you run from the repository root.

### My `.env` changes have no effect

Settings are read once when the process starts. Restart it after editing `.env` or changing
an environment variable. The file must be named `.env` and sit in the repository root, next
to `.env.example`.

### The embedding model fails to download or load

The first use of `GemmaEmbedder` downloads the model into `WSW_MODELS_DIR` (default
`models/`), so it needs network access once. A missing download is retried a single time.
If loading still fails, `get_embedder()` logs a warning and falls back to `HashEmbedder`,
and that choice is kept until the process restarts.

- To work offline, set `WSW_EMBEDDER=hash`.
- After repairing a failed download, restart the process.
- Vectors from the two embedders are not compatible. When you switch, use a new
  `WSW_GRAPH` name or rebuild the stored embeddings.

### Answers look like quoted evidence lines

`WSW_LLM_PROVIDER=auto` uses Gemini when `GEMINI_API_KEY` is set. Otherwise it uses the local
Ollama model only if its exact tag is installed, and falls back to a deterministic fake that
quotes evidence lines. To use a local model:

```
ollama pull gemma4:e4b
```

Make sure `WSW_OLLAMA_MODEL` matches that tag exactly. To skip the check, set
`WSW_LLM_PROVIDER=ollama`. If you have a Gemini key set but want the local model, also set
`WSW_LLM_PROVIDER=ollama`.