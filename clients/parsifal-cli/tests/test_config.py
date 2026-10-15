import json

from parsifal_cli import cli, config
from tests.conftest import invoke


def test_resolve_precedence(monkeypatch, tmp_path):
    path = tmp_path / "config.toml"
    monkeypatch.setenv("PARSIFAL_CONFIG", str(path))
    monkeypatch.delenv("PARSIFAL_URL", raising=False)
    monkeypatch.delenv("PARSIFAL_TOKEN", raising=False)
    monkeypatch.delenv("PARSIFAL_PROFILE", raising=False)

    assert config.resolve().url == config.DEFAULT_URL
    config.save_profiles({"default": {"url": "http://file", "token": "pfl_file"}, "lab": {"url": "http://lab"}})
    assert (config.resolve().url, config.resolve().token) == ("http://file", "pfl_file")
    assert config.resolve(profile="lab").url == "http://lab"
    monkeypatch.setenv("PARSIFAL_URL", "http://env")
    assert config.resolve().url == "http://env"
    assert config.resolve(url="http://flag").url == "http://flag"
    assert oct(path.stat().st_mode)[-3:] == "600"


def test_config_set_and_show(runner, monkeypatch, tmp_path):
    path = tmp_path / "config.toml"
    monkeypatch.setenv("PARSIFAL_CONFIG", str(path))
    monkeypatch.delenv("PARSIFAL_URL", raising=False)
    monkeypatch.delenv("PARSIFAL_TOKEN", raising=False)
    result = runner.invoke(cli.app, ["config", "set", "--url", "http://srv", "--token", "pfl_abcdefghijklmnop"])
    assert result.exit_code == 0, result.output
    shown = json.loads(invoke(runner, ["config", "show"]).output)
    assert shown["url"] == "http://srv"
    assert shown["token"] == "pfl_abcdefgh…"
    assert "pfl_abcdefghijklmnop" not in json.dumps(shown)
    assert runner.invoke(cli.app, ["config", "set"]).exit_code != 0
