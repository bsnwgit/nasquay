"""
The worker: `python -m app.worker`, one systemd service beside the web one.

It runs what should not share a lifetime with a web server — today the monitoring
schedule, the routines, and later the jobs. A collection walking a 28 TB share must not be
interrupted because the interface was restarted to pick up a new page, and a web service
must be free to restart for exactly that reason.

It runs no migrations. The web service owns the schema, and two processes applying the
same migration at the same moment is a race with a real loser: `CREATE TABLE IF NOT
EXISTS` survives it, `ALTER TABLE ADD COLUMN` does not. So the worker waits for the schema
to be there and then uses it.
"""
from __future__ import annotations

import asyncio
import logging
import signal

from app.config import get_settings
from app.database import connect
from app.monitoring import scheduler
from app.routines import scheduler as routine_scheduler
from app.version import get_version

log = logging.getLogger("nasquay.worker")

# How long to wait for the web service to create or migrate the database before giving up
# and letting systemd restart us. Generous: a migration on a large audit table takes time,
# and a worker that exits impatiently just restarts into the same wait.
SCHEMA_TIMEOUT = 120
SCHEMA_POLL = 2


async def _wait_for_schema() -> None:
    waited = 0
    while True:
        try:
            conn = await connect()
            try:
                async with conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'nas'"
                ) as cur:
                    if await cur.fetchone():
                        return
            finally:
                await conn.close()
        except Exception as exc:  # the file may not exist yet at all
            log.debug("database not ready: %s", exc)

        if waited >= SCHEMA_TIMEOUT:
            raise RuntimeError(
                "The database has no schema after "
                f"{SCHEMA_TIMEOUT}s — is the web service running?"
            )
        await asyncio.sleep(SCHEMA_POLL)
        waited += SCHEMA_POLL


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    await _wait_for_schema()
    scheduler.start()
    routine_scheduler.start()
    log.info("NASQuay worker %s started", get_version())

    # Wait for systemd to say stop, rather than spinning.
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopping.set)
    await stopping.wait()

    log.info("NASQuay worker stopping")
    await scheduler.stop()
    await routine_scheduler.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
