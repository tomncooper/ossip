"""Tests for the social announce CLI command."""

import json
from pathlib import Path

import pytest

from ipper.social import cli
from ipper.social.cli import run_announce_cmd, setup_social_parser
from ipper.social.detector import save_state, seed_state
from ipper.social.models import ProposalSnapshot, SocialState


def make_args(**kwargs):
    """Namespace of announce arguments with test-friendly defaults."""
    from argparse import Namespace

    defaults = {
        "post_to": "console",
        "projects": "kafka",
        "dry_run": False,
        "demo": False,
        "max_posts": 5,
        "max_attempts": 5,
        "state_file": str(Path("state.json")),
        "reseed": False,
    }
    defaults.update(kwargs)
    return Namespace(**defaults)


@pytest.fixture
def kip_cache(tmp_path: Path, monkeypatch):
    """A tiny KIP cache in tmp_path; monkeypatches the kafka loader."""
    data = {
        "123": {
            "kip_id": 123,
            "title": "KIP-123 - Exactly-once semantics",
            "web_url": "https://example.com/kip-123",
            "state": "under discussion",
        }
    }
    cache_file = tmp_path / "kip_wiki_cache.json"
    cache_file.write_text(json.dumps(data), encoding="utf-8")

    from ipper.social.adapters import kafka as kafka_adapter

    monkeypatch.setitem(
        cli.LOADERS, "kafka", lambda: kafka_adapter.load_snapshots(cache_file)
    )
    return cache_file


def test_announce_dry_run_first_run_never_writes_state(
    kip_cache, tmp_path, capsys
) -> None:
    """--dry-run prints the seed summary but never creates the state file."""
    state_file = tmp_path / "social" / "state.json"
    args = make_args(dry_run=True, state_file=str(state_file))
    run_announce_cmd(args)
    assert "Would seed baseline" in capsys.readouterr().out
    assert not state_file.exists()


def test_announce_live_first_run_seeds_only(kip_cache, tmp_path, capsys) -> None:
    """The first live run seeds the baseline and posts nothing."""
    state_file = tmp_path / "social" / "state.json"
    args = make_args(state_file=str(state_file))
    run_announce_cmd(args)
    assert "Seeded baseline with 1 proposals" in capsys.readouterr().out
    state = SocialState.model_validate_json(state_file.read_text(encoding="utf-8"))
    assert len(state.baselines) == 1
    assert state.pending == []


def test_announce_end_to_end_new_event(kip_cache, tmp_path, capsys) -> None:
    """A state transition prints one message and empties the queue."""
    state_file = tmp_path / "social" / "state.json"
    state = seed_state(
        [
            ProposalSnapshot(
                key="kafka:kip-123",
                project="kafka",
                reference="KIP-123",
                title="Exactly-once semantics",
                state="under discussion",
                detail_url="https://ossip.dev/kips/KIP-123.html",
            )
        ],
        "2026-10-04T09:30:00+00:00",
    )
    save_state(state, state_file)

    # The cache now says the KIP was accepted.
    data = json.loads(kip_cache.read_text(encoding="utf-8"))
    data["123"]["state"] = "accepted"
    kip_cache.write_text(json.dumps(data), encoding="utf-8")

    args = make_args(state_file=str(state_file))
    run_announce_cmd(args)
    out = capsys.readouterr().out
    assert out.count("[console]") == 1
    assert "KIP-123 ✅ accepted" in out
    final = SocialState.model_validate_json(state_file.read_text(encoding="utf-8"))
    assert final.baselines["kafka:kip-123"].state == "accepted"
    assert final.pending == []


def test_announce_retry_logic(kip_cache, tmp_path, capsys, monkeypatch) -> None:
    """A failed destination is retried alone on the next run."""
    from ipper.social.posters import base as poster_base
    from ipper.social.posters.base import PostResult

    state_file = tmp_path / "social" / "state.json"
    cache = tmp_path / "kip_wiki_cache.json"

    class FlakyPoster:
        name = "flaky"
        fail = False

        def __init__(self) -> None:
            self.calls = 0

        @classmethod
        def from_env(cls):
            """No credentials required."""
            return cls()

        def post(self, event):
            self.calls += 1
            if self.fail:
                return PostResult(ok=False, error="down")
            return PostResult(ok=True, post_id=str(self.calls))

    instance = FlakyPoster()
    monkeypatch.setitem(poster_base.POSTER_REGISTRY, "flaky", FlakyPoster)
    monkeypatch.setattr(
        "ipper.social.cli.get_poster", lambda name: instance, raising=False
    )

    def write_cache(state: str) -> None:
        data = {"123": {"kip_id": 123, "title": "KIP-123 - E", "state": state}}
        cache.write_text(json.dumps(data), encoding="utf-8")

    def load_state_file() -> SocialState:
        return SocialState.model_validate_json(state_file.read_text(encoding="utf-8"))

    # Pre-seed so run 1 is not the seeding run.
    save_state(
        seed_state(
            [
                ProposalSnapshot(
                    key="kafka:kip-123",
                    project="kafka",
                    reference="KIP-123",
                    title="E",
                    state="under discussion",
                    detail_url="https://ossip.dev/kips/KIP-123.html",
                )
            ],
            "2026-10-04T09:30:00+00:00",
        ),
        state_file,
    )

    # Run 1: cache says accepted; event fires and posts successfully.
    write_cache("accepted")
    run_announce_cmd(make_args(post_to="flaky", state_file=str(state_file)))
    assert load_state_file().pending == []
    assert instance.calls == 1

    # Run 2: new change, destination fails; event stays pending.
    instance.fail = True
    write_cache("not accepted")
    run_announce_cmd(make_args(post_to="flaky", state_file=str(state_file)))
    final = load_state_file()
    assert len(final.pending) == 1
    assert final.pending[0].destinations["flaky"].attempts == 1
    assert instance.calls == 2

    # Run 3: destination recovers; only the failed destination is retried.
    instance.fail = False
    run_announce_cmd(make_args(post_to="flaky", state_file=str(state_file)))
    final = load_state_file()
    assert final.pending == []
    assert instance.calls == 3


def test_demo_prints_sample_messages_without_state(kip_cache, tmp_path, capsys) -> None:
    """--demo prints rendered messages and never touches the state file."""
    state_file = tmp_path / "state.json"
    run_announce_cmd(make_args(demo=True, state_file=str(state_file)))
    out = capsys.readouterr().out
    assert "KIP-123" in out
    assert not state_file.exists()


def test_reseed_rebuilds_baseline(kip_cache, tmp_path, capsys) -> None:
    """--reseed clears pending and rebuilds baselines from current snapshots."""
    state_file = tmp_path / "social" / "state.json"
    state = SocialState(
        version=1,
        baselines={"kafka:kip-999": {"state": "under discussion"}},
        pending=[
            {
                "event": {
                    "event_type": "new",
                    "observed_at": "2026-10-01T00:00:00+00:00",
                    "snapshot": {
                        "key": "kafka:kip-999",
                        "project": "kafka",
                        "reference": "KIP-999",
                        "title": "Gone",
                        "state": "under discussion",
                        "detail_url": "https://ossip.dev/kips/KIP-999.html",
                    },
                },
                "destinations": {},
            }
        ],
    )
    save_state(state, state_file)
    run_announce_cmd(make_args(reseed=True, state_file=str(state_file)))
    assert "Re-seeded baseline with 1 proposals" in capsys.readouterr().out
    final = SocialState.model_validate_json(state_file.read_text(encoding="utf-8"))
    assert set(final.baselines) == {"kafka:kip-123"}
    assert final.pending == []


def test_reseed_dry_run_never_writes(kip_cache, tmp_path, capsys) -> None:
    """--reseed --dry-run only prints."""
    state_file = tmp_path / "social" / "state.json"
    run_announce_cmd(make_args(reseed=True, dry_run=True, state_file=str(state_file)))
    assert "Would re-seed" in capsys.readouterr().out
    assert not state_file.exists()


def test_unknown_project_exits(kip_cache) -> None:
    """An unknown --projects key fails loudly."""
    with pytest.raises(SystemExit, match="Unknown projects"):
        run_announce_cmd(make_args(projects="kafka,nowhere"))


def test_parser_registered() -> None:
    """setup_social_parser wires the announce subcommand."""

    from argparse import ArgumentParser

    parser = ArgumentParser()
    sub = parser.add_subparsers()
    setup_social_parser(sub)
    args = parser.parse_args(["social", "announce", "--dry-run"])
    assert args.dry_run is True
    assert args.func is run_announce_cmd
