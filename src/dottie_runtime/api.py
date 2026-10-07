"""The connection from the agent in the sandbox back to the app (`/internal` of the app, with this run's token)."""

from dataclasses import dataclass

import httpx


@dataclass
class Api:
    """Two clients on the same address: sync for the filesystem tools (Deep Agents calls those from threads), async for
    everything else. Tests pass clients that talk to the app in-process."""

    sync: httpx.Client
    asy: httpx.AsyncClient
    base_url: str  # what a model client is pointed at: the app proxies `<base_url>/llm/...` to the real model
    token: str

    @classmethod
    def connect(cls, base_url: str, token: str) -> Api:
        headers = {"Authorization": f"Bearer {token}"}
        return cls(
            sync=httpx.Client(base_url=base_url, headers=headers, timeout=60),
            asy=httpx.AsyncClient(base_url=base_url, headers=headers, timeout=60),
            base_url=base_url,
            token=token,
        )

    async def close(self) -> None:
        await self.asy.aclose()
        self.sync.close()
