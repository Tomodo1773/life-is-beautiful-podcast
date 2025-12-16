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
from app.utils.podcast_generator import PodcastGenerator, RetryConfig

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

        os.makedirs(os.path.join("tmp", "audio_chunks"), exist_ok=True)
        os.makedirs(os.path.join("tmp", "final_audio"), exist_ok=True)
        os.makedirs(os.path.join("tmp", "scripts"), exist_ok=True)

        status = ProcessingStatus(
            job_id=job_id, status="processing", progress=0.0, chunk_count=chunk_count, script_done=0, tts_done=0
        )
        save_status_to_file(job_id, status)

        generator = PodcastGenerator(api_key=api_key)
        logger.info(f"[Job {job_id}] PodcastGenerator initialized")

        script_concurrency = int(os.environ.get("SCRIPT_CONCURRENCY", "20"))
        tts_concurrency = int(os.environ.get("TTS_CONCURRENCY", "5"))
        max_retries = int(os.environ.get("GEMINI_MAX_RETRIES", "8"))
        retry_max_seconds = float(os.environ.get("GEMINI_RETRY_MAX_SECONDS", "60"))

        retry = RetryConfig(max_retries=max_retries, max_delay_seconds=retry_max_seconds)

        script_sem = asyncio.Semaphore(max(1, min(script_concurrency, chunk_count or 1)))
        tts_sem = asyncio.Semaphore(max(1, min(tts_concurrency, chunk_count or 1)))
        status_lock = asyncio.Lock()

        def recompute_progress() -> float:
            if not chunk_count:
                return 0.0
            # 0.0-0.9: script(0.3) + tts(0.6) + base(0.0). 連結で1.0にする。
            return min(0.9, 0.3 * (status.script_done / chunk_count) + 0.6 * (status.tts_done / chunk_count))

        async def mark_script_done() -> None:
            async with status_lock:
                status.script_done += 1
                status.progress = recompute_progress()
                save_status_to_file(job_id, status)

        async def mark_tts_done() -> None:
            async with status_lock:
                status.tts_done += 1
                status.progress = recompute_progress()
                save_status_to_file(job_id, status)

        async def process_one_chunk(i: int, chunk) -> tuple[int, str]:
            async with script_sem:
                script = await generator.generate_script_async(chunk, retry=retry)
            await mark_script_done()

            async with tts_sem:
                temp_file = os.path.join("tmp", "audio_chunks", f"chunk_{i}")
                audio_file = await generator.generate_audio_async(script, temp_file, retry=retry)
            await mark_tts_done()

            if not audio_file:
                raise RuntimeError(f"Audio generation returned empty result for chunk {i}")
            return i, audio_file

        indexed_files: list[tuple[int, str]] = []

        async def run_and_collect(i: int, chunk) -> None:
            indexed_files.append(await process_one_chunk(i, chunk))

        async with asyncio.TaskGroup() as tg:
            for i, chunk in enumerate(chunks):
                tg.create_task(run_and_collect(i, chunk))

        indexed_files.sort(key=lambda x: x[0])
        audio_files = [f for _, f in indexed_files]

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
