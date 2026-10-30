"""CAP-051 AC9: known node sizes come from config/compute.yaml."""
from __future__ import annotations

import pytest

from capellactl.config import presets


@pytest.mark.story("CAP-051", "AC9")
def test_compute_sizes_ac9_loaded_from_file(monkeypatch):
    sizes = presets.load_compute_sizes()
    assert set(sizes) == {"aws", "gcp", "azure"}
    assert (8, 32) in sizes["aws"]["sizes"] and (2, 8) in sizes["aws"]["singleNode"]
    assert presets.known_size("aws", 8, 32, single=False)
    assert not presets.known_size("aws", 8, 30, single=False)
    assert not presets.known_size("aws", 2, 8, single=False) and presets.known_size("aws", 2, 8, single=True)
    assert presets.known_size("azure", 20, 160, single=False) and not presets.known_size("aws", 20, 160, single=False)

    class Text:
        def joinpath(self, _name):
            return self

        def read_text(self, encoding):
            return "aws:\n  sizes: [8/30]\n"

    presets.load_compute_sizes.cache_clear()
    monkeypatch.setattr(presets.resources, "files", lambda _pkg: Text())
    try:
        assert presets.known_size("aws", 8, 30, single=False)  # changing the file changes the sizes
    finally:
        presets.load_compute_sizes.cache_clear()
