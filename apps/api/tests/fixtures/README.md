The three ONNX files are synthetic, four-dimensional models for embedding adapter tests. They contain a fixed token lookup table, not trained model weights. Two store the table inline and return token states or a pooled sentence vector. The third keeps its table in `model_quantized.onnx_data`, which lets the tests reproduce and recover from missing external weights. Tests use the real tokenizer and ONNX CPU runtime with these files, without network access.

Regenerate the fixtures from the repository root with:

```bash
uv run --project apps/api --with onnx python apps/api/tests/fixtures/make_embedding_models.py
```

`onnx` is needed only to regenerate the fixtures. It is not a runtime or test dependency.
