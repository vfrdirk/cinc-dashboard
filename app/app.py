"""cinc-dashboard unified app.

Single service combining:
  - collector: receives converge payloads on :8080, writes runs + resource_events
  - api:       FastAPI JSON backend (/runs, /api/*, /health)
  - ui:        serves the static dashboard (latest-run-card.html) at /

Backed by Postgres (postgres service). One container, one image.
"""
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from psycopg import sql
from psycopg_pool import ConnectionPool

app = FastAPI(title="Cinc Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Config ---
TOKEN = os.environ["CINC_COLLECTOR_TOKEN"]
EVENT_DIR = Path(os.environ.get("EVENT_DIR", "/data/raw-events"))
EVENT_FILE = EVENT_DIR / "collector.ndjson"

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "postgres")
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_DB = os.environ.get("POSTGRES_DB", "cinc_collector")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "cinc_collector")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "")

DATABASE_URL = (
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)

pool = ConnectionPool(conninfo=DATABASE_URL, min_size=1, max_size=10, open=False)

UI_DIR = Path(os.environ.get("UI_DIR", "/app/ui"))


def json_value(value):
    return json.dumps(value, separators=(",", ":")) if value is not None else None


def parse_timestamp(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def duration_ms(start_time, end_time):
    if not start_time or not end_time:
        return None
    return round((end_time - start_time).total_seconds() * 1000)


@app.on_event("startup")
def startup():
    pool.open(wait=True)
    EVENT_DIR.mkdir(parents=True, exist_ok=True)


@app.on_event("shutdown")
def shutdown():
    pool.close()


# --- Health ---
@app.get("/health")
def health():
    try:
        with pool.connection() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok", "db": f"{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"}
    except Exception as exc:
        return {"status": "degraded", "db": f"{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}", "detail": str(exc)}


@app.get("/healthz")
async def healthz():
    with pool.connection() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok"}


# --- Ingest (collector) ---
@app.post("/")
@app.post("/{collector_path:path}")
async def collect(request: Request, collector_path: str = "",
                 x_data_collector_token: str | None = Header(default=None)):
    if not x_data_collector_token or not hmac.compare_digest(x_data_collector_token, TOKEN):
        raise HTTPException(status_code=401, detail="invalid data collector token")

    raw_body = await request.body()
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="request body must be JSON")

    received_at = datetime.now(timezone.utc)
    event = {
        "received_at": received_at.isoformat(),
        "collector_path": "/" + collector_path,
        "method": request.method,
        "remote_ip": request.client.host if request.client else None,
        "payload": payload,
    }
    EVENT_DIR.mkdir(parents=True, exist_ok=True)
    with EVENT_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, separators=(",", ":")) + "\n")

    run_id = payload.get("run_id")
    node_name = payload.get("node_name")
    if not run_id or not node_name:
        return JSONResponse(status_code=202, content={"status": "captured", "indexed": False})

    start_time = parse_timestamp(payload.get("start_time"))
    end_time = parse_timestamp(payload.get("end_time"))

    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO runs (
                  run_id, node_name, organization_name, chef_server_fqdn,
                  status, start_time, end_time, received_at, duration_ms,
                  total_resource_count, updated_resource_count, message_type,
                  message_version, entity_uuid, policy_name, policy_group,
                  source, run_list, expanded_run_list, cookbooks,
                  deprecations, raw_payload
                ) VALUES (
                  %(run_id)s, %(node_name)s, %(organization_name)s,
                  %(chef_server_fqdn)s, %(status)s, %(start_time)s,
                  %(end_time)s, %(received_at)s, %(duration_ms)s,
                  %(total_resource_count)s, %(updated_resource_count)s,
                  %(message_type)s, %(message_version)s, %(entity_uuid)s,
                  %(policy_name)s, %(policy_group)s, %(source)s,
                  %(run_list)s::jsonb, %(expanded_run_list)s::jsonb,
                  %(cookbooks)s::jsonb, %(deprecations)s::jsonb,
                  %(raw_payload)s::jsonb
                )
                ON CONFLICT (run_id) DO UPDATE SET
                  node_name = EXCLUDED.node_name,
                  organization_name = EXCLUDED.organization_name,
                  chef_server_fqdn = EXCLUDED.chef_server_fqdn,
                  status = EXCLUDED.status,
                  start_time = EXCLUDED.start_time,
                  end_time = EXCLUDED.end_time,
                  received_at = EXCLUDED.received_at,
                  duration_ms = EXCLUDED.duration_ms,
                  total_resource_count = EXCLUDED.total_resource_count,
                  updated_resource_count = EXCLUDED.updated_resource_count,
                  message_type = EXCLUDED.message_type,
                  message_version = EXCLUDED.message_version,
                  entity_uuid = EXCLUDED.entity_uuid,
                  policy_name = EXCLUDED.policy_name,
                  policy_group = EXCLUDED.policy_group,
                  source = EXCLUDED.source,
                  run_list = EXCLUDED.run_list,
                  expanded_run_list = EXCLUDED.expanded_run_list,
                  cookbooks = EXCLUDED.cookbooks,
                  deprecations = EXCLUDED.deprecations,
                  raw_payload = EXCLUDED.raw_payload
                """,
                {
                    "run_id": run_id,
                    "node_name": node_name,
                    "organization_name": payload.get("organization_name"),
                    "chef_server_fqdn": payload.get("chef_server_fqdn"),
                    "status": payload.get("status", "unknown"),
                    "start_time": start_time,
                    "end_time": end_time,
                    "received_at": received_at,
                    "duration_ms": duration_ms(start_time, end_time),
                    "total_resource_count": payload.get("total_resource_count"),
                    "updated_resource_count": payload.get("updated_resource_count"),
                    "message_type": payload.get("message_type"),
                    "message_version": payload.get("message_version"),
                    "entity_uuid": payload.get("entity_uuid"),
                    "policy_name": payload.get("policy_name"),
                    "policy_group": payload.get("policy_group"),
                    "source": payload.get("source"),
                    "run_list": json_value(payload.get("run_list")),
                    "expanded_run_list": json_value(payload.get("expanded_run_list")),
                    "cookbooks": json_value(payload.get("cookbooks")),
                    "deprecations": json_value(payload.get("deprecations")),
                    "raw_payload": json_value(payload),
                },
            )
            cur.execute("DELETE FROM resource_events WHERE run_id = %s", (run_id,))
            resources = payload.get("resources") or []
            for event_order, resource in enumerate(resources):
                cur.execute(
                    """
                    INSERT INTO resource_events (
                      run_id, resource_id, resource_type, resource_name,
                      status, result, duration_ms, cookbook_name,
                      cookbook_version, recipe_name, ignore_failure,
                      event_order, before_state, after_state, delta
                    ) VALUES (
                      %(run_id)s, %(resource_id)s, %(resource_type)s,
                      %(resource_name)s, %(status)s, %(result)s,
                      %(duration_ms)s, %(cookbook_name)s,
                      %(cookbook_version)s, %(recipe_name)s,
                      %(ignore_failure)s, %(event_order)s,
                      %(before_state)s::jsonb, %(after_state)s::jsonb,
                      %(delta)s::jsonb
                    )
                    """,
                    {
                        "run_id": run_id,
                        "resource_id": str(resource.get("id", event_order)),
                        "resource_type": resource.get("type", "unknown"),
                        "resource_name": resource.get("name", "unknown"),
                        "status": resource.get("status"),
                        "result": resource.get("result"),
                        "duration_ms": int(resource["duration"]) if str(resource.get("duration", "")).isdigit() else None,
                        "cookbook_name": resource.get("cookbook_name"),
                        "cookbook_version": resource.get("cookbook_version"),
                        "recipe_name": resource.get("recipe_name"),
                        "ignore_failure": resource.get("ignore_failure"),
                        "event_order": event_order,
                        "before_state": json_value(resource.get("before")),
                        "after_state": json_value(resource.get("after")),
                        "delta": json_value(resource.get("delta")),
                    },
                )
        conn.commit()
    return {"status": "accepted", "indexed": True}


# --- Query API (from api) ---
def _row_to_dict(row):
    return {
        "run_id": row[0], "node_name": row[1], "status": row[2],
        "start_time": row[3], "duration_ms": row[4],
        "total_resources": row[5], "updated_resources": row[6],
    }


@app.get("/runs")
def runs():
    try:
        with pool.connection() as conn:
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
    try:
        with pool.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT r.node_name, "
                "(SELECT r2.status FROM runs r2 WHERE r2.node_name = r.node_name "
                "ORDER BY r2.start_time DESC NULLS LAST LIMIT 1) AS status, "
                "MAX(r.start_time) AS last_run "
                "FROM runs r GROUP BY r.node_name "
                "ORDER BY last_run DESC NULLS LAST"
            )
            rows = [{"node_name": r[0], "status": r[1], "last_run": r[2]} for r in cur.fetchall()]
        return {"nodes": rows}
    except Exception as exc:
        return {"nodes": [], "error": str(exc)}


@app.get("/api/summary")
def api_summary():
    try:
        with pool.connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT status, count(*) FROM runs GROUP BY status")
            by_status = {r[0]: r[1] for r in cur.fetchall()}
            cur.execute("SELECT count(*), max(start_time) FROM runs")
            total, latest = cur.fetchone()
            cur.execute("SELECT sum(updated_resource_count) FROM runs WHERE status='success'")
            updated = cur.fetchone()[0] or 0
        return {"total": total, "updated": updated, "by_status": by_status, "latest_run": latest}
    except Exception as exc:
        return {"total": 0, "by_status": {}, "latest_run": None, "error": str(exc)}


@app.get("/api/nodes/{node_name}/runs")
def api_node_runs(node_name: str):
    try:
        with pool.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT run_id, node_name, status, start_time, duration_ms, "
                "total_resource_count, updated_resource_count "
                "FROM runs WHERE node_name=%s ORDER BY start_time DESC NULLS LAST",
                (node_name,),
            )
            rows = [_row_to_dict(r) for r in cur.fetchall()]
        return {"node_name": node_name, "runs": rows}
    except Exception as exc:
        return {"node_name": node_name, "runs": [], "error": str(exc)}


@app.get("/api/runs/{run_id}")
def api_run_detail(run_id: str):
    try:
        with pool.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT run_id, node_name, status, start_time, duration_ms, "
                "total_resource_count, updated_resource_count "
                "FROM runs WHERE run_id=%s", (run_id,),
            )
            row = cur.fetchone()
            if not row:
                return {"run_id": run_id, "error": "not found"}
            run = _row_to_dict(row)
            cur.execute(
                "SELECT resource_type, resource_name, status, result, "
                "duration_ms, cookbook_name, cookbook_version "
                "FROM resource_events WHERE run_id=%s ORDER BY event_order", (run_id,),
            )
            run["resource_events"] = [
                {"resource_type": r[0], "resource_name": r[1], "status": r[2],
                 "result": r[3], "duration_ms": r[4], "cookbook_name": r[5],
                 "cookbook_version": r[6]}
                for r in cur.fetchall()
            ]
        return run
    except Exception as exc:
        return {"run_id": run_id, "error": str(exc)}


@app.get("/api/runs/{run_id}/resources")
def api_run_resources(run_id: str):
    try:
        with pool.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT resource_type, resource_name, status, result, "
                "duration_ms, cookbook_name, cookbook_version "
                "FROM resource_events WHERE run_id=%s ORDER BY event_order", (run_id,),
            )
            rows = [
                {"resource_type": r[0], "resource_name": r[1], "status": r[2],
                 "result": r[3], "duration_ms": r[4], "cookbook_name": r[5],
                 "cookbook_version": r[6]}
                for r in cur.fetchall()
            ]
        return {"run_id": run_id, "resources": rows}
    except Exception as exc:
        return {"run_id": run_id, "resources": [], "error": str(exc)}


# --- Static UI ---
if UI_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(UI_DIR)), name="static")

    @app.get("/")
    def index():
        html = UI_DIR / "latest-run-card.html"
        if html.exists():
            return FileResponse(str(html))
        return {"note": "cinc-dashboard unified API. GET /runs | /api/nodes | /api/summary | /health"}
else:
    @app.get("/")
    def index():
        return {"note": "cinc-dashboard unified API. GET /runs | /api/nodes | /api/summary | /health"}
