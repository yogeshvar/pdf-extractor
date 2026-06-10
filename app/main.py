"""ArogyaNow Package Extractor — PDF brochures to package-template CSV,
with a human-in-the-loop review step."""

import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .auth import BasicAuthMiddleware, log_auth_status
from .csv_writer import packages_to_csv
from .extractor import ExtractionError, extract_packages
from .schema import Package
from .store import JobStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="ArogyaNow Package Extractor", version="0.1.0")
app.add_middleware(BasicAuthMiddleware)
store = JobStore()


@app.on_event("startup")
async def startup():
    log_auth_status()

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


class PackagesUpdate(BaseModel):
    packages: list[Package]


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/jobs")
async def create_job(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload a PDF file")
    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(400, "Empty file")

    job_id = store.create(file.filename, pdf_bytes)
    try:
        result, meta = await extract_packages(pdf_bytes)
    except ExtractionError as e:
        store.set_failed(job_id, str(e))
        raise HTTPException(502, f"Extraction failed: {e}")
    except Exception as e:  # surface unexpected errors on the job too
        logger.exception("extraction crashed")
        store.set_failed(job_id, str(e))
        raise HTTPException(500, f"Extraction failed: {e}")

    packages = [p.model_dump() for p in result.packages]
    store.set_result(job_id, packages, meta)
    return store.get(job_id)


@app.get("/api/jobs")
async def list_jobs():
    return {"jobs": store.list()}


def _get_job_or_404(job_id: str) -> dict:
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    return _get_job_or_404(job_id)


@app.get("/api/jobs/{job_id}/pdf")
async def get_job_pdf(job_id: str):
    pdf = store.get_pdf(job_id)
    if pdf is None:
        raise HTTPException(404, "Job not found")
    return Response(content=pdf, media_type="application/pdf")


@app.put("/api/jobs/{job_id}/packages")
async def update_packages(job_id: str, body: PackagesUpdate):
    job = _get_job_or_404(job_id)
    if job["status"] not in ("needs_review", "approved"):
        raise HTTPException(409, f"Job is in status '{job['status']}', cannot edit")
    store.update_packages(job_id, [p.model_dump() for p in body.packages])
    return store.get(job_id)


@app.post("/api/jobs/{job_id}/approve")
async def approve_job(job_id: str):
    job = _get_job_or_404(job_id)
    if job["status"] != "needs_review":
        raise HTTPException(409, f"Job is in status '{job['status']}', cannot approve")
    store.approve(job_id)
    return store.get(job_id)


@app.get("/api/jobs/{job_id}/csv")
async def get_job_csv(job_id: str, draft: bool = False):
    job = _get_job_or_404(job_id)
    if job["status"] != "approved" and not draft:
        raise HTTPException(
            409, "Job is not approved yet. Pass ?draft=1 for a draft export."
        )
    csv_text = packages_to_csv(job["packages"])
    suffix = "" if job["status"] == "approved" else "-draft"
    filename = f"packages-{job_id}{suffix}.csv"
    return PlainTextResponse(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/review/{job_id}")
async def review_page(job_id: str):
    return FileResponse(STATIC_DIR / "review.html")


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
