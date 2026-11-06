# cinc-dashboard

Web dashboard for CINC/Chef converge data. Shows the latest converge per node and
lets you drill into the individual resources (updated / up-to-date / failed).

```
postgres ── cinc_collector DB (canonical store)
app      ── unified FastAPI service: converge ingest + query API + WebUI
```

Single container, single port (8080). All services share one compose network.

## Quick start — build from source

```bash
git clone <this repo> cinc-dashboard && cd cinc-dashboard
cp .env.example .env          # set POSTGRES_PASSWORD, keep CINC_COLLECTOR_TOKEN
docker compose up -d --build
```

Open <http://localhost:8080/>.

## Quick start — pull the prebuilt image

No build step. Image is published to GHCR:

```bash
cp .env.example .env          # still required: DB password + ingest token
CINC_REGISTRY=ghcr.io/vfrdirk CINC_IMAGE_TAG=v0.2.0 docker compose pull
CINC_REGISTRY=ghcr.io/vfrdirk CINC_IMAGE_TAG=v0.2.0 docker compose up -d
```

| Image | Purpose |
|---|---|
| `ghcr.io/vfrdirk/cinc-dashboard` | unified app (ingest + API + WebUI) |

`postgres:17-alpine` is upstream and pulled automatically.

To use a different registry or tag:

```bash
CINC_REGISTRY=ghcr.io/myorg CINC_IMAGE_TAG=v0.2.0 docker compose pull
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
| `8080` | Single entry point (WebUI + API + ingest) |

## Persistent data

- `postgres-data` named volume — the `runs` and `resource_events` tables.
- `./data/raw-events/` bind mount — raw payloads as NDJSON (`collector.ndjson`),
  kept for debugging.

## Publishing images

```bash
docker login ghcr.io
CINC_REGISTRY=ghcr.io/vfrdirk CINC_IMAGE_TAG=v0.2.0 ./scripts/publish-images.sh
```

Only the app image is pushed; `postgres` is never published.

## Pointing nodes at the collector

Configure `data_collector` in the node's `client.rb` (or `cinc.rb`):

```ruby
data_collector.server_url = "http://<host>:8080/"
data_collector.token      = "<the CINC_COLLECTOR_TOKEN from .env>"
```

Or set the environment variable on the node before running cinc-client:

```bash
export CINC_COLLECTOR_TOKEN=<the token from .env>
```

Send converge data to `http://<host>:8080/` with the header:

```
CINC_COLLECTOR_TOKEN: <the token from .env>
```

Nodes report on every converge. The dashboard updates automatically once a run is
ingested; node cards appear after the first successful report.

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
curl -s localhost:8080/api/summary
# {"total":0,"updated":0,"by_status":{},"latest_run":null}
curl -s localhost:8080/health
# {"status":"ok","db":"postgres:5432/cinc_collector"}
```

Then open the UI: node cards appear once a node reports in, and clicking a card
(or a row in a node's **History**) fetches that run's per-resource detail.

## Notes

- Resources that did not change are **up-to-date**, not failed. Chef took no
  action on them; a run-level `total - updated` remainder must never be labelled
  "failed". Real failures come only from `resource_events.status`.
- `skipped` is folded into the up-to-date group (both mean "no action taken");
  the per-resource **Result** column still shows the exact status.
