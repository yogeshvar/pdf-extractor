"""PDF content extraction + OpenRouter LLM call producing structured packages."""

import base64
import json
import logging
import os

import fitz  # PyMuPDF
import httpx

from .schema import ExtractionResult

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "google/gemini-2.5-flash"

# Below this many characters per page on average, treat the PDF as scanned
# and fall back to sending page images to a vision model.
MIN_CHARS_PER_PAGE = 120

SYSTEM_PROMPT = """\
You are a meticulous data-extraction agent for a healthcare marketplace.
You receive the content of a hospital health-checkup brochure (as text or page images)
and must extract every health checkup package into a strict JSON structure.

Rules:
- Extract EVERY package in the brochure. Do not skip or merge packages.
- If a package has separate Male and Female variants (different tests or prices),
  output one package per gender with '(Male)' / '(Female)' appended to the name
  and the gender field set. If a single package merely marks some tests as
  "only for male/female", keep it as one unisex package and keep those annotations.
- Categorize included items carefully:
  * blood_tests: lab tests done on blood (CBC/haemogram, ESR, blood grouping,
    sugar, HbA1c, urea, creatinine, lipid/liver/kidney/thyroid profiles, vitamins,
    electrolytes, serology like HIV/HBsAg, tumor markers like PSA/CEA/CA-125...)
  * other_tests: non-blood diagnostics (urine/stool analysis, ECG, TMT, PFT,
    audiometry, pap smear, endoscopy, foot exam...)
  * radiology: imaging (X-ray, ultrasound/USG, mammogram, ECHO, BMD/DEXA, CT, MRI...)
  * consultations: doctor consultations, physical examinations, counselling
    (diet counselling, physiotherapy...)
- Keep test names as printed (fix only obvious OCR/typo artifacts).
- price: keep the currency symbol exactly as printed (e.g. '₹5,999/-' -> '₹5,999').
- Brochure-level preparation guidelines (fasting, what to bring, appointment rules)
  apply to EVERY package: write a condensed version into each package's
  preparation_guidelines, and put contraindication-type lines (pregnancy notice,
  extra charges) into important_notes.
- concierge_services: complementary items like breakfast, meals, room stay.
- hospital_name: set on every package and at the top level.
- PDF text extraction often jumbles multi-column layouts. Reconstruct the most
  plausible grouping; when unsure, set confidence to 'medium' or 'low' and explain
  in review_notes what a human should double-check.
- Output ONLY JSON matching the provided schema. No markdown, no commentary.
"""


class ExtractionError(Exception):
    pass


def read_pdf(pdf_bytes: bytes) -> tuple[str, int, str]:
    """Return (text, page_count, mode). mode is 'text' or 'vision'."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = doc.page_count
    text_parts = []
    for i, page in enumerate(doc):
        text_parts.append(f"--- page {i + 1} of {pages} ---\n{page.get_text('text')}")
    text = "\n".join(text_parts)
    mode = "text" if len(text) >= MIN_CHARS_PER_PAGE * max(pages, 1) else "vision"
    doc.close()
    return text, pages, mode


def render_pages(pdf_bytes: bytes, max_pages: int = 40) -> list[str]:
    """Render pages to base64 PNG data URLs for vision models."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    urls = []
    for page in list(doc)[:max_pages]:
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        b64 = base64.b64encode(pix.tobytes("png")).decode()
        urls.append(f"data:image/png;base64,{b64}")
    doc.close()
    return urls


def _json_schema() -> dict:
    schema = ExtractionResult.model_json_schema()
    return {
        "type": "json_schema",
        "json_schema": {"name": "extraction_result", "strict": True, "schema": schema},
    }


def _parse_content(content: str) -> ExtractionResult:
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:]
    return ExtractionResult.model_validate(json.loads(content))


async def extract_packages(pdf_bytes: bytes) -> tuple[ExtractionResult, dict]:
    """Run the full pipeline: read PDF, call OpenRouter, validate result."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ExtractionError("OPENROUTER_API_KEY is not set")
    model = os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)

    text, pages, mode = read_pdf(pdf_bytes)

    if mode == "text":
        user_content: list[dict] | str = (
            "Extract all health checkup packages from this brochure text:\n\n" + text
        )
    else:
        images = render_pages(pdf_bytes)
        user_content = [
            {
                "type": "text",
                "text": "Extract all health checkup packages from these brochure page images:",
            },
            *[{"type": "image_url", "image_url": {"url": u}} for u in images],
        ]

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "response_format": _json_schema(),
        "temperature": 0.1,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://arogyanow.local",
        "X-Title": "ArogyaNow Package Extractor",
    }

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(300, connect=15),
        trust_env=False,  # avoid system proxy blocking OpenRouter
    ) as client:
        resp = await client.post(OPENROUTER_URL, json=payload, headers=headers)
        if resp.status_code != 200:
            raise ExtractionError(f"OpenRouter error {resp.status_code}: {resp.text[:500]}")
        data = resp.json()

    try:
        content = data["choices"][0]["message"]["content"]
        result = _parse_content(content)
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        raise ExtractionError(f"Could not parse model response: {e}") from e

    # Backfill hospital name on packages that missed it.
    for pkg in result.packages:
        if not pkg.hospital_name:
            pkg.hospital_name = result.hospital_name

    meta = {
        "model": model,
        "pages": pages,
        "mode": mode,
        "usage": data.get("usage", {}),
    }
    return result, meta
