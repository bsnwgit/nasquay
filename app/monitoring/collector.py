"""
Taking readings from a NAS.

Two halves, deliberately separate:

  discover() asks a NAS what there is to watch and writes `targets`. It never removes a
  target — a share that vanishes is the kind of thing this app exists to notice, so its
  target stays and stops receiving readings.

  collect() takes one tier's readings for a NAS's enabled targets and writes `readings`.

Everything is read twice by different means wherever possible, because the whole point is
to catch a NAS reporting one thing while another says otherwise: MCP's idea of a volume's
free space against `df`, MCP's cached per-share file count against a live `find`. Nothing
here decides what a divergence means; the rules do that from the rows.

Both are synchronous and run in a worker thread — the connectors are blocking.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from app.connectors import qnap_mcp, ssh

# Fast: cheap enough to run every few minutes.
FAST = "fast"
# Slow: `du` and a live `find` walk a whole share, which takes minutes on a large one.
SLOW = "slow"


@dataclass
class Reading:
    target_id: int
    metric: str
    value: Optional[int]
    source: str
    rounded: bool = False
    cached: bool = False
    raw: str = ""
    # Empty means "now"; backfilled readings carry the moment they describe.
    taken_at: str = ""


@dataclass
class Outcome:
    readings: list[Reading] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def note(self, what: str, exc: Exception) -> None:
        self.problems.append(f"{what}: {exc}")


def _int(value: Any) -> Optional[int]:
    """A whole number, or nothing. QNAP returns numbers as strings in places."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


# ── discovery ─────────────────────────────────────────────────────────────────

@dataclass
class Found:
    kind: str
    ref: str
    label: str
    # For a share, the volume it lives on — what gives a volume's `df` a path to measure.
    parent_ref: str = ""


def discover(mcp: qnap_mcp.Target) -> tuple[list[Found], list[str]]:
    """What this NAS has that can be watched: its pools, volumes and shared folders."""
    found: list[Found] = []
    problems: list[str] = []
    connection = qnap_mcp.Connection(mcp)
    try:
        connection.open()

        try:
            storages = json.loads(connection.call_tool("list_storages", {}))
            for pool in storages.get("pools") or []:
                pool_id = str(pool.get("pool_id") or "")
                if pool_id:
                    found.append(Found("pool", pool_id, f"Pool {pool_id}"))
                for volume in pool.get("volumes") or []:
                    vol_no = str(volume.get("vol_no") or "")
                    if vol_no:
                        found.append(Found("volume", vol_no, str(volume.get("vol_label") or "")))
        except (qnap_mcp.McpError, ValueError) as exc:
            problems.append(f"storages: {exc}")

        try:
            shares = json.loads(connection.call_tool("list_shared_folder", {"detailed": True}))
            for share in shares.get("sharedfolders") or []:
                name = str(share.get("name") or "")
                if name:
                    found.append(Found("share", name, str(share.get("comment") or ""),
                                       str(share.get("volumeID") or "")))
        except (qnap_mcp.McpError, ValueError) as exc:
            problems.append(f"shares: {exc}")
    finally:
        connection.close()
    return found, problems


# ── collection ────────────────────────────────────────────────────────────────

@dataclass
class Watched:
    """One row of `targets`, with what the collector needs to reach it."""

    id: int
    kind: str
    ref: str
    label: str = ""
    parent_ref: str = ""
    # For a volume: a share that lives on it, so `df` has a path to resolve.
    via_share: str = ""


def collect(
    mcp: Optional[qnap_mcp.Target],
    sshing: Optional[ssh.Target],
    watched: list[Watched],
    tier: str,
) -> Outcome:
    """One tier's readings for one NAS."""
    outcome = Outcome()
    pools = [w for w in watched if w.kind == "pool"]
    volumes = [w for w in watched if w.kind == "volume"]
    shares = [w for w in watched if w.kind == "share"]

    if tier == FAST and mcp is not None and (pools or volumes):
        _fast_mcp(mcp, pools, volumes, outcome)

    if tier == FAST and sshing is not None:
        for volume in volumes:
            if not volume.via_share:
                continue
            try:
                figures = ssh.df_kib(sshing, f"/share/{volume.via_share}")
            except ssh.SshError as exc:
                outcome.note(f"df for volume {volume.ref}", exc)
                continue
            outcome.readings += [
                Reading(volume.id, "df_total_bytes", figures["total_bytes"], "ssh"),
                Reading(volume.id, "df_used_bytes", figures["used_bytes"], "ssh"),
                Reading(volume.id, "df_available_bytes", figures["available_bytes"], "ssh"),
            ]

    if tier == SLOW and mcp is not None and shares:
        _slow_mcp(mcp, shares, outcome)

    if tier == SLOW and sshing is not None:
        for share in shares:
            path = f"/share/{share.ref}"
            try:
                counts = ssh.file_count(sshing, path)
                outcome.readings += [
                    Reading(share.id, "file_count", counts["files"], "ssh"),
                    Reading(share.id, "file_count_excluding_housekeeping",
                            counts["files_excluding_housekeeping"], "ssh"),
                    Reading(share.id, "dir_count", counts["directories"], "ssh"),
                ]
            except ssh.SshError as exc:
                outcome.note(f"file count for {share.ref}", exc)
            try:
                outcome.readings.append(
                    Reading(share.id, "du_bytes", ssh.du_bytes(sshing, path), "ssh")
                )
            except ssh.SshError as exc:
                outcome.note(f"du for {share.ref}", exc)

    return outcome


def _fast_mcp(
    mcp: qnap_mcp.Target, pools: list[Watched], volumes: list[Watched], outcome: Outcome
) -> None:
    connection = qnap_mcp.Connection(mcp)
    try:
        connection.open()
        storages = json.loads(connection.call_tool("list_storages", {}))
    except (qnap_mcp.McpError, ValueError) as exc:
        outcome.note("list_storages", exc)
        return
    finally:
        connection.close()

    by_pool = {str(p.get("pool_id") or ""): p for p in storages.get("pools") or []}
    volumes_seen: dict[str, dict[str, Any]] = {}
    for pool in storages.get("pools") or []:
        for volume in pool.get("volumes") or []:
            volumes_seen[str(volume.get("vol_no") or "")] = volume

    for target in pools:
        pool = by_pool.get(target.ref)
        if pool is None:
            outcome.problems.append(f"pool {target.ref} was not reported by the NAS")
            continue
        # "0" is healthy and "-1" is degraded on QTS 5.2; the rule watches for the value
        # changing rather than for any particular number.
        outcome.readings.append(
            Reading(target.id, "pool_status", _int(pool.get("pool_status")), "mcp",
                    raw=str(pool.get("pool_status")))
        )
        outcome.readings.append(
            Reading(target.id, "pool_capacity_bytes", _int(pool.get("pool_capacity")), "mcp")
        )
        pool_capacity = _int(pool.get("pool_capacity"))
        pool_free = _int(pool.get("pool_freesize"))
        outcome.readings.append(
            Reading(target.id, "pool_free_bytes", pool_free, "mcp")
        )
        if pool_capacity is not None and pool_free is not None:
            outcome.readings.append(
                Reading(target.id, "pool_used_bytes", pool_capacity - pool_free, "mcp")
            )

    for target in volumes:
        volume = volumes_seen.get(target.ref)
        if volume is None:
            outcome.problems.append(f"volume {target.ref} was not reported by the NAS")
            continue
        capacity = _int(volume.get("capacity_bytes"))
        free = _int(volume.get("freesize_bytes"))
        outcome.readings += [
            Reading(target.id, "volume_capacity_bytes", capacity, "mcp"),
            Reading(target.id, "volume_free_bytes", free, "mcp"),
        ]
        # Recorded as used, not only as free, because that is what the NAS's own history
        # gives — one series, so an import and a live reading can sit on the same chart.
        if capacity is not None and free is not None:
            outcome.readings.append(
                Reading(target.id, "volume_used_bytes", capacity - free, "mcp")
            )


def _slow_mcp(mcp: qnap_mcp.Target, shares: list[Watched], outcome: Outcome) -> None:
    """The NAS's own per-share counts, which it computed at some earlier time."""
    connection = qnap_mcp.Connection(mcp)
    try:
        connection.open()
        listing = json.loads(connection.call_tool("list_shared_folder", {"detailed": True}))
    except (qnap_mcp.McpError, ValueError) as exc:
        outcome.note("list_shared_folder", exc)
        return
    finally:
        connection.close()

    by_name = {str(s.get("name") or ""): s for s in listing.get("sharedfolders") or []}
    for target in shares:
        share = by_name.get(target.ref)
        if share is None:
            outcome.problems.append(f"share {target.ref} was not reported by the NAS")
            continue
        outcome.readings += [
            Reading(target.id, "file_count_reported", _int(share.get("file_count")), "mcp",
                    cached=True),
            Reading(target.id, "dir_count_reported", _int(share.get("dir_count")), "mcp",
                    cached=True),
        ]
