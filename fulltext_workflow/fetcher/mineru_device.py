"""MinerU runtime device selection: prefer CUDA, fallback to CPU."""
from __future__ import annotations

import os

import config

_DEVICE_LOGGED = False


def resolve_mineru_device(preference: str | None = None) -> str:
    """
    Resolve MinerU execution device.

    preference:
      - auto (default): cuda when torch.cuda.is_available(), else cpu
      - cuda: same as auto but logs when falling back to cpu
      - cpu: force cpu
    """
    pref = (preference or config.MINERU_DEVICE).strip().lower()
    if pref in ("gpu", "cuda"):
        pref = "cuda"

    if pref == "cpu":
        return "cpu"

    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except ImportError:
        pass

    if pref == "cuda":
        print("[MinerU] CUDA not available (check GPU driver / CUDA PyTorch), using CPU")
    return "cpu"


def apply_mineru_env(*, preference: str | None = None, log: bool = True) -> str:
    """Set MinerU env vars before importing mineru modules."""
    global _DEVICE_LOGGED

    os.environ.setdefault("MINERU_MODEL_SOURCE", config.MINERU_MODEL_SOURCE)

    if os.environ.get("MINERU_DEVICE_MODE"):
        device = os.environ["MINERU_DEVICE_MODE"]
    else:
        device = resolve_mineru_device(preference)
        os.environ["MINERU_DEVICE_MODE"] = device

    if log and not _DEVICE_LOGGED:
        print(f"[MinerU] device={device}, backend={config.MINERU_BACKEND}")
        _DEVICE_LOGGED = True

    return device
