"""Unit tests for runtime device resolution.

resolve_device imports torch lazily, thus a stub module in sys.modules
exercises the selection rule with no torch install.
"""

import sys
import types

import pytest

from pool.preparation.run import resolve_device


def _stub_torch(monkeypatch, cuda: bool, xpu: bool) -> None:
    stub = types.ModuleType("torch")
    stub.cuda = types.SimpleNamespace(is_available=lambda: cuda)
    stub.xpu = types.SimpleNamespace(is_available=lambda: xpu)
    monkeypatch.setitem(sys.modules, "torch", stub)


def test_auto_prefers_cuda(monkeypatch) -> None:
    _stub_torch(monkeypatch, cuda=True, xpu=True)
    assert resolve_device("auto") == "cuda"


def test_auto_falls_to_xpu_without_cuda(monkeypatch) -> None:
    _stub_torch(monkeypatch, cuda=False, xpu=True)
    assert resolve_device("auto") == "xpu"


def test_auto_falls_to_cpu_without_a_gpu(monkeypatch) -> None:
    _stub_torch(monkeypatch, cuda=False, xpu=False)
    assert resolve_device("auto") == "cpu"


def test_explicit_devices_pass_through_when_available(monkeypatch) -> None:
    _stub_torch(monkeypatch, cuda=True, xpu=True)
    assert resolve_device("cuda") == "cuda"
    assert resolve_device("xpu") == "xpu"
    assert resolve_device("cpu") == "cpu"


def test_explicit_cuda_raises_when_unavailable(monkeypatch) -> None:
    _stub_torch(monkeypatch, cuda=False, xpu=True)
    with pytest.raises(ValueError, match="cuda"):
        resolve_device("cuda")


def test_explicit_xpu_raises_when_unavailable(monkeypatch) -> None:
    _stub_torch(monkeypatch, cuda=True, xpu=False)
    with pytest.raises(ValueError, match="xpu"):
        resolve_device("xpu")


def test_unknown_device_raises(monkeypatch) -> None:
    _stub_torch(monkeypatch, cuda=True, xpu=True)
    with pytest.raises(ValueError, match="unknown runtime.device"):
        resolve_device("tpu")
