from pathlib import Path
import sys
import types

from fan_sim.ml.dataset import PICKLE_PROTOCOL_FOR_LARGE_GRAPHS, save_graph_sample


def test_save_graph_sample_uses_pickle_protocol_that_supports_large_graphs(monkeypatch, tmp_path: Path):
    calls = {}
    fake_torch = types.ModuleType("torch")

    def fake_save(sample, path, *, pickle_protocol):
        calls["sample"] = sample
        calls["path"] = Path(path)
        calls["pickle_protocol"] = pickle_protocol
        Path(path).write_bytes(b"graph")

    fake_torch.save = fake_save
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    output = tmp_path / "sample.graph.pt"
    save_graph_sample({"x": 1}, output)

    assert output.read_bytes() == b"graph"
    assert calls["path"].name == "sample.graph.pt.tmp"
    assert calls["pickle_protocol"] >= PICKLE_PROTOCOL_FOR_LARGE_GRAPHS
    assert calls["pickle_protocol"] >= 4
    assert not calls["path"].exists()


def test_save_graph_sample_removes_partial_temp_file_on_failure(monkeypatch, tmp_path: Path):
    fake_torch = types.ModuleType("torch")

    def fake_save(sample, path, *, pickle_protocol):
        Path(path).write_bytes(b"partial")
        raise RuntimeError("disk write failed")

    fake_torch.save = fake_save
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    output = tmp_path / "sample.graph.pt"
    try:
        save_graph_sample({"x": 1}, output)
    except RuntimeError:
        pass

    assert not output.exists()
    assert not (tmp_path / "sample.graph.pt.tmp").exists()
