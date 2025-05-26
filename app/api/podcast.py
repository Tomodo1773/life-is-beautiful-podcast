import asyncio
import logging
import os
import sys
import tempfile
import traceback
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.utils.markdown_processor import split_markdown_advanced
from app.utils.podcast_generator import PodcastGenerator

logger = logging.getLogger("app.api.podcast")

router = APIRouter()


class ProcessingStatus(BaseModel):
    """Model for podcast processing status."""

    job_id: str
    status: str
    progress: float = 0.0
    result_file: Optional[str] = None
    error: Optional[str] = None
    chunk_count: Optional[int] = None  # チャンク数
    script_done: Optional[int] = None  # スクリプト生成済み数
    tts_done: Optional[int] = None  # TTS生成済み数


def get_gemini_api_key():
    """Get Gemini API key from environment variables."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY environment variable not set")
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY environment variable not set")
    logger.info("GEMINI_API_KEY successfully loaded from environment")
    return api_key


def save_status_to_file(job_id: str, status: ProcessingStatus):
    status_file = os.path.join(os.path.dirname(__file__), "../../tmp", f"{job_id}_status.json")
    os.makedirs(os.path.dirname(status_file), exist_ok=True)
    with open(status_file, "w", encoding="utf-8") as f:
        f.write(status.json())


def load_status_from_file(job_id: str) -> Optional[ProcessingStatus]:
    status_file = os.path.join(os.path.dirname(__file__), "../../tmp", f"{job_id}_status.json")
    if not os.path.exists(status_file):
        return None
    with open(status_file, "r", encoding="utf-8") as f:
        data = f.read()
        return ProcessingStatus.parse_raw(data)


async def process_podcast_background(job_id: str, markdown_content: str, output_dir: str, api_key: str):
    """
    Process podcast generation in the background.

    Args:
        job_id: Unique job identifier
        markdown_content: Markdown content to process
        output_dir: Directory to save output files
        api_key: Gemini API key
    """
    try:
        logger.info(f"[Job {job_id}] Podcast generation started")
        chunk_dir = os.path.join("tmp", "chunks")
        chunks = split_markdown_advanced(markdown_content, save_dir=chunk_dir)
        chunk_count = len(chunks)
        status = ProcessingStatus(
            job_id=job_id, status="processing", progress=0.0, chunk_count=chunk_count, script_done=0, tts_done=0
        )
        save_status_to_file(job_id, status)

        generator = PodcastGenerator(api_key=api_key)
        logger.info(f"[Job {job_id}] PodcastGenerator initialized")

        # スクリプト生成
        scripts = []
        for i, chunk in enumerate(chunks):
            script = await asyncio.to_thread(generator.generate_script, chunk)
            scripts.append(script)
            status.script_done = i + 1
            status.progress = 0.1 + 0.3 * (i + 1) / chunk_count
            save_status_to_file(job_id, status)

        # TTS生成
        audio_files = []
        for i, script in enumerate(scripts):
            temp_file = os.path.join("tmp/audio_chunks", f"chunk_{i}")
            audio_file = await asyncio.to_thread(generator.generate_audio, script, temp_file)
            if audio_file:
                audio_files.append(audio_file)
            status.tts_done = i + 1
            status.progress = 0.4 + 0.5 * (i + 1) / chunk_count
            save_status_to_file(job_id, status)

        # 連結
        if audio_files:
            final_podcast = os.path.join("tmp/final_audio", "final_podcast.wav")
            await asyncio.to_thread(generator.concatenate_audio_files, audio_files, final_podcast)
            status.status = "completed"
            status.progress = 1.0
            status.result_file = final_podcast
            save_status_to_file(job_id, status)
            logger.info(f"[Job {job_id}] Podcast generation completed: {final_podcast}")
        else:
            status.status = "failed"
            status.error = "Failed to generate podcast"
            save_status_to_file(job_id, status)
            logger.error(f"[Job {job_id}] Podcast generation failed: No result file")

    except Exception as e:
        tb = traceback.format_exc()
        status = ProcessingStatus(job_id=job_id, status="failed", error=f"{e}\n{tb}")
        save_status_to_file(job_id, status)
        logger.error(f"[Job {job_id}] Podcast生成失敗: {e}\n{tb}")


@router.post("/generate-podcast", response_model=ProcessingStatus)
async def generate_podcast(background_tasks: BackgroundTasks, file: UploadFile, api_key: str = Depends(get_gemini_api_key)):
    """
    Generate a podcast from a markdown file.

    Args:
        background_tasks: FastAPI background tasks
        file: Uploaded markdown file
        api_key: Gemini API key

    Returns:
        Processing status
    """
    if not file.filename.endswith((".md", ".markdown")):
        logger.error(f"File extension not supported: {file.filename}")
        raise HTTPException(status_code=400, detail="Only markdown files are supported")

    content = await file.read()
    markdown_content = content.decode("utf-8")

    job_id = f"job_{os.urandom(8).hex()}"
    logger.info(f"[Job {job_id}] New podcast generation job created")

    output_dir = os.path.join(tempfile.gettempdir(), job_id)
    os.makedirs(output_dir, exist_ok=True)
    logger.info(f"[Job {job_id}] Output directory created: {output_dir}")

    background_tasks.add_task(process_podcast_background, job_id, markdown_content, output_dir, api_key)

    status = ProcessingStatus(job_id=job_id, status="queued", progress=0.0)
    save_status_to_file(job_id, status)
    logger.info(f"[Job {job_id}] Job queued")

    return status


@router.get("/podcast-status/{job_id}", response_model=ProcessingStatus)
async def get_podcast_status(job_id: str):
    """
    Get the status of a podcast generation job.

    Args:
        job_id: Job ID

    Returns:
        Processing status
    """
    status = load_status_from_file(job_id)
    if not status:
        logger.error(f"Job {job_id} not found")
        sys.stdout.flush()
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    logger.info(f"[Job {job_id}] Status checked: {status.status}")
    sys.stdout.flush()
    return status


@router.get("/download-podcast/{job_id}")
async def download_podcast(job_id: str):
    """
    Download a generated podcast.

    Args:
        job_id: Job ID

    Returns:
        Podcast audio file
    """
    status = load_status_from_file(job_id)
    if not status:
        logger.error(f"Job {job_id} not found")
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if status.status != "completed":
        logger.error(f"Podcast generation not completed for job {job_id}. Current status: {status.status}")
        raise HTTPException(status_code=400, detail=f"Podcast generation not completed. Current status: {status.status}")

    if not status.result_file or not os.path.exists(status.result_file):
        logger.error(f"Podcast file not found for job {job_id}")
        raise HTTPException(status_code=404, detail="Podcast file not found")

    logger.info(f"[Job {job_id}] Podcast file download started: {status.result_file}")
    return FileResponse(status.result_file, media_type="audio/mpeg", filename="podcast.mp3")
