# Cloud Cost Intelligence

Cloud Cost Intelligence is a real cloud FinOps service scaffold that can ingest live AWS and GCP billing/resource telemetry, detect cost anomalies with machine learning, and execute selected optimizations through provider APIs.

## What it does

- Pulls live AWS daily spend from Cost Explorer and EC2 resource state from EC2 and CloudWatch.
- Pulls live GCP billing data from a BigQuery billing export and resource telemetry from Cloud Monitoring and Compute Engine.
- Detects genuine anomalies with `IsolationForest` over recent service-level spend history.
- Generates actionable recommendations for idle EC2 instances, unattached EBS volumes, and idle GCE instances.
- Exposes a FastAPI control plane for syncing, reviewing anomalies, and executing optimizations.
- Serves a browser dashboard at `/` for metrics, anomalies, recommendations, and execution results.
- Includes session-based login and role-based access control for dashboard/API access.
- Schedules recurring ingestion and analysis with APScheduler.

## Architecture

- `app/connectors/aws/client.py`: AWS live billing/resource ingestion and remediation actions.
- `app/connectors/gcp/client.py`: GCP billing export ingestion, resource discovery, and remediation actions.
- `app/services/anomaly_detection.py`: ML-based anomaly detection pipeline.
- `app/services/recommendations.py`: Optimization recommendation generation.
- `app/services/optimization.py`: Safe execution layer for cloud API actions.
- `app/api/routes.py`: Control plane API.

## Local setup

1. Create a virtual environment and install dependencies.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .[dev]
```

2. Copy `.env.example` to `.env` and fill in your cloud settings.

```powershell
Copy-Item .env.example .env
```

The default database should live outside OneDrive-backed folders on Windows. A safe example path is already provided in `.env.example`, and the app now falls back to a temp-directory SQLite database when `DATABASE_URL` is not set.

3. Run the API.

```powershell
uvicorn app.main:app --reload
```

4. Sign in at `/auth/login` with the bootstrap admin account from your `.env`.

Roles:

- `viewer`: read-only dashboard and API access
- `operator`: can run syncs and optimization actions
- `admin`: full operator access plus user management

## Required cloud setup

### AWS

- Configure credentials that allow:
  - `ce:GetCostAndUsage`
  - `ec2:DescribeInstances`
  - `ec2:DescribeVolumes`
  - `cloudwatch:GetMetricStatistics`
  - `ec2:StopInstances`
  - `ec2:DeleteVolume`
- Set `AWS_ENABLED=true`, `AWS_REGION`, and optionally `AWS_ACCOUNT_ID`.

### GCP

- Enable billing export to BigQuery for the target billing account.
- Set `GCP_PROJECT_ID` and `GCP_BILLING_EXPORT_TABLE` using the fully-qualified table name, for example:
  - `my-project.billing_export.gcp_billing_export_v1_123ABC_456DEF_789GHI`
- Provide credentials with access to:
  - BigQuery read on the billing export dataset
  - Cloud Monitoring read
  - Compute Engine instance list/stop
- Set `GCP_ENABLED=true`.

## Safety model

- `OPTIMIZATION_DRY_RUN=true` is the default so recommendations are generated without mutating cloud resources.
- Use `POST /optimize` with `auto_approve=true` to mark recommendations approved.
- Use `POST /optimize` with `force_execute=true` only after validating permissions and expected blast radius.

## API

- `GET /health`
- `GET /`
- `GET /auth/login`
- `POST /auth/login`
- `POST /auth/logout`
- `GET /auth/me`
- `GET /auth/users`
- `POST /auth/users`
- `PATCH /auth/users/{user_id}`
- `GET /summary`
- `POST /sync`
- `GET /anomalies`
- `GET /recommendations`
- `POST /optimize`

Example optimization request:

```json
{
  "recommendation_ids": [1, 2],
  "auto_approve": true,
  "force_execute": false
}
```

## Tests

```powershell
pytest
```

## Notes on “real” connectivity

This project is wired to real AWS and GCP APIs, but I cannot activate the live integrations from this environment because no cloud credentials or network access were provided in the workspace. Once you add credentials and the GCP billing export table, the `/sync` and `/optimize` flows are ready to operate against actual accounts.
