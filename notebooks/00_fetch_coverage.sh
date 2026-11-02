#!/usr/bin/env bash
# Downloads small snapshots used by 00_data_coverage.py.
# Needs PURPLEAIR_KEY, OPENAQ_KEY and AIRNOW_KEY in the environment (see .env.example).
set -euo pipefail
: "${PURPLEAIR_KEY:?missing}" "${OPENAQ_KEY:?missing}" "${AIRNOW_KEY:?missing}"
out="data/coverage"
mkdir -p "$out"

curl -s --fail-with-body -o "$out/airnow_bay.json" \
  "https://www.airnowapi.org/aq/data/?startDate=2026-11-01T12&endDate=2026-11-01T13&parameters=PM25&BBOX=-123.0,37.2,-121.6,38.3&dataType=C&format=application/json&verbose=1&monitorType=0&API_KEY=$AIRNOW_KEY"

curl -s --fail-with-body -H "X-API-Key: $PURPLEAIR_KEY" -o "$out/purpleair_bay.json" \
  "https://api.purpleair.com/v1/sensors?fields=latitude,longitude&location_type=0&max_age=3600&nwlng=-123.0&nwlat=38.3&selng=-121.6&selat=37.2"

curl -s --fail-with-body -H "X-API-Key: $PURPLEAIR_KEY" -o "$out/purpleair_kl.json" \
  "https://api.purpleair.com/v1/sensors?fields=latitude,longitude&location_type=0&max_age=3600&nwlng=101.5&nwlat=3.3&selng=101.8&selat=2.9"

curl -s --fail-with-body -H "X-API-Key: $OPENAQ_KEY" -o "$out/openaq_my.json" \
  "https://api.openaq.org/v3/locations?iso=MY&limit=1000"

ls -lh "$out"
