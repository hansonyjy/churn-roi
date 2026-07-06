"""FastAPI app that serves the static frontend and the committed JSON artifacts.

There is no inference endpoint. The model is trained offline by `python -m src.build`,
which commits scored_customers.json, metrics.json, and shap.json into static/data/.
The browser does all the live EV recompute, so this process only serves files.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Churn ROI", docs_url=None, redoc_url=None)

# scored_customers.json is ~1.3MB of numeric text that compresses to a fraction of
# that, so gzip turns the one heavy download into a fast one on the free tier.
app.add_middleware(GZipMiddleware, minimum_size=1024)

# html=True serves index.html at "/", other paths resolve to files under static/,
# and anything missing returns a 404.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
