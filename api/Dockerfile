# cinc-dashboard-api — FastAPI JSON backend.
#
# Serves live converge data queried from the cinc_collector Postgres store:
#   GET /runs          live runs (last 50, ordered start_time DESC NULLS LAST)
#   GET /api/nodes     one row per node with latest run + status
#   GET /api/summary   Total / Updated / by_status / latest_run
#   GET /api/runs/{id}
#   GET /api/runs/{id}/resources
#   GET /health
#
# DB wiring: env over config; defaults target the .27 docker `cinc-net` deploy.
#   POSTGRES_HOST=postgres   (compose service name)
#   POSTGRES_PORT=5432
#   POSTGRES_DB=cinc_collector
#   POSTGRES_USER=cinc_collector
#   POSTGRES_PASSWORD=<set>

FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y gcc python3-dev libpq-dev && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
RUN pip install --upgrade pip

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py /app/

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
