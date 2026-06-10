# PDF Extractor (POC)

Converts hospital health-checkup brochure PDFs into the standard
"New Package(s) Template" CSV format using an LLM via OpenRouter — with a
**human-in-the-loop review step** before the CSV is finalized.

## How it works

1. Upload a brochure PDF (API or web UI).
2. Text is extracted with PyMuPDF; scanned PDFs automatically fall back to
   sending page images to a vision model.
3. An LLM (via OpenRouter, structured JSON output) extracts every package
   into the template schema, with a per-package confidence rating and
   review notes for anything ambiguous.
4. A human reviews the extraction side-by-side with the original PDF,
   edits fields, and approves.
5. The final template CSV is downloadable only after approval
   (draft export available before).

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then put your real OPENROUTER_API_KEY in .env
uvicorn app.main:app --reload
```

Open http://localhost:8000 and drop in a brochure PDF.

## API (pluggable into any application)

| Method | Path | Description |
| --- | --- | --- |
| POST | `/api/jobs` | Multipart PDF upload, runs extraction, returns job with packages |
| GET | `/api/jobs` | List all jobs with statuses |
| GET | `/api/jobs/{id}` | Job detail (packages, status, meta) |
| GET | `/api/jobs/{id}/pdf` | Original PDF |
| PUT | `/api/jobs/{id}/packages` | Save reviewer edits |
| POST | `/api/jobs/{id}/approve` | Mark job approved |
| GET | `/api/jobs/{id}/csv` | Template CSV (`?draft=1` before approval) |
| GET | `/health` | Health check |

Job statuses: `processing` → `needs_review` → `approved` (or `failed`).

Example:

```bash
curl -F "file=@brochure.pdf" http://localhost:8000/api/jobs
curl http://localhost:8000/api/jobs/<id>/csv?draft=1
```

## Configuration

| Env var | Default | Description |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | — | Required. https://openrouter.ai/keys |
| `OPENROUTER_MODEL` | `google/gemini-2.5-flash` | Any vision-capable OpenRouter model |
| `DATA_DIR` | `./data` | Where the SQLite job store lives |
| `ACCESS_USERNAME` | — | HTTP Basic Auth username (enable auth when set with password) |
| `ACCESS_PASSWORD` | — | HTTP Basic Auth password |
| `DISABLE_AUTH` | — | Set `true` to skip auth (local dev only) |

## Access control

When `ACCESS_USERNAME` and `ACCESS_PASSWORD` are set, the browser prompts for
credentials before any page or API call. `/health` stays public for hosting
health checks.

```bash
curl -u demo:your-password -F "file=@brochure.pdf" https://your-app/api/jobs
```

On Railway, add `ACCESS_USERNAME` and `ACCESS_PASSWORD` as service variables.
Do **not** set `DISABLE_AUTH` in production.

## Deploy (Render / Railway / Fly.io)

A `Dockerfile` is included:

```bash
docker build -t package-extractor .
docker run -p 8000:8000 \
  -e OPENROUTER_API_KEY=sk-or-... \
  -e ACCESS_USERNAME=demo \
  -e ACCESS_PASSWORD=your-password \
  package-extractor
```

On any container host: deploy the Dockerfile, set `OPENROUTER_API_KEY`,
and mount a volume at `/srv/data` so jobs survive restarts.

### Railway checklist

| Setting | Value |
| --- | --- |
| Volume mount | `/srv/data` |
| `DATA_DIR` | `/srv/data` |
| `OPENROUTER_API_KEY` | your key |
| `ACCESS_USERNAME` / `ACCESS_PASSWORD` | demo credentials |
| Health check path | `/health` |
| Port | **Do not set `PORT` manually** — Railway injects it; the Dockerfile reads `${PORT}` |

If health checks fail with "service unavailable", the app was almost certainly
listening on the wrong port (fixed in Dockerfile via `${PORT:-8000}`).
Redeploy after pulling the latest code.
