"""cinc-dashboard live API.

Serves run/node/summary data queried from the canonical `cinc_collector` Postgres
store (the .27 `postgres` container on 192.168.1.27:5432), instead of the stale
embedded JSON that was in the default app.py.

DB wiring: env over config; defaults are for the .27 docker `cinc-net` deploy.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
import psycopg

app = FastAPI()

# Allow any origin so the UI (served by the Umbrel proxy or the API container)
# can call the live endpoints from a different origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# DB wiring: env over config; defaults are for the .27 docker `cinc-net` deploy.
PG_HOST = os.environ.get("POSTGRES_HOST", "192.168.1.27")
PG_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
PG_DB = os.environ.get("POSTGRES_DB", "cinc_collector")
PG_USER = os.environ.get("POSTGRES_USER", "cinc_collector")
PG_PASS = os.environ.get("POSTGRES_PASSWORD", "secret")


def _connect():
    return psycopg.connect(
        host=PG_HOST,
        port=PG_PORT,
        dbname=PG_DB,
        user=PG_USER,
        password=PG_PASS,
        connect_timeout=5,
    )


def _row_to_dict(row):
    return {
        "run_id": row[0],
        "node_name": row[1],
        "status": row[2],
        "start_time": row[3],
        "duration_ms": row[4],
        "total_resources": row[5],
        "updated_resources": row[6],
    }


@app.get("/health")
def health():
    try:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
        finally:
            conn.close()
        return {"status": "ok", "db": f"{PG_HOST}:{PG_PORT}/{PG_DB}"}
    except Exception as exc:
        return {
            "status": "degraded",
            "db": f"{PG_HOST}:{PG_PORT}/{PG_DB}",
            "detail": str(exc),
        }


@app.get("/runs")
def runs():
    """Return the most recent converge runs (live data from the Postgres DB)."""
    try:
        with _connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT run_id, node_name, status, start_time, duration_ms, "
                "total_resource_count, updated_resource_count "
                "FROM runs ORDER BY start_time DESC NULLS LAST LIMIT 50"
            )
            rows = [_row_to_dict(r) for r in cur.fetchall()]
        return {"runs": rows}
    except Exception as exc:
        return {"runs": [], "error": str(exc)}


@app.get("/api/nodes")
def api_nodes():
    """Return one row per node with its last run time."""
    try:
        with _connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT r.node_name, "
                "(SELECT r2.status FROM runs r2 WHERE r2.node_name = r.node_name "
                "ORDER BY r2.start_time DESC NULLS LAST LIMIT 1) AS status, "
                "MAX(r.start_time) AS last_run "
                "FROM runs r GROUP BY r.node_name "
                "ORDER BY last_run DESC NULLS LAST"
            )
            rows = [
                {"node_name": r[0], "status": r[1], "last_run": r[2]}
                for r in cur.fetchall()
            ]
        return {"nodes": rows}
    except Exception as exc:
        return {"nodes": [], "error": str(exc)}


@app.get("/api/summary")
def api_summary():
    """Return aggregate converge counts."""
    try:
        with _connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT status, count(*) FROM runs GROUP BY status")
            by_status = {r[0]: r[1] for r in cur.fetchall()}
            cur.execute("SELECT count(*), max(start_time) FROM runs")
            total, latest = cur.fetchone()
            cur.execute(
                "SELECT sum(updated_resource_count) FROM runs WHERE status='success'"
            )
            updated = cur.fetchone()[0] or 0
        return {
            "total": total,
            "updated": updated,
            "by_status": by_status,
            "latest_run": latest,
        }
    except Exception as exc:
        return {"total": 0, "by_status": {}, "latest_run": None, "error": str(exc)}


@app.get("/api/nodes/{node_name}/runs")
def api_node_runs(node_name):
    """Return historical runs for a specific node (latest first)."""
    try:
        with _connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT run_id, node_name, status, start_time, duration_ms, "
                "total_resource_count, updated_resource_count "
                "FROM runs WHERE node_name=%s "
                "ORDER BY start_time DESC NULLS LAST",
                (node_name,),
            )
            rows = [_row_to_dict(r) for r in cur.fetchall()]
        return {"node_name": node_name, "runs": rows}
    except Exception as exc:
        return {"node_name": node_name, "runs": [], "error": str(exc)}


@app.get("/api/runs/{run_id}")
def api_run_detail(run_id):
    """Return one run plus its resource events."""
    try:
        with _connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT run_id, node_name, status, start_time, duration_ms, "
                "total_resource_count, updated_resource_count "
                "FROM runs WHERE run_id=%s",
                (run_id,),
            )
            row = cur.fetchone()
            if not row:
                return {"run_id": run_id, "error": "not found"}
            run = _row_to_dict(row)
            cur.execute(
                "SELECT resource_type, resource_name, status, result, "
                "duration_ms, cookbook_name, cookbook_version "
                "FROM resource_events WHERE run_id=%s ORDER BY event_order",
                (run_id,),
            )
            run["resource_events"] = [
                {
                    "resource_type": r[0],
                    "resource_name": r[1],
                    "status": r[2],
                    "result": r[3],
                    "duration_ms": r[4],
                    "cookbook_name": r[5],
                    "cookbook_version": r[6],
                }
                for r in cur.fetchall()
            ]
        return run
    except Exception as exc:
        return {"run_id": run_id, "error": str(exc)}


@app.get("/api/runs/{run_id}/resources")
def api_run_resources(run_id):
    """Return the resource events for a single run."""
    try:
        with _connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT resource_type, resource_name, status, result, "
                "duration_ms, cookbook_name, cookbook_version "
                "FROM resource_events WHERE run_id=%s ORDER BY event_order",
                (run_id,),
            )
            rows = [
                {
                    "resource_type": r[0],
                    "resource_name": r[1],
                    "status": r[2],
                    "result": r[3],
                    "duration_ms": r[4],
                    "cookbook_name": r[5],
                    "cookbook_version": r[6],
                }
                for r in cur.fetchall()
            ]
        return {"run_id": run_id, "resources": rows}
    except Exception as exc:
        return {"run_id": run_id, "resources": [], "error": str(exc)}


@app.get("/")
def index():
    return {
        "note": "cinc-dashboard live API (DB cinc_collector on 192.168.1.27:5432). "
                "GET /runs | /api/nodes | /api/summary"
    }
