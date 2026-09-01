# Deploying LedgerProof to Google Cloud Run

LedgerProof is a single long-lived FastAPI server (SSE + per-request compute), so it runs as a
container on **Cloud Run** — not as serverless functions. Cloud Build builds the `Dockerfile` from
source; no local Docker needed. The demo datasets are generated **at image build time** (they are
gitignored, reproducible from a seed), so the container is self-contained.

## Prerequisites (one time)

```bash
gcloud auth login
gcloud config set project <PROJECT_ID>          # e.g. ledgerproof-506605
gcloud services enable run.googleapis.com cloudbuild.googleapis.com
```

You need a project with **billing enabled** (Cloud Build + Cloud Run). The free tier covers a demo.

## Deploy (one command, from the repo root)

```bash
gcloud run deploy ledgerproof \
  --source . \
  --region asia-south1 \
  --allow-unauthenticated \
  --memory 1Gi --cpu 1 --timeout 300 --port 8080
```

- `--source .` → Cloud Build builds the `Dockerfile` and pushes the image, then deploys it.
- `--allow-unauthenticated` → public demo URL (drop it to require auth).
- `asia-south1` is Mumbai; change the region if you prefer.
- `--memory 1Gi` gives the pipeline headroom for the heavier evidence endpoints
  (`/api/architectures`, `/api/faults`, `/api/necessity`) on the 5,000-payment datasets.

On success gcloud prints the service URL, e.g. `https://ledgerproof-xxxxx-el.a.run.app`. Open it —
the dashboard loads on the held-out dataset.

## Optional: enable the live Gemini path

The dashboard runs fully on the deterministic (heuristic) agent by default. To enable the **Gemini
(Vertex AI)** model in the Investigation Workspace's live trace:

```bash
# 1. let the Cloud Run runtime service account call Vertex AI
PROJECT=<PROJECT_ID>
SA=$(gcloud run services describe ledgerproof --region asia-south1 --format='value(spec.template.spec.serviceAccountName)')
SA=${SA:-$(gcloud projects describe $PROJECT --format='value(projectNumber)')-compute@developer.gserviceaccount.com}
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:$SA" --role="roles/aiplatform.user"
gcloud services enable aiplatform.googleapis.com

# 2. point the app at your project/region and redeploy the env
gcloud run services update ledgerproof --region asia-south1 \
  --set-env-vars GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_CLOUD_LOCATION=us-central1
```

The base image does **not** bundle `google-genai` (it is imported lazily). If you want the Gemini
path in-image, add `-r requirements-agent.txt` to the `pip install` line in the `Dockerfile`.

## Redeploying

Push changes and re-run the same `gcloud run deploy` command — it rebuilds and rolls out a new
revision with zero-downtime traffic migration.
