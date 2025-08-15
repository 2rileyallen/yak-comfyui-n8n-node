# Phase 2 - The Middleware Service (with Output Formatting)

import asyncio
import json
import uuid
import websockets
import httpx
import random
import os
import base64
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import create_engine, Column, String, Text, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from sqlalchemy.sql import func
import uvicorn

# --- Configuration ---
DB_FILE = "gatekeeper_db.sqlite"
COMFYUI_ADDRESS = "127.0.0.1:8188"
GATEKEEPER_PORT = 8189
CLIENT_ID = str(uuid.uuid4())
JOB_HISTORY_DAYS = 30
COMPLETED_JOB_HISTORY_DAYS = 7

# --- State Tracking ---
last_queue_remaining = None
last_prompt_id = None

# --- Database Setup (SQLAlchemy) ---
Base = declarative_base()
engine = create_engine(f"sqlite:///{DB_FILE}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Job(Base):
    __tablename__ = "jobs"
    job_id = Column(String, primary_key=True, index=True)
    n8n_execution_id = Column(String, index=True)
    comfy_prompt_id = Column(String, index=True, nullable=True)
    status = Column(String, default="pending")
    callback_type = Column(String)
    callback_url = Column(String, nullable=True)
    output_format = Column(String, default="binary")
    result_data = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

Base.metadata.create_all(bind=engine)

# --- WebSocket Connection Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, job_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[job_id] = websocket
        print(f"[WS-CONN] WebSocket connected for job_id: {job_id}")

    def disconnect(self, job_id: str):
        if job_id in self.active_connections:
            del self.active_connections[job_id]
            print(f"[WS-DCONN] WebSocket disconnected for job_id: {job_id}")

    async def send_result(self, job_id: str, data: dict):
        if job_id in self.active_connections:
            websocket = self.active_connections[job_id]
            try:
                print(f"[WS-SEND] Sending result to job {job_id}: {data}")
                await websocket.send_json(data)
            except Exception as e:
                print(f"[ERROR] Failed to send WebSocket message for job {job_id}: {e}")

manager = ConnectionManager()

# --- DB Cleanup Function ---
def cleanup_old_jobs():
    db = SessionLocal()
    try:
        completed_cutoff = datetime.now() - timedelta(days=COMPLETED_JOB_HISTORY_DAYS)
        db.query(Job).filter(Job.status == 'completed', Job.created_at < completed_cutoff).delete()
        all_cutoff = datetime.now() - timedelta(days=JOB_HISTORY_DAYS)
        db.query(Job).filter(Job.created_at < all_cutoff).delete()
        db.commit()
        print("[INFO] Old jobs cleaned up.")
    finally:
        db.close()

# --- Lifespan Event Handler ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[INFO] Gatekeeper starting up.")
    cleanup_old_jobs()
    task = asyncio.create_task(listen_to_comfyui())
    yield
    print("[INFO] Gatekeeper server shutting down.")
    task.cancel()

# --- FastAPI Application ---
app = FastAPI(title="Yak ComfyUI Gatekeeper", lifespan=lifespan)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def randomize_seed(workflow):
    for node in workflow.values():
        if node.get("class_type") == "KSampler":
            node["inputs"]["seed"] = random.randint(0, 9999)
    return workflow

# --- API Endpoints ---
@app.post("/execute")
async def execute_workflow(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    new_job = Job(
        job_id=str(uuid.uuid4()),
        n8n_execution_id=payload['n8n_execution_id'],
        callback_type=payload['callback_type'],
        callback_url=payload.get('callback_url'),
        output_format=payload.get('output_format', 'binary'),
        status="pending_submission"
    )
    db.add(new_job)
    db.commit()

    try:
        randomized_workflow = randomize_seed(payload['workflow_json'])
        comfy_payload = {"prompt": randomized_workflow}
        async with httpx.AsyncClient() as client:
            response = await client.post(f"http://{COMFYUI_ADDRESS}/prompt", json=comfy_payload)
            response.raise_for_status()
            comfy_response = response.json()

        new_job.comfy_prompt_id = comfy_response['prompt_id']
        new_job.status = "queued"
        db.commit()
        db.refresh(new_job)
        print(f"[INFO] Job {new_job.job_id} submitted to ComfyUI. Prompt ID: {new_job.comfy_prompt_id}")
        return {"status": "success", "job_id": new_job.job_id}
    except Exception as e:
        new_job.status = "submission_failed"
        db.commit()
        raise HTTPException(status_code=500, detail=f"Failed to communicate with ComfyUI: {e}")

@app.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    await manager.connect(job_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(job_id)

# --- ComfyUI WebSocket Listener ---
async def listen_to_comfyui():
    global last_queue_remaining, last_prompt_id
    ws_url = f"ws://{COMFYUI_ADDRESS}/ws"
    
    while True:
        try:
            async with websockets.connect(ws_url) as websocket:
                print(f"[INFO] WebSocket connection to ComfyUI established.")
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        print(f"[WS-RECV] {data}")
                        
                        if not isinstance(data, dict):
                            continue

                        # Handle status messages - track queue remaining
                        if data.get('type') == 'status':
                            status_data = data.get('data', {}).get('status', {})
                            exec_info = status_data.get('exec_info', {})
                            current_queue = exec_info.get('queue_remaining')
                            
                            if current_queue is not None:
                                print(f"[QUEUE] Current: {current_queue}, Last: {last_queue_remaining}")
                                
                                # Check if queue decreased (job completed)
                                if last_queue_remaining is not None and current_queue < last_queue_remaining and last_prompt_id:
                                    print(f"[COMPLETED] Job finished! Queue went from {last_queue_remaining} to {current_queue}")
                                    await handle_job_completion(last_prompt_id)
                                
                                last_queue_remaining = current_queue

                        # Handle progress_state messages - track prompt_id
                        elif data.get('type') == 'progress_state':
                            progress_data = data.get('data', {})
                            prompt_id = progress_data.get('prompt_id')
                            if prompt_id:
                                last_prompt_id = prompt_id
                                print(f"[PROMPT-ID] Updated to: {prompt_id}")

                    except Exception as e:
                        print(f"[ERROR] Error processing WebSocket message: {e}")
        except Exception as e:
            print(f"[ERROR] WebSocket listener error: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)

async def handle_job_completion(prompt_id: str):
    """Handle job completion using the prompt_id"""
    db = SessionLocal()
    try:
        # Find the job by prompt_id
        job = db.query(Job).filter(Job.comfy_prompt_id == prompt_id).first()
        if not job or job.status == 'completed':
            print(f"[SKIP] Job not found or already completed for prompt_id: {prompt_id}")
            return

        # Get history data from ComfyUI
        async with httpx.AsyncClient() as client:
            history_response = await client.get(f"http://{COMFYUI_ADDRESS}/history/{prompt_id}")
            history_response.raise_for_status()
            history_data = history_response.json()

        if prompt_id not in history_data:
            print(f"[ERROR] No history found for prompt_id: {prompt_id}")
            return

        output_data = history_data[prompt_id].get('outputs', {})
        
        # Update job status
        job.status = "completed"
        job.result_data = json.dumps(output_data)
        db.commit()
        print(f"[DB] Job {job.job_id} marked as completed.")

        # Format the output
        final_payload = await format_output(job, output_data)

        # Send result
        if job.callback_type == 'websocket':
            await manager.send_result(job.job_id, final_payload)
            print(f"[WS-PUSH] Pushed result for job {job.job_id}.")
        elif job.callback_type == 'webhook' and job.callback_url:
            print(f"[WEBHOOK] Sending result for job {job.job_id} to {job.callback_url}")
            async with httpx.AsyncClient() as client:
                await client.post(job.callback_url, json=final_payload)

    except Exception as e:
        print(f"[ERROR] Error handling job completion for {prompt_id}: {e}")
    finally:
        db.close()

# --- Output Formatting Logic ---
async def format_output(job: Job, output_data: dict) -> dict:
    """Prepares the final payload based on the job's requested output format."""

    # For text format, return the history data
    if job.output_format == 'text':
        return {"format": "text", "data": json.dumps(output_data)}

    # Find all output files
    files = []
    for node_output in output_data.values():
        if 'images' in node_output:
            files.extend([{'filename': img['filename'], 'type': 'image'} for img in node_output['images']])
        if 'videos' in node_output:
            files.extend([{'filename': vid['filename'], 'type': 'video'} for vid in node_output['videos']])
        if 'audio' in node_output:
            files.extend([{'filename': aud['filename'], 'type': 'audio'} for aud in node_output['audio']])

    if not files:
        return {"format": "text", "data": json.dumps(output_data)}

    results = []
    for file_info in files:
        filename = file_info['filename']
        file_type = file_info['type']

        if job.output_format == 'filePath':
            # Construct real filesystem path
            gatekeeper_dir = Path(__file__).parent.absolute()
            file_path = gatekeeper_dir / "ComfyUI" / "output" / filename
            
            results.append({
                "format": "filePath",
                "type": file_type,
                "data": str(file_path),
                "filename": filename
            })
        elif job.output_format == 'binary':
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(f"http://{COMFYUI_ADDRESS}/view?filename={filename}")
                    response.raise_for_status()
                    binary_data = response.content
                    base64_data = base64.b64encode(binary_data).decode('utf-8')

                    # Determine MIME type
                    ext = filename.lower().split('.')[-1]
                    mime_type = "application/octet-stream"
                    if ext in ['png', 'jpg', 'jpeg', 'gif', 'webp']:
                        mime_type = f"image/{ext if ext != 'jpg' else 'jpeg'}"
                    elif ext in ['mp4', 'avi', 'mov', 'webm']:
                        mime_type = f"video/{ext}"
                    elif ext in ['mp3', 'wav', 'ogg', 'flac']:
                        mime_type = f"audio/{ext}"

                    results.append({
                        "format": "binary",
                        "type": file_type,
                        "data": base64_data,
                        "filename": filename,
                        "mime_type": mime_type
                    })
            except Exception as e:
                print(f"[ERROR] Failed to fetch binary data for {filename}: {e}")
                # Fallback to filePath
                gatekeeper_dir = Path(__file__).parent.absolute()
                file_path = gatekeeper_dir / "ComfyUI" / "output" / filename
                results.append({
                    "format": "filePath",
                    "type": file_type,
                    "data": str(file_path),
                    "filename": filename,
                    "error": str(e)
                })

    return results[0] if len(results) == 1 else {"format": "multiple", "results": results}

# --- Main Execution ---
if __name__ == "__main__":
    uvicorn.run("gatekeeper:app", host="0.0.0.0", port=GATEKEEPER_PORT, reload=True)