"""Command-line entry point: `digikey-datasheet-mcp` (stdio MCP server)."""

from __future__ import annotations

import argparse
import asyncio
import sys

from . import __version__
from .config import ConfigError, Settings


async def _check(settings: Settings) -> int:
    from .digikey import DigiKeyClient, DigiKeyError

    if not settings.has_digikey:
        print("DIGIKEY_CLIENT_ID / DIGIKEY_CLIENT_SECRET are not set.", file=sys.stderr)
        return 1
    client = DigiKeyClient(settings)
    try:
        body = await client.keyword_search("NE555", limit=1)
    except DigiKeyError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        await client.aclose()
    env = "sandbox" if settings.sandbox else "production"
    print(
        f"OK: DigiKey {env} API reachable, {body.get('ProductsCount', '?')} results for NE555 "
        f"(site {settings.site}, {settings.currency})."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="digikey-datasheet-mcp",
        description="MCP server for DigiKey part search, pricing, BOM costing and datasheet reading (stdio).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--check", action="store_true", help="verify DigiKey credentials and exit")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio", help="default: stdio")
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"digikey-datasheet-mcp: configuration error: {exc}", file=sys.stderr)
        return 2
    if args.check:
        return asyncio.run(_check(settings))

    from .server import build_server

    build_server(settings).run(args.transport)
    return 0


if __name__ == "__main__":
    sys.exit(main())
