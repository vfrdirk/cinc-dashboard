# cinc-dashboard-ui
#
# Distributable WebUI for cinc-dashboard.
#
# Serves latest-run-card.html at GET / and proxies /runs and /api/* to the
# cinc-dashboard-api (FastAPI JSON backend). This lets the UI fetch live data
# (and never fall back to static sample data via file://).
#
# Usage (compose):
#   services:
#     ui:
#       build: ./ui
#       ports: ["80:80"]
#       depends_on: [api]
#       networks: [cinc-net]
#
# The api hostname must point at the cinc-dashboard-api service.

FROM nginx:alpine

COPY latest-run-card.html /usr/share/nginx/html/
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
