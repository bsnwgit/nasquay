"""
Importing a NAS's own usage history, so there is a baseline before NASQuay was installed.

QNAP keeps several windows of history at different resolutions. Taken together they cover
about a year, and the point of importing them is that a question like "when did this volume
start losing space" should be answerable on the first day rather than after weeks of
collecting.

Two things make this history worth less than a live reading, and both are recorded against
every row it produces:

  Its numbers are rounded. QNAP returns three or four significant digits.

  Its numbers are mislabelled. A field called `used_bytes` holding 923,080,000,000 means
  923.08 GiB, not 923.08 GB — the figure is binary but scaled by decimal powers. The NAS
  proves this against itself: it reports `total_size_bytes` 30,750,000,000,000 for a volume
  that `list_storages` gives as 33,805,257,478,144 bytes, and 33,805,257,478,144 / 1024^4 is
  30.75. Every value here is converted back the same way and marked `rounded`.

The windows overlap, so each is cut where the next finer one begins. That leaves one
timeline, coarse in the distant past and fine in the last day, with no point counted twice.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from app.connectors import qnap_mcp
from app.monitoring.collector import Outcome, Reading, Watched

# QNAP's record types, coarsest first, each with the age beyond which it is the best
# source available. A window only contributes points older than the next finer window.
WINDOWS: tuple[tuple[int, str, timedelta], ...] = (
    (10, "year, weekly", timedelta(days=30)),
    (8, "30 days, daily", timedelta(days=7)),
    (15, "week, 4-hourly", timedelta(days=1)),
    (5, "day, hourly", timedelta(0)),
)


def real_bytes(reported: Optional[int]) -> Optional[int]:
    """Undo QNAP's scaling: x × 10^(3k) in the output means x × 1024^k in reality."""
    if reported is None:
        return None
    if reported <= 0:
        return 0
    power = 0
    while power < 5 and reported >= 1000 ** (power + 1):
        power += 1
    magnitude = 1000**power
    return int(round((reported / magnitude) * (1024**power)))


def _moment(stamp: str) -> Optional[str]:
    """QNAP writes times in C's asctime form: "Sun Sep 21 00:00:00 2025"."""
    try:
        return datetime.strptime(stamp.strip(), "%a %b %d %H:%M:%S %Y").strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except (ValueError, AttributeError):
        return None


@dataclass
class Imported:
    readings: list[Reading]
    problems: list[str]
    windows: dict[str, int]


def _series(connection: qnap_mcp.Connection, tool: str, arguments: dict[str, Any]) -> list[dict]:
    answer = json.loads(connection.call_tool(tool, arguments))
    return list(answer.get("used_series") or [])


def history(mcp: qnap_mcp.Target, watched: list[Watched]) -> Imported:
    """Every watched volume's and pool's usage history, as readings."""
    outcome = Outcome()
    windows: dict[str, int] = {}
    now = datetime.now()

    connection = qnap_mcp.Connection(mcp)
    try:
        connection.open()

        for target in watched:
            if target.kind == "volume":
                tool, key, metric = "get_qts_volume_usage_history", "volume_id", "volume_used_bytes"
            elif target.kind == "pool":
                tool, key, metric = "get_pool_usage_history", "pool_id", "pool_used_bytes"
            else:
                continue

            try:
                identifier = int(target.ref)
            except ValueError:
                outcome.problems.append(f"{target.kind} {target.ref} has no numeric id")
                continue

            newest_taken: Optional[datetime] = None
            for record_type, label, older_than in WINDOWS:
                try:
                    points = _series(connection, tool, {key: identifier, "record_type": record_type})
                except (qnap_mcp.McpError, ValueError) as exc:
                    outcome.problems.append(f"{target.kind} {target.ref} ({label}): {exc}")
                    continue

                cutoff = now - older_than
                kept = 0
                for point in points:
                    moment = _moment(str(point.get("time") or ""))
                    if moment is None:
                        continue
                    taken = datetime.strptime(moment, "%Y-%m-%d %H:%M:%S")
                    # Each window only supplies what the next finer one will not cover,
                    # and nothing dated in the future.
                    if taken > cutoff or taken > now:
                        continue
                    value = real_bytes(point.get("used_bytes"))
                    if value is None:
                        continue
                    outcome.readings.append(
                        Reading(
                            target.id, metric, value, "mcp",
                            rounded=True,
                            raw=json.dumps({"reported": point.get("used_bytes"), "window": label}),
                            taken_at=moment,
                        )
                    )
                    kept += 1
                    newest_taken = max(newest_taken or taken, taken)
                windows[label] = windows.get(label, 0) + kept

            if newest_taken is None:
                outcome.problems.append(f"{target.kind} {target.ref}: no usable history")
    except qnap_mcp.McpError as exc:
        outcome.problems.append(str(exc))
    finally:
        connection.close()

    return Imported(readings=outcome.readings, problems=outcome.problems, windows=windows)
