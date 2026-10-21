# cinc-dashboard

Web dashboard for CINC/Chef converge data. Shows the latest converge per node and
lets you drill into the individual resources (updated / up-to-date / failed).

```
postgres ── cinc_collector DB (canonical store)
collector ── receives converge payloads on :8080, writes runs + resource_events
api       ── FastAPI JSON backend on :8000 (/runs, /api/*)
ui        ── nginx WebUI on :80, proxies /runs and /api/* to the api
```

All four services share one compose network and address each other by service
name, so nothing is bound to a host IP.

## Quick start — build from source

```bash
git clone <this repo> cinc-dashboard && cd cinc-dashboard
cp .env.example .env          # set POSTGRES_PASSWORD, keep CINC_COLLECTOR_TOKEN
docker compose up -d --build
```

Open <http://localhost/>.

## Quick start — pull the prebuilt images

No build step. Images are published to Docker Hub:

```bash
cp .env.example .env          # still required: DB password + ingest token
docker compose pull
docker compose up -d
```

| Image | Purpose |
|---|---|
| `chunkylover59/cinc-dashboard-collector` | converge ingest receiver |
| `chunkylover59/cinc-dashboard-api` | FastAPI JSON backend |
| `chunkylover59/cinc-dashboard-ui` | nginx WebUI + API proxy |

`postgres:17-alpine` is upstream and pulled automatically.

To use a different registry or tag:

```bash
CINC_REGISTRY=ghcr.io/myorg CINC_IMAGE_TAG=v0.1.0 docker compose pull
```

## Configuration

`.env` is required (see `.env.example`) and is **not** committed:

| Variable | Meaning |
|---|---|
| `POSTGRES_PASSWORD` | DB password — set a real one |
| `POSTGRES_USER` / `POSTGRES_DB` | DB credentials (defaults fine) |
| `CINC_COLLECTOR_TOKEN` | shared secret; nodes send it as `CINC_COLLECTOR_TOKEN` |

> Changing `CINC_COLLECTOR_TOKEN` makes every node get `401` until its
> `data_collector` config is updated. Keep it stable across redeploys.

## Ports

| Port | Service |
|---|---|
| `80` | WebUI (single entry point) |
| `8000` | API (also reachable through the UI proxy) |
| `8080` | Collector ingest endpoint |

## Persistent data

- `postgres-data` named volume — the `runs` and `resource_events` tables.
- `./data/raw-events/` bind mount — raw payloads as NDJSON (`collector.ndjson`),
  kept for debugging. A one-shot `collector-init` container fixes its ownership
  to uid 10001 on first boot, so the collector can append to it.

## Publishing images

```bash
docker login
scripts/publish-images.sh                        # :latest
CINC_IMAGE_TAG=v0.1.0 scripts/publish-images.sh  # a versioned tag
```

Only the three custom images are pushed; `postgres` is never published.

## Pointing nodes at the collector

Send converge data to `http://<host>:8080/` with the header:

```
CINC_COLLECTOR_TOKEN: <the token from .env>
```

## API

| Endpoint | Returns |
|---|---|
| `GET /runs` | most recent runs |
| `GET /api/nodes` | one row per node with latest run |
| `GET /api/nodes/{name}/runs` | all runs for a node |
| `GET /api/runs/{run_id}` | one run + its resource events |
| `GET /api/runs/{run_id}/resources` | just the resource events |
| `GET /api/summary` | aggregate counts |
| `GET /health` | DB connectivity |

## Verifying a fresh deploy

```bash
curl -s localhost/api/summary
# {"total":0,"updated":0,"by_status":{},"latest_run":null}
curl -s localhost:8000/health
# {"status":"ok","db":"postgres:5432/cinc_collector"}
```

> The UI proxy forwards `/api/*` and `/runs` only; `/health` is served by the
> API container directly on port 8000.

Then open the UI: node cards appear once a node reports in, and clicking a card
(or a row in a node's **History**) fetches that run's per-resource detail.

## Notes

- Resources that did not change are **up-to-date**, not failed. Chef took no
  action on them; a run-level `total - updated` remainder must never be labelled
  "failed". Real failures come only from `resource_events.status`.
- `skipped` is folded into the up-to-date group (both mean "no action taken");
  the per-resource **Result** column still shows the exact status.
