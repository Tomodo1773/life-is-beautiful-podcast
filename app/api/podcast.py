import os
import tempfile
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.utils.markdown_processor import split_markdown_by_h2
from app.utils.podcast_generator import PodcastGenerator

router = APIRouter()

processing_jobs = {}

class ProcessingStatus(BaseModel):
    """Model for podcast processing status."""
    job_id: str
    status: str
    progress: float = 0.0
    result_file: Optional[str] = None
    error: Optional[str] = None

def get_gemini_api_key():
    """Get Gemini API key from environment variables."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500, 
            detail="GEMINI_API_KEY environment variable not set"
        )
    return api_key

async def process_podcast_background(
    job_id: str,
    markdown_content: str,
    output_dir: str,
    api_key: str
):
    """
    Process podcast generation in the background.
    
    Args:
        job_id: Unique job identifier
        markdown_content: Markdown content to process
        output_dir: Directory to save output files
        api_key: Gemini API key
    """
    try:
        processing_jobs[job_id] = ProcessingStatus(
            job_id=job_id,
            status="processing",
            progress=0.0
        )
        
        chunks = split_markdown_by_h2(markdown_content)
        
        processing_jobs[job_id].progress = 0.1
        
        generator = PodcastGenerator(api_key=api_key)
        
        result_file = generator.process_markdown_chunks(chunks, output_dir)
        
        if result_file:
            processing_jobs[job_id].status = "completed"
            processing_jobs[job_id].progress = 1.0
            processing_jobs[job_id].result_file = result_file
        else:
            processing_jobs[job_id].status = "failed"
            processing_jobs[job_id].error = "Failed to generate podcast"
            
    except Exception as e:
        processing_jobs[job_id].status = "failed"
        processing_jobs[job_id].error = str(e)

@router.post("/generate-podcast", response_model=ProcessingStatus)
async def generate_podcast(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    api_key: str = Depends(get_gemini_api_key)
):
    """
    Generate a podcast from a markdown file.
    
    Args:
        background_tasks: FastAPI background tasks
        file: Uploaded markdown file
        api_key: Gemini API key
        
    Returns:
        Processing status
    """
    if not file.filename.endswith(('.md', '.markdown')):
        raise HTTPException(
            status_code=400,
            detail="Only markdown files are supported"
        )
    
    content = await file.read()
    markdown_content = content.decode("utf-8")
    
    job_id = f"job_{os.urandom(8).hex()}"
    
    output_dir = os.path.join(tempfile.gettempdir(), job_id)
    os.makedirs(output_dir, exist_ok=True)
    
    background_tasks.add_task(
        process_podcast_background,
        job_id,
        markdown_content,
        output_dir,
        api_key
    )
    
    processing_jobs[job_id] = ProcessingStatus(
        job_id=job_id,
        status="queued",
        progress=0.0
    )
    
    return processing_jobs[job_id]

@router.get("/podcast-status/{job_id}", response_model=ProcessingStatus)
async def get_podcast_status(job_id: str):
    """
    Get the status of a podcast generation job.
    
    Args:
        job_id: Job ID
        
    Returns:
        Processing status
    """
    if job_id not in processing_jobs:
        raise HTTPException(
            status_code=404,
            detail=f"Job {job_id} not found"
        )
    
    return processing_jobs[job_id]

@router.get("/download-podcast/{job_id}")
async def download_podcast(job_id: str):
    """
    Download a generated podcast.
    
    Args:
        job_id: Job ID
        
    Returns:
        Podcast audio file
    """
    if job_id not in processing_jobs:
        raise HTTPException(
            status_code=404,
            detail=f"Job {job_id} not found"
        )
    
    status = processing_jobs[job_id]
    
    if status.status != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Podcast generation not completed. Current status: {status.status}"
        )
    
    if not status.result_file or not os.path.exists(status.result_file):
        raise HTTPException(
            status_code=404,
            detail="Podcast file not found"
        )
    
    return FileResponse(
        status.result_file,
        media_type="audio/mpeg",
        filename="podcast.mp3"
    )
