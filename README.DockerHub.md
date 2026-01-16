# Wavespeed.ai Statistics Prometheus Exporter

Fetches Wavespeed.ai balance and usage statistics and exposes Prometheus metrics for Grafana dashboards.

## Endpoints

- `/metrics` Prometheus text format
- `/healthz` health check

## Metrics

- `wavespeed_balance_usd` (gauge)
- `wavespeed_daily_usage` (gauge)

## Environment variables

Required:

- `WS_AI_TOKEN` Wavespeed.ai API token
- `PORT` HTTP port to listen on

Optional:

- `WS_AI_BASE_URL` (default: `https://api.wavespeed.ai`)
- `UPDATE_INTERVAL_SECONDS` (default: `300`)
- `REQUEST_TIMEOUT_SECONDS` (default: `10`)

## Docker run

```bash
docker run --rm -p 8080:8080 \
	-e WS_AI_TOKEN="..." \
	-e PORT=8080 \
	<IMAGE>
```
