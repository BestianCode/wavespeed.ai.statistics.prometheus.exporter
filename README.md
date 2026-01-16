# Wavespeed.ai Statistics Prometheus Exporter

Fetches Wavespeed.ai balance and usage statistics and exposes Prometheus metrics for Grafana dashboards.

## Endpoints

- `/metrics` Prometheus text format
- `/healthz` simple health check

## Metrics

This exporter exposes **exactly two metric names**:

1. `wavespeed_balance_usd` (gauge)
2. `wavespeed_daily_usage` (gauge)

`wavespeed_daily_usage` is a single metric name that contains both counts and costs, using labels:

- `date` in `YYYY-MM-DD` format
- `metric` is `count` or `cost_usd`
- `model_uuid` empty for daily totals, or the model id for per-model series
- `model_type` empty for daily totals, or the model type for per-model series

## Configuration

Required:

- `WS_AI_TOKEN` Wavespeed.ai API token
- `PORT` HTTP port to listen on

Optional:

- `WS_AI_BASE_URL` (default: `https://api.wavespeed.ai`)
- `UPDATE_INTERVAL_SECONDS` (default: `300`)
- `REQUEST_TIMEOUT_SECONDS` (default: `10`)

## Run locally

```bash
python3 -m venv .env
source .env/bin/activate
pip install -r requirements.txt

export WS_AI_TOKEN="..."
export PORT=8080

python3 main.py
curl -fsS http://localhost:8080/metrics
```

## Run with Docker

```bash
docker run --rm -p 8080:8080 \
  -e WS_AI_TOKEN="..." \
  -e PORT=8080 \
  <YOUR_IMAGE>
```

## Deploy with Helm

The Helm chart is located in `helmchart/wavespeed.ai.stat`.

```bash
helm upgrade --install wavespeed-exporter helmchart/wavespeed.ai.stat \
  --namespace wavespeed-exporter --create-namespace \
  --values ./my-values.yaml
```

## PromQL examples

Daily generations (total):

```promql
sum by (date) (wavespeed_daily_usage{metric="count", model_uuid=""})
```

Daily generations by model:

```promql
sum by (date, model_uuid) (wavespeed_daily_usage{metric="count", model_uuid!=""})
```

Daily costs (total):

```promql
sum by (date) (wavespeed_daily_usage{metric="cost_usd", model_uuid=""})
```

Daily costs by model:

```promql
sum by (date, model_uuid) (wavespeed_daily_usage{metric="cost_usd", model_uuid!=""})
```
