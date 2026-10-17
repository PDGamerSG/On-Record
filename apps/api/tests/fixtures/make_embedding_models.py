"""Regenerate tiny test models: uv run --with onnx python <this-file>."""

from pathlib import Path

import numpy as np
from onnx import TensorProto, checker, helper, numpy_helper, save

DESTINATION = Path(__file__).parent


def make_model(pooled: bool) -> None:
    inputs = [
        helper.make_tensor_value_info(name, TensorProto.INT64, ["batch", "sequence"])
        for name in ("input_ids", "attention_mask", "token_type_ids")
    ]
    # Prompt tokens are zero except text: (1, 0, 0, 0) and query: (0, 1, 0, 0).
    # A large pad vector makes a missing attention mask visible in test results.
    table = np.zeros((12, 4), dtype=np.float32)
    table[0], table[1] = [1000, 1000, 1000, 1000], [1, 1, 1, 1]
    table[5], table[9] = [1, 0, 0, 0], [0, 1, 0, 0]
    table[10], table[11] = [3, 4, 0, 0], [0, 0, 6, 8]
    initializers = [numpy_helper.from_array(table, name="table")]
    nodes = [helper.make_node("Gather", ["table", "input_ids"], ["last_hidden_state"])]
    outputs = [helper.make_tensor_value_info("last_hidden_state", TensorProto.FLOAT, ["batch", "sequence", 4])]
    if pooled:
        initializers.extend([
            numpy_helper.from_array(np.array([2], dtype=np.int64), name="expand_axis"),
            numpy_helper.from_array(np.array([1], dtype=np.int64), name="sequence_axis"),
            numpy_helper.from_array(np.array(1.0, dtype=np.float32), name="one"),
        ])
        nodes.extend([
            helper.make_node("Cast", ["attention_mask"], ["mask"], to=TensorProto.FLOAT),
            helper.make_node("Unsqueeze", ["mask", "expand_axis"], ["weights"]),
            helper.make_node("Mul", ["last_hidden_state", "weights"], ["weighted"]),
            helper.make_node("ReduceSum", ["weighted", "sequence_axis"], ["total"], keepdims=0),
            helper.make_node("ReduceSum", ["weights", "sequence_axis"], ["count"], keepdims=0),
            helper.make_node("Max", ["count", "one"], ["denominator"]),
            helper.make_node("Div", ["total", "denominator"], ["sentence_embedding"]),
        ])
        outputs = [helper.make_tensor_value_info("sentence_embedding", TensorProto.FLOAT, ["batch", 4])]
    graph = helper.make_graph(nodes, "embedding-test", inputs, outputs, initializers)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 18)], ir_version=9)
    checker.check_model(model)
    save(model, DESTINATION / ("pooled_embedding.onnx" if pooled else "token_embeddings.onnx"))


if __name__ == "__main__":
    make_model(pooled=False)
    make_model(pooled=True)
