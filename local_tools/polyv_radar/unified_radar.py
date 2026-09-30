"""Read-only projection over the independent POLYV and ZigoAI stores."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .storage import RadarStore
from .zigo_store import ZigoStore


class UnifiedRadarReader:
    def __init__(self, polyv_root: Path, zigo_db: Path | None = None):
        self.polyv_root = Path(polyv_root)
        self.zigo_db = Path(zigo_db or self.polyv_root / "zigoai" / "radar.sqlite3")

    def _zigo(self) -> ZigoStore:
        store = ZigoStore(self.zigo_db)
        store.initialize()
        return store

    def _polyv_summary(self) -> dict:
        store = RadarStore(self.polyv_root / "radar.sqlite3")
        store.initialize()
        row = store.connection.execute("SELECT run_id FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()
        run_id = str(row[0]) if row else ""
        if not run_id:
            store.close()
            return {"runs": 0, "contents": 0, "comments": 0, "candidates": 0, "verified": 0, "revision": 0}
        counts = store.connection.execute(
            "SELECT (SELECT COUNT(*) FROM runs) AS runs, "
            "(SELECT COUNT(DISTINCT platform || '|' || content_id) FROM run_contents) AS contents, "
            "(SELECT COUNT(DISTINCT platform || '|' || comment_id) FROM run_comments) AS comments, "
            "(SELECT COUNT(DISTINCT run_id || '|' || platform || '|' || content_id || '|' || comment_id) FROM leads) AS candidates"
        ).fetchone()
        result = {"runs": int(counts["runs"]), "contents": int(counts["contents"]), "comments": int(counts["comments"]),
                  "candidates": int(counts["candidates"]), "verified": 0, "revision": 0, "run_id": run_id}
        store.close()
        return result

    def summary(self, brand: str = "all", product_domain: str | None = None) -> dict:
        if brand not in {"all", "polyv", "zigo"}:
            raise ValueError("brand must be all, polyv or zigo")
        polyv = self._polyv_summary()
        zigo_store = self._zigo()
        zigo = zigo_store.summary(product_domain)
        zigo_store.close()
        if brand == "polyv":
            selected = polyv
        elif brand == "zigo":
            selected = zigo
        else:
            selected = {
                "runs": polyv["runs"] + zigo["runs"],
                "contents": polyv["contents"] + zigo["contents"],
                "comments": polyv["comments"] + zigo["comments"],
                "candidates": polyv["candidates"] + zigo["candidates"],
                "verified": polyv["verified"] + zigo["verified"],
                "revision": max(polyv["revision"], zigo["revision"]),
            }
        return {"brand": brand, "product_domain": product_domain, **selected,
                "brands": {"polyv": polyv["contents"], "zigo": zigo["contents"]},
                "last_updated": self.last_updated()}

    def runs(self, brand: str = "all") -> list[dict]:
        rows: list[dict] = []
        if brand in {"all", "polyv"}:
            store = RadarStore(self.polyv_root / "radar.sqlite3")
            store.initialize()
            for row in store.connection.execute("SELECT run_id, started_at, finished_at, status FROM runs ORDER BY started_at DESC").fetchall():
                rows.append({"brand": "polyv", "product_domain": "polyv", **dict(row)})
            store.close()
        if brand in {"all", "zigo"}:
            store = self._zigo()
            rows.extend({"brand": "zigo", **row} for row in store.list_runs())
            store.close()
        return sorted(rows, key=lambda row: row.get("started_at", ""), reverse=True)

    def leads(self, brand: str = "all", product_domain: str | None = None, run_id: str | None = None, limit: int = 100, include_excluded: bool = False) -> list[dict]:
        rows: list[dict] = []
        if brand in {"all", "polyv"} and not product_domain:
            store = RadarStore(self.polyv_root / "radar.sqlite3")
            store.initialize()
            selected_run = run_id or (self.runs("polyv")[0]["run_id"] if self.runs("polyv") else "")
            rows = [{"brand": "polyv", "product_domain": "polyv", **lead.to_dict()} for lead in store.load_leads(selected_run)[:limit]] if selected_run else []
            store.close()
            if brand == "polyv":
                return rows
        store = self._zigo()
        zigo_rows = []
        for row in store.list_candidates(run_id, product_domain, limit, include_excluded):
            zigo_rows.append({"brand": "zigo", "product_domain": row["product_domain"], "run_id": row["run_id"],
                              "candidate_id": row["candidate_id"], "platform": row["platform"], "content_id": row["content_id"],
                              "comment_id": row["comment_id"], "decision": row["decision"], "score": row["rule_score"],
                              **__import__("json").loads(row["payload"])})
        store.close()
        return (rows + zigo_rows)[:limit]

    def last_updated(self) -> str:
        paths = [self.polyv_root / "radar.sqlite3", self.polyv_root / "radar.sqlite3-wal", self.zigo_db, Path(str(self.zigo_db) + "-wal")]
        values = []
        latest = 0
        for path in paths:
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            latest = max(latest, stat.st_mtime_ns)
            values.append(f"{path}:{stat.st_mtime_ns}:{stat.st_size}")
        return hashlib.sha256("|".join(values).encode()).hexdigest()[:16]
