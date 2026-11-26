"""End to end: start the real CLI over stdio, like an MCP client would."""

import os
import sys

from mcp import Client, StdioServerParameters


async def test_cli_serves_tools_over_stdio(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("DIGIKEY_")}
    env["DIGIKEY_MCP_CACHE_DIR"] = str(tmp_path)
    params = StdioServerParameters(command=sys.executable, args=["-m", "digikey_datasheet_mcp"], env=env)
    async with Client(params) as client:
        tools = (await client.list_tools()).tools
        assert len(tools) == 11
        result = await client.call_tool("get_part", {"part_number": "NE555"})
    assert result.is_error
    assert "DIGIKEY_CLIENT_ID" in result.content[0].text


def test_version_flag(capsys):
    import pytest

    from digikey_datasheet_mcp.__main__ import main

    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "digikey-datasheet-mcp" in capsys.readouterr().out


def test_check_without_credentials(monkeypatch, capsys):
    from digikey_datasheet_mcp.__main__ import main

    for key in ("DIGIKEY_CLIENT_ID", "DIGIKEY_CLIENT_SECRET"):
        monkeypatch.delenv(key, raising=False)
    assert main(["--check"]) == 1
    assert "not set" in capsys.readouterr().err
