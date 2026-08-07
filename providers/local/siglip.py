"""SigLIP text and image towers as local encoder slots.

Spec: docs/specs/pool-preparation.md section 8 (U2, D3). The two
classes fill the TextEncoder and ImageEncoder protocols as drop-in
alternatives for the OpenRouter embeddings endpoint. The torch stack
imports in the constructors, thus this module imports without torch
available. The device comes from the constructor, not from the config,
and is not part of the config_hash: the determinism guarantee has the
scope of one machine and environment (spec section 14).
"""

import io
from collections.abc import Sequence
from typing import NamedTuple

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from core.canonical import canonical_json, sha256_hex
from core.types import Vectors


class SiglipConfig(NamedTuple):
    """The full parameter set of one SigLIP tower slot.

    The config_hash covers all fields - a change to one of them moves
    the cache tree (R12). The device is not a field here: it is a
    constructor argument and not part of the hash.
    """

    checkpoint: str
    revision: str
    dimension: int
    dtype: str


def siglip_text_config_hash(config: SiglipConfig) -> str:
    """The SHA-256 hex digest of the canonical JSON of the text-tower config."""
    return sha256_hex(canonical_json({"provider": "local-siglip-text", **config._asdict()}))


def siglip_image_config_hash(config: SiglipConfig) -> str:
    """The SHA-256 hex digest of the canonical JSON of the image-tower config."""
    return sha256_hex(canonical_json({"provider": "local-siglip-image", **config._asdict()}))


def _checked_dimension(rows: NDArray[np.float64], expected: int) -> None:
    """Raises ValueError when the model width does not agree with the config."""
    width = int(rows.shape[1])
    if width != expected:
        raise ValueError(
            f"model output dimension {width} does not agree with "
            f"configured dimension {expected}"
        )


def _unit_rows(rows: NDArray[np.float64]) -> Vectors:
    """Unit-normalize each row in float64, then cast to float32.

    A row with a non-finite or zero norm raises ValueError - it must
    not become a plausible unit vector (no silent fallbacks).
    """
    norms = np.linalg.norm(rows, axis=1, keepdims=True)  # (B, 1)
    if not np.all(np.isfinite(norms)) or np.any(norms == 0.0):
        raise ValueError("encoder output has a non-finite or zero-norm row")
    return (rows / norms).astype(np.float32)


class SiglipTextEncoder:
    """TextEncoder through a local SigLIP checkpoint - the p04 slot.

    The model loads at construction with the configured checkpoint,
    revision, and dtype, in eval mode. Inference uses
    torch.inference_mode with no autocast. Tokenization pads to the
    model maximum length, the SigLIP training shape. Batching is
    internal, in chunks of batch_size.
    """

    def __init__(self, config: SiglipConfig, device: str = "cuda", batch_size: int = 32) -> None:
        import torch
        from transformers import AutoModel, AutoProcessor

        self._config = config
        self._device = device
        self._batch_size = batch_size
        self._torch = torch
        self._dtype = getattr(torch, config.dtype)
        self._model = AutoModel.from_pretrained(
            config.checkpoint, revision=config.revision, dtype=self._dtype
        ).to(device)
        self._model.eval()
        self._processor = AutoProcessor.from_pretrained(
            config.checkpoint, revision=config.revision
        )

    @property
    def config_hash(self) -> str:
        return siglip_text_config_hash(self._config)

    def encode_texts(self, texts: Sequence[str]) -> Vectors:
        """The output is float32 (B, d), each row unit-norm.

        An empty input gives a (0, d) array without a model forward
        step. A model width different from the configured dimension
        raises ValueError with the two numbers named.
        """
        if not texts:
            return np.zeros((0, self._config.dimension), dtype=np.float32)
        batches: list[NDArray[np.float64]] = []
        for start in range(0, len(texts), self._batch_size):
            chunk = list(texts[start : start + self._batch_size])
            encoded = self._processor(
                text=chunk, padding="max_length", truncation=True, return_tensors="pt"
            )
            moved = {name: tensor.to(self._device) for name, tensor in encoded.items()}
            with self._torch.inference_mode():
                features = self._model.get_text_features(**moved)  # (b, d)
            batches.append(features.float().cpu().numpy().astype(np.float64))
        stacked = np.concatenate(batches, axis=0)  # (B, d)
        _checked_dimension(stacked, self._config.dimension)
        return _unit_rows(stacked)


class SiglipImageEncoder:
    """ImageEncoder through a local SigLIP checkpoint - the p06 slot.

    The model loads at construction with the configured checkpoint,
    revision, and dtype, in eval mode. Inference uses
    torch.inference_mode with no autocast. Image bytes decode through
    PIL to RGB. Batching is internal, in chunks of batch_size.
    """

    def __init__(self, config: SiglipConfig, device: str = "cuda", batch_size: int = 32) -> None:
        import torch
        from transformers import AutoModel, AutoProcessor

        self._config = config
        self._device = device
        self._batch_size = batch_size
        self._torch = torch
        self._dtype = getattr(torch, config.dtype)
        self._model = AutoModel.from_pretrained(
            config.checkpoint, revision=config.revision, dtype=self._dtype
        ).to(device)
        self._model.eval()
        self._processor = AutoProcessor.from_pretrained(
            config.checkpoint, revision=config.revision
        )

    @property
    def config_hash(self) -> str:
        return siglip_image_config_hash(self._config)

    def encode_images(self, images: Sequence[bytes]) -> Vectors:
        """The output is float32 (B, d), each row unit-norm.

        An empty input gives a (0, d) array without a model forward
        step. A model width different from the configured dimension
        raises ValueError with the two numbers named.
        """
        if not images:
            return np.zeros((0, self._config.dimension), dtype=np.float32)
        batches: list[NDArray[np.float64]] = []
        for start in range(0, len(images), self._batch_size):
            chunk = images[start : start + self._batch_size]
            decoded = [Image.open(io.BytesIO(item)).convert("RGB") for item in chunk]
            encoded = self._processor(images=decoded, return_tensors="pt")
            pixel_values = encoded["pixel_values"].to(device=self._device, dtype=self._dtype)
            with self._torch.inference_mode():
                features = self._model.get_image_features(pixel_values=pixel_values)  # (b, d)
            batches.append(features.float().cpu().numpy().astype(np.float64))
        stacked = np.concatenate(batches, axis=0)  # (B, d)
        _checked_dimension(stacked, self._config.dimension)
        return _unit_rows(stacked)
