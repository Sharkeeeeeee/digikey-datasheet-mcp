import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fixtures import FakeBackend, settings  # noqa: E402

from digikey_datasheet_mcp.datasheet import DatasheetStore  # noqa: E402
from digikey_datasheet_mcp.digikey import DigiKeyClient  # noqa: E402
from digikey_datasheet_mcp.lcsc import LcscClient  # noqa: E402


@pytest.fixture
def backend():
    return FakeBackend()


@pytest.fixture
def cfg(tmp_path):
    return settings(tmp_path)


def http_for(backend):
    return httpx.AsyncClient(transport=backend.transport(), follow_redirects=True)


@pytest.fixture
def digikey(backend, cfg):
    return DigiKeyClient(cfg, http=http_for(backend))


@pytest.fixture
def lcsc(backend, cfg):
    return LcscClient(cfg, http=http_for(backend))


@pytest.fixture
def store(backend, cfg):
    return DatasheetStore(cfg, http=http_for(backend))
