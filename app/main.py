import logging

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.podcast import router as podcast_router

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Life is Beautiful Podcast Generator",
    description="Generate podcasts from Life is Beautiful newsletter markdown content",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods
    allow_headers=["*"],  # Allow all headers
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")

app.include_router(podcast_router, prefix="/api", tags=["podcast"])


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Render the home page."""
    logger.info("Rendering home page")
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    logger.info("Health check endpoint called")
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    logger.info("Starting FastAPI app with uvicorn")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
