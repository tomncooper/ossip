"""Tests for the cache adapters."""

import pytest

from ipper.social.adapters import LOADERS
from ipper.social.adapters.flink import load_snapshots as load_flink
from ipper.social.adapters.github import reference_for
from ipper.social.adapters.kafka import load_snapshots as load_kafka


def test_kafka_adapter_maps_fields(sample_kip_cache, write_cache, monkeypatch) -> None:
    """KIP snapshots get stable keys, stripped titles and detail URLs."""
    monkeypatch.setenv("OSSIP_BASE_URL", "https://test.example")
    cache = write_cache("kip_wiki_cache.json", sample_kip_cache)
    snaps = load_kafka(cache)
    by_key = {s.key: s for s in snaps}
    assert "kafka:kip-1" in by_key
    snap = by_key["kafka:kip-1"]
    assert snap.reference == "KIP-1"
    assert snap.title == "Remove support of request.required.acks"
    assert snap.state == "accepted"
    assert snap.detail_url == "https://test.example/kips/KIP-1.html"


def test_flink_adapter_preserves_completed_state(
    sample_flip_cache, write_cache, monkeypatch
) -> None:
    """FLIP 'completed' state stays 'completed' in the snapshot."""
    monkeypatch.setenv("OSSIP_BASE_URL", "https://test.example")
    cache = write_cache("flip_wiki_cache.json", sample_flip_cache)
    snaps = load_flink(cache)
    by_key = {s.key: s for s in snaps}
    assert by_key["flink:flip-1"].state == "completed"
    assert by_key["flink:flip-1"].title == "Fine Grained Recovery"
    assert by_key["flink:flip-1"].detail_url == "https://test.example/flips/FLIP-1.html"


def test_github_adapter_numbered_and_unnumbered(
    sample_sip_cache, write_cache, monkeypatch, tmp_path
) -> None:
    """SIP snapshots use pr-number keys and detail_page_filename URLs."""
    monkeypatch.setenv("OSSIP_BASE_URL", "https://test.example")
    (tmp_path / "cache").mkdir()
    write_cache("cache/sip_proposals_cache.json", sample_sip_cache)
    monkeypatch.chdir(tmp_path)
    snaps = LOADERS["strimzi"]()
    by_key = {s.key: s for s in snaps}
    numbered = by_key["strimzi:pr-3"]
    assert numbered.reference == "SIP-5"
    assert numbered.detail_url.endswith("/sips/SIP-5.html")
    unnumbered = by_key["strimzi:pr-245"]
    assert unnumbered.reference == "SIP-PR-245"
    assert unnumbered.detail_url.endswith("/sips/SIP-PR-245.html")


def test_reference_for_numbered_and_unnumbered() -> None:
    """reference_for mirrors detail_page_filename logic."""
    from ipper.common.github_config import GITHUB_PROJECT_CONFIGS

    config = GITHUB_PROJECT_CONFIGS["strimzi"]
    assert reference_for(config, {"id": 46, "pr_number": 245}) == "SIP-46"
    assert reference_for(config, {"id": None, "pr_number": 245}) == "SIP-PR-245"


def test_missing_cache_raises_file_not_found_error(tmp_path) -> None:
    """A missing cache file raises FileNotFoundError (not an empty list)."""
    with pytest.raises(FileNotFoundError):
        load_kafka(tmp_path / "nope.json")
