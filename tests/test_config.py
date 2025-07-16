from src.config import parse_arguments, load_config


def test_parse_arguments_defaults(monkeypatch):
    monkeypatch.setattr("sys.argv", ["prog"])
    args = parse_arguments()
    assert hasattr(args, "conf")
    assert hasattr(args, "folder")


def test_load_config_defaults():
    config = load_config()
    assert isinstance(config, dict)
    assert "DISCORD_TOKEN" in config
    assert "API_KEY" in config
    assert "LOG_FILE" in config
    assert isinstance(config["RATE_LIMIT"], int)
    assert isinstance(config["RATE_LIMIT_PER"], int)


def test_env_override(monkeypatch):
    monkeypatch.setenv("API_KEY", "env_api_key")
    config = load_config()
    assert config["API_KEY"] == "env_api_key"
