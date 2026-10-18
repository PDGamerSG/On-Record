# Local Gemma runtime

The brain package includes a small provider-neutral client for exercising Gemma 4 through Ollama, Gemini, or an OpenAI-compatible endpoint. The offline fake provider is useful for CI and does not download a model.

## Ollama setup

Install [Ollama](https://ollama.com), then start the configured model from the repository root:

```bash
./apps/api/scripts/gemma.sh
```

The default is `gemma4:12b-it-qat`. It is a quantized 12B model and needs several gigabytes of local storage. Set `WSW_OLLAMA_MODEL=gemma4:e4b` when a smaller model is needed. The script waits for the local service, pulls the model once, and can run a prompt when given an argument.

The runtime uses Ollama's native `/api/chat` endpoint with thinking disabled. JSON responses are validated with a Pydantic schema and receive one repair attempt when the model returns malformed output. The Ollama Gemma 4 variants that support native audio can also be used for transcription through the same client.

## Smoke benchmark

The checked-in corpus keeps the benchmark repeatable. Run the offline path with:

```bash
uv run --project apps/api python apps/api/scripts/bench_gemma.py --provider fake
```

For a local model, use:

```bash
uv run --project apps/api python apps/api/scripts/bench_gemma.py \
  --provider ollama \
  --model gemma4:12b-it-qat
```

Reports are written to `apps/api/benchmarks/results/latest.json`, which is ignored except for the directory placeholder. Each report includes per-case latency, JSON validity, exact matches, and field-match rates. Hosted providers can be selected with `--provider gemini` or `--provider openai` and their usual environment variables.
