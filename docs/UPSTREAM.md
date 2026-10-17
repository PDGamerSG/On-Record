# Source notes

On Record imports code from [Hydra-Of-Malice/hack-october-who-said-what-brain](https://github.com/Hydra-Of-Malice/hack-october-who-said-what-brain), starting at commit [`69b2d11c1662f38110f35a2d8f4896345f075a1e`](https://github.com/Hydra-Of-Malice/hack-october-who-said-what-brain/commit/69b2d11c1662f38110f35a2d8f4896345f075a1e).

The original project and its contributors retain credit for that implementation. Its Apache 2.0 license is included in this repository. On Record adds the source in separate feature branches, with integration changes recorded in each PR.

The initial changes set the display name to On Record, keep demo seeding off in the example environment, and adapt the setup documentation to the files available here. Internal package names and environment variables retain the `wsw` names used by the source.

The source documents Claude Code assistance. Codex assists this repository's staged import, integration checks, and documentation. Test results and performance figures reported by the source are not new measurements from On Record.

The graph-schema branch imports `graph/cypher.py` and `graph/text.py` unchanged from that snapshot. Its package initializer exposes only the modules present here. The Compose file includes the source's database service, with ports bound to localhost; the application service comes later. The schema checks adapt the source's index assertions and add direct full-text/vector retrieval checks so they can run before `GraphStore` is imported.

The text-embeddings branch imports the `HashEmbedder` portion of `brain/embed.py` from the same pinned snapshot. It adds explicit positive-integer dimension validation to match the graph store's contract, and exposes only the available embedder through `brain/__init__.py`. Its tests check normalisation, basic lexical ranking, empty input, and dimension validation.

The model-embeddings branch adds the `GemmaEmbedder` adapter from the pinned snapshot. It validates constructor options before loading the model and downloads plain files under `WSW_MODELS_DIR`, keeping the ONNX graph and its external weights together instead of resolving them through separate cache symlinks. The tests use new synthetic ONNX fixtures and the real CPU runtime and tokenizer; no trained weights are committed.
