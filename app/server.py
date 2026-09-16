"""
Production entry point — `python -m app.server`. Reads host and port from config.yaml
at process start, so the systemd unit never hard-codes them.
"""
from __future__ import annotations

import logging

import uvicorn

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        # One worker: login throttling and future job state are kept in process.
        workers=1,
        log_level=settings.log_level,
        access_log=False,
        # Behind the local reverse proxy, take the client address from it — and only
        # from it, so a direct caller cannot forge X-Forwarded-For.
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
    )


if __name__ == "__main__":
    main()
