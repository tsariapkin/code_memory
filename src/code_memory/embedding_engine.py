from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

MODEL_REPO = "Xenova/all-MiniLM-L6-v2"
MODEL_FILENAME = "model_quantized.onnx"
TOKENIZER_FILENAME = "tokenizer.json"
EMBEDDING_DIM = 384

DEFAULT_MODEL_DIR = str(Path.home() / ".code-memory" / "models" / "all-MiniLM-L6-v2-int8")


class EmbeddingEngine:
    def __init__(self, model_dir: str = DEFAULT_MODEL_DIR):
        self.model_dir = model_dir
        self._session = None
        self._tokenizer = None

    @property
    def is_ready(self) -> bool:
        return self._session is not None and self._tokenizer is not None

    def ensure_ready(self) -> None:
        if self.is_ready:
            return
        self._download_if_needed()
        self._load_model()

    def _download_if_needed(self) -> None:
        model_path = os.path.join(self.model_dir, MODEL_FILENAME)
        tokenizer_path = os.path.join(self.model_dir, TOKENIZER_FILENAME)
        if os.path.exists(model_path) and os.path.exists(tokenizer_path):
            return

        logger.info("Downloading embedding model (~23MB, one-time)...")
        os.makedirs(self.model_dir, exist_ok=True)

        from huggingface_hub import hf_hub_download

        # Download model ONNX file
        downloaded_model = hf_hub_download(
            repo_id=MODEL_REPO,
            filename=f"onnx/{MODEL_FILENAME}",
        )
        if not os.path.exists(model_path):
            shutil.copy2(downloaded_model, model_path)

        # Download tokenizer
        downloaded_tokenizer = hf_hub_download(
            repo_id=MODEL_REPO,
            filename=TOKENIZER_FILENAME,
        )
        if not os.path.exists(tokenizer_path):
            shutil.copy2(downloaded_tokenizer, tokenizer_path)

        logger.info("Model downloaded successfully.")

    def _load_model(self) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        model_path = os.path.join(self.model_dir, MODEL_FILENAME)
        tokenizer_path = os.path.join(self.model_dir, TOKENIZER_FILENAME)

        self._session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self._tokenizer = Tokenizer.from_file(tokenizer_path)
        self._tokenizer.enable_truncation(max_length=128)
        self._tokenizer.enable_padding(length=128)

    def embed(self, text: str):
        import numpy as np

        self.ensure_ready()
        encoded = self._tokenizer.encode(text)
        input_ids = np.array([encoded.ids], dtype=np.int64)
        attention_mask = np.array([encoded.attention_mask], dtype=np.int64)
        token_type_ids = np.zeros_like(input_ids)

        outputs = self._session.run(
            None,
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "token_type_ids": token_type_ids,
            },
        )
        # Mean pooling over token embeddings, masked by attention
        token_embeddings = outputs[0]  # (1, seq_len, 384)
        mask = attention_mask[:, :, np.newaxis].astype(np.float32)
        pooled = (token_embeddings * mask).sum(axis=1) / mask.sum(axis=1)
        # L2 normalize
        norm = np.linalg.norm(pooled, axis=1, keepdims=True)
        normalized = pooled / np.maximum(norm, 1e-12)
        return normalized[0].astype(np.float32)

    def embed_batch(self, texts: list[str]):
        import numpy as np

        self.ensure_ready()
        if not texts:
            return np.empty((0, EMBEDDING_DIM), dtype=np.float32)
        encoded_batch = self._tokenizer.encode_batch(texts)
        input_ids = np.array([e.ids for e in encoded_batch], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encoded_batch], dtype=np.int64)
        token_type_ids = np.zeros_like(input_ids)

        outputs = self._session.run(
            None,
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "token_type_ids": token_type_ids,
            },
        )
        token_embeddings = outputs[0]
        mask = attention_mask[:, :, np.newaxis].astype(np.float32)
        pooled = (token_embeddings * mask).sum(axis=1) / mask.sum(axis=1)
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        return (pooled / np.maximum(norms, 1e-12)).astype(np.float32)

    @staticmethod
    def cosine_similarity(query_vec, matrix):
        import numpy as np

        if matrix.size == 0:
            return np.array([])
        return matrix @ query_vec

    @staticmethod
    def vector_to_blob(vec) -> bytes:
        import numpy as np

        return vec.astype(np.float32).tobytes()

    @staticmethod
    def blob_to_vector(blob: bytes):
        import numpy as np

        return np.frombuffer(blob, dtype=np.float32)
