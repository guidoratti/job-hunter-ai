"""Windows-safe Uvicorn launcher ensuring ProactorEventLoop for Playwright subprocesses."""

from __future__ import annotations

import asyncio
import sys

import uvicorn

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        loop="asyncio",
    )


if __name__ == "__main__":
    main()
