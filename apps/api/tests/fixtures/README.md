The two ONNX files are synthetic, four-dimensional models for embedding adapter tests. They contain a fixed token lookup table, not trained model weights. One returns token states; the other returns a pooled sentence vector. Tests use the real tokenizer and ONNX CPU runtime with these files, without network access.

Regenerate both files from the repository root with:

```bash
uv run --project apps/api --with onnx python apps/api/tests/fixtures/make_embedding_models.py
```

`onnx` is needed only to regenerate the fixtures. It is not a runtime or test dependency.
