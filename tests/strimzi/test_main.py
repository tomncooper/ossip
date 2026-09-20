"""Tests for the strimzi CLI wiring."""

import pytest

from ipper.main import setup_top_level_parser


def parse(argv):
    parser = setup_top_level_parser()
    return parser.parse_args(argv)


class TestStrimziCli:
    def test_init_dispatch(self, mocker, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "t")
        init_mock = mocker.patch("ipper.common.github_cli.init_cache")
        save_mock = mocker.patch("ipper.common.github_cli.save_cache")
        mocker.patch("ipper.common.github_cli.GithubClient")

        args = parse(["strimzi", "init"])
        args.func(args)

        assert init_mock.call_count == 1
        assert save_mock.call_count == 1
        # cache path derived from the Strimzi config
        assert save_mock.call_args.args[1].name == "sip_proposals_cache.json"

    def test_update_dispatch(self, mocker, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        cache_file = tmp_path / "sip_proposals_cache.json"
        cache_file.write_text('{"proposals": {}, "pr_index": {}}')
        mocker.patch(
            "ipper.common.github_cli.load_cache",
            return_value={"proposals": {}, "pr_index": {}},
        )
        mocker.patch("ipper.common.github_cli.cache_path_for", return_value=cache_file)
        update_mock = mocker.patch("ipper.common.github_cli.update_cache")
        mocker.patch("ipper.common.github_cli.save_cache")
        mocker.patch("ipper.common.github_cli.GithubClient")

        args = parse(["strimzi", "update"])
        args.func(args)

        assert update_mock.call_count == 1

    def test_refresh_dispatch(self, mocker, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "t")
        mocker.patch("ipper.common.github_cli.init_cache")
        mocker.patch("ipper.common.github_cli.save_cache")
        mocker.patch("ipper.common.github_cli.GithubClient")

        args = parse(["strimzi", "refresh"])
        args.func(args)
        # refresh does a full reprocess like init

    def test_output_dispatch(self, mocker, tmp_path):
        cache_file = tmp_path / "cache.json"
        cache_file.write_text('{"proposals": {}, "pr_index": {}}')

        render_index = mocker.patch("ipper.common.github_cli.render_index_page")
        render_detail = mocker.patch("ipper.common.github_cli.render_detail_pages")
        api_mock = mocker.patch("ipper.common.github_cli.generate_github_json_api")

        args = parse(
            [
                "strimzi",
                "output",
                str(cache_file),
                str(tmp_path / "strimzi.html"),
                str(tmp_path / "sips"),
                "--api-dir",
                str(tmp_path / "api"),
            ]
        )
        args.func(args)

        assert render_index.call_count == 1
        assert render_detail.call_count == 1
        assert api_mock.call_count == 1

    def test_output_without_api_dir(self, mocker, tmp_path):
        cache_file = tmp_path / "cache.json"
        cache_file.write_text('{"proposals": {}, "pr_index": {}}')

        mocker.patch("ipper.common.github_cli.render_index_page")
        mocker.patch("ipper.common.github_cli.render_detail_pages")
        api_mock = mocker.patch("ipper.common.github_cli.generate_github_json_api")

        args = parse(["strimzi", "output", str(cache_file), "out.html", "sips"])
        args.func(args)

        assert api_mock.call_count == 0

    def test_init_requires_token(self, mocker, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        mocker.patch("ipper.common.github_cli.GithubClient", side_effect=ImportError)
        # GithubTokenRequiredError -> SystemExit via cli error handling
        from ipper.common.github import GithubTokenRequiredError

        mocker.patch(
            "ipper.common.github_cli.GithubClient",
            side_effect=GithubTokenRequiredError("no token"),
        )
        args = parse(["strimzi", "init"])
        with pytest.raises(SystemExit):
            args.func(args)

    def test_update_missing_cache_exits(self, mocker, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        args = parse(["strimzi", "update"])
        with pytest.raises(SystemExit):
            args.func(args)

    def test_top_level_help_lists_projects(self, capsys):
        parse(["strimzi"])
        # strimzi with no subcommand prints its help
