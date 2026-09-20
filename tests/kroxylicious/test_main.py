"""Tests for the kroxylicious CLI wiring."""

from ipper.main import setup_top_level_parser


def parse(argv):
    parser = setup_top_level_parser()
    return parser.parse_args(argv)


class TestKroxyliciousCli:
    def test_commands_registered(self):
        args = parse(["kroxylicious", "update"])
        assert args.func is not None

    def test_uses_kdp_config(self, mocker, monkeypatch, tmp_path):
        monkeypatch.setenv("GITHUB_TOKEN", "t")
        save_mock = mocker.patch("ipper.common.github_cli.save_cache")
        mocker.patch("ipper.common.github_cli.init_cache")
        mocker.patch("ipper.common.github_cli.GithubClient")

        args = parse(["kroxylicious", "init"])
        args.func(args)
        assert save_mock.call_args.args[1].name == "kdp_proposals_cache.json"
