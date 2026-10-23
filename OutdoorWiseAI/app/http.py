import httpx
from .config import USER_AGENT

_client = None


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=httpx.Timeout(40.0, connect=10.0),
            follow_redirects=True,
        )
    return _client
