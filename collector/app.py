import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from psycopg import sql
from psycopg_pool import ConnectionPool

app = FastAPI(title="Cinc Data Collector")

token = os.environ["CINC_COLLECTOR_TOKEN"]
event_dir = Path(os.environ.get("EVENT_DIR", "/data/raw-events"))
event_file = event_dir / "collector.ndjson"

# DB host/port come from the environment so the stack stays portable: inside the
# compose stack this resolves to the `postgres` service by name. Never hardcode a
# host here — a hardcoded host silently points at whatever publishes that port,
# which is how ingest drifted onto a stray container for days.
POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "postgres")
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")

database_url = (
    f"postgresql://{os.environ['POSTGRES_USER']}:"
    f"{os.environ['POSTGRES_PASSWORD']}@{POSTGRES_HOST}:{POSTGRES_PORT}/"
    f"{os.environ['POSTGRES_DB']}"
)

pool = ConnectionPool(
    conninfo=database_url,
    min_size=1,
    max_size=5,
    open=False,
)


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


@app.on_event("shutdown")
def shutdown():
    pool.close()


@app.get("/healthz")
async def healthz():
    with pool.connection() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok"}


@app.post("/{collector_path:path}")
async def collect(
    collector_path: str,
    request: Request,
    x_data_collector_token: str | None = Header(default=None),
):
    if not x_data_collector_token or not hmac.compare_digest(
        x_data_collector_token, token
    ):
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
        "headers": {
            key: value
            for key, value in request.headers.items()
            if key.lower()
            not in {"authorization", "cookie", "x-data-collector-token"}
        },
        "payload": payload,
    }

    event_dir.mkdir(parents=True, exist_ok=True)

    with event_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, separators=(",", ":")) + "\n")

    run_id = payload.get("run_id")
    node_name = payload.get("node_name")

    if not run_id or not node_name:
        return JSONResponse(
            status_code=202,
            content={"status": "captured", "indexed": False},
        )

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
                )
                VALUES (
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
                    )
                    VALUES (
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
                        "duration_ms": int(resource["duration"])
                        if str(resource.get("duration", "")).isdigit()
                        else None,
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
