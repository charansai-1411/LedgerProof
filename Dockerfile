# LedgerProof — Cloud Run image.
# A single long-lived FastAPI/uvicorn server (SSE + per-request compute), NOT serverless.
FROM python:3.11-slim

WORKDIR /app

# 1. deps first (better layer caching). Core = PyYAML; API = fastapi/uvicorn/multipart.
#    The Gemini path (google-genai) is imported lazily and is NOT needed to run the demo.
COPY requirements.txt requirements-api.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-api.txt

# 2. app source
COPY . .

# 3. datasets are gitignored (reproducible from a seed, never committed) — generate them at BUILD
#    time so the image is self-contained and cold starts are fast. heldout is the default the
#    dashboard loads; dev/demo/adversarial give the dataset switcher something to switch to.
RUN python -m ledgerproof.generator --config configs/generator_heldout.yaml \
 && python -m ledgerproof.generator --config configs/generator.yaml \
 && python -m ledgerproof.generator --config configs/generator_demo.yaml \
 && python -m ledgerproof.generator --config configs/generator_adversarial.yaml

ENV PORT=8080
EXPOSE 8080

# Cloud Run injects $PORT; sh -c expands it. --factory calls create_app() (defaults to data/heldout).
CMD ["sh", "-c", "exec uvicorn ledgerproof.api.app:create_app --factory --host 0.0.0.0 --port ${PORT:-8080}"]
