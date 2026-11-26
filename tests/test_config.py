from pathlib import Path

from digikey_datasheet_mcp.config import Settings


def test_defaults_without_env():
    s = Settings.from_env({})
    assert not s.has_digikey
    assert (s.site, s.language, s.currency) == ("US", "en", "USD")
    assert s.sandbox is False
    assert s.cache_dir.name == "digikey-datasheet-mcp"


def test_reads_env():
    s = Settings.from_env(
        {
            "DIGIKEY_CLIENT_ID": " abc ",
            "DIGIKEY_CLIENT_SECRET": "xyz",
            "DIGIKEY_SANDBOX": "true",
            "DIGIKEY_LOCALE_SITE": "TW",
            "DIGIKEY_LOCALE_LANGUAGE": "zht",
            "DIGIKEY_LOCALE_CURRENCY": "TWD",
            "DIGIKEY_MCP_CACHE_DIR": "/tmp/dk-cache",
            "LCSC_SEARCH_URL": "http://localhost:3000/",
        }
    )
    assert s.has_digikey and s.client_id == "abc"
    assert s.sandbox
    assert (s.site, s.language, s.currency) == ("TW", "zht", "TWD")
    assert s.cache_dir == Path("/tmp/dk-cache")
    assert s.lcsc_url == "http://localhost:3000"


def test_blank_secret_means_not_configured():
    assert not Settings.from_env({"DIGIKEY_CLIENT_ID": "a", "DIGIKEY_CLIENT_SECRET": "  "}).has_digikey


def test_bad_numbers_are_reported():
    import pytest

    from digikey_datasheet_mcp.config import ConfigError

    with pytest.raises(ConfigError, match="DIGIKEY_MCP_TIMEOUT"):
        Settings.from_env({"DIGIKEY_MCP_TIMEOUT": "fast"})
    with pytest.raises(ConfigError, match="greater than 0"):
        Settings.from_env({"DATASHEET_MAX_MB": "0"})


def test_allow_private():
    assert Settings.from_env({"DATASHEET_ALLOW_PRIVATE": "1"}).allow_private_urls
