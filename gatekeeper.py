# gatekeeper.py
# Phase 2 - The Middleware Service

import asyncio
import json
import uuid
import websockets
import httpx # Re-enabled httpx for async requests
import random
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, HTTPException, Depends
from sqlalchemy import create_engine, Column, String, Text, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from sqlalchemy.sql import func
import uvicorn

# --- Configuration ---
DB_FILE = "gatekeeper_db.sqlite"
COMFYUI_ADDRESS = "127.0.0.1:8188"
GATEKEEPER_PORT = 8189
CLIENT_ID = str(uuid.uuid4())
JOB_HISTORY_DAYS = 30 # Delete any job older than this
COMPLETED_JOB_HISTORY_DAYS = 7 # Delete completed jobs older than this

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
    result_data = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

Base.metadata.create_all(bind=engine)

# --- DB Cleanup Function ---
def cleanup_old_jobs():
    """Deletes old job records from the database on startup."""
    db = SessionLocal()
    try:
        # Delete completed jobs older than COMPLETED_JOB_HISTORY_DAYS
        completed_cutoff = datetime.now() - timedelta(days=COMPLETED_JOB_HISTORY_DAYS)
        num_deleted_completed = db.query(Job).filter(
            Job.status == 'completed',
            Job.created_at < completed_cutoff
        ).delete(synchronize_session=False)

        # Delete ANY job older than JOB_HISTORY_DAYS
        all_cutoff = datetime.now() - timedelta(days=JOB_HISTORY_DAYS)
        num_deleted_all = db.query(Job).filter(
            Job.created_at < all_cutoff
        ).delete(synchronize_session=False)

        db.commit()
        if num_deleted_completed > 0:
            print(f"[DB Cleanup] Deleted {num_deleted_completed} completed jobs older than {COMPLETED_JOB_HISTORY_DAYS} days.")
        if num_deleted_all > 0:
            print(f"[DB Cleanup] Deleted {num_deleted_all} jobs older than {JOB_HISTORY_DAYS} days.")
    except Exception as e:
        print(f"[ERROR] Database cleanup failed: {e}")
        db.rollback()
    finally:
        db.close()

# --- Lifespan Event Handler ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[INFO] Gatekeeper starting up with Client ID: {CLIENT_ID}")
    
    # Run cleanup and crash recovery on startup
    cleanup_old_jobs()
    # TODO: Add crash recovery logic here.
    
    # Re-enable the WebSocket listener
    task = asyncio.create_task(listen_to_comfyui())
    print("[INFO] ComfyUI WebSocket listener started in the background.")
    
    yield
    
    print("[INFO] Gatekeeper server shutting down.")
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        print("[INFO] WebSocket listener task cancelled successfully.")

# --- FastAPI Application ---
app = FastAPI(title="Yak ComfyUI Gatekeeper", lifespan=lifespan)

# --- Helper function to get a database session ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Helper function to randomize seed ---
def randomize_seed(workflow):
    """Finds all KSampler nodes and gives them a random seed."""
    for node in workflow.values():
        if node.get("class_type") == "KSampler":
            node["inputs"]["seed"] = random.randint(0, 999999999999999)
            print(f"[INFO] Randomized seed to {node['inputs']['seed']}")
    return workflow

# --- API Endpoints ---
@app.post("/execute")
async def execute_workflow(request: Request, db: Session = Depends(get_db)):
    print("[INFO] Received new job request from n8n.")
    
    try:
        payload = await request.json()
        if not all(k in payload for k in ['n8n_execution_id', 'callback_type', 'workflow_json']):
            raise HTTPException(status_code=400, detail="Missing required fields.")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON.")

    new_job = Job(
        job_id=str(uuid.uuid4()),
        n8n_execution_id=payload['n8n_execution_id'],
        callback_type=payload['callback_type'],
        callback_url=payload.get('callback_url'),
        status="pending_submission"
    )
    db.add(new_job)
    db.commit()
    db.refresh(new_job)
    print(f"[INFO] Job {new_job.job_id} saved to database.")

    try:
        # Randomize the seed before submitting
        randomized_workflow = randomize_seed(payload['workflow_json'])
        comfy_payload = { "prompt": randomized_workflow }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(f"http://{COMFYUI_ADDRESS}/prompt", json=comfy_payload)
            response.raise_for_status() 
        
        comfy_response = response.json()
        if 'prompt_id' not in comfy_response:
            raise ValueError("ComfyUI API response did not include a prompt_id.")

        new_job.comfy_prompt_id = comfy_response['prompt_id']
        new_job.status = "queued"
        db.commit()
        print(f"[INFO] Job {new_job.job_id} submitted to ComfyUI. Prompt ID: {new_job.comfy_prompt_id}")

    except (httpx.RequestError, ValueError) as e:
        print(f"[ERROR] Failed to submit job to ComfyUI: {e}")
        new_job.status = "submission_failed"
        db.commit()
        raise HTTPException(status_code=500, detail=f"Failed to communicate with ComfyUI: {e}")

    return {"status": "success", "message": "Job submitted to ComfyUI.", "job_id": new_job.job_id}


@app.get("/status/{job_id}")
async def get_job_status(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"job_id": job.job_id, "status": job.status, "result": job.result_data}


# --- ComfyUI WebSocket Listener ---
async def listen_to_comfyui():
    ws_url = f"ws://{COMFYUI_ADDRESS}/ws"
    
    while True:
        try:
            async with websockets.connect(ws_url) as websocket:
                print(f"[INFO] WebSocket connection to ComfyUI established at {ws_url}")
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        if not isinstance(data, dict): continue

                        if data.get('type') == 'executing' and 'prompt_id' in data.get('data', {}):
                            prompt_id = data['data']['prompt_id']
                            print(f"[INFO] Job with prompt_id {prompt_id} is now executing.")
                            db = SessionLocal()
                            try:
                                job = db.query(Job).filter(Job.comfy_prompt_id == prompt_id).first()
                                if job and job.status != 'running':
                                    job.status = "running"
                                    db.commit()
                                    print(f"[DB] Updated job {job.job_id} to running.")
                            finally:
                                db.close()

                        elif data.get('type') == 'executed' and 'prompt_id' in data.get('data', {}):
                            prompt_id = data['data']['prompt_id']
                            output_data = data['data'].get('output', {})
                            print(f"[SUCCESS] Job with prompt_id {prompt_id} has finished.")
                            
                            db = SessionLocal()
                            try:
                                job = db.query(Job).filter(Job.comfy_prompt_id == prompt_id).first()
                                if job:
                                    job.status = "completed"
                                    job.result_data = json.dumps(output_data)
                                    db.commit()
                                    print(f"[DB] Updated job {job.job_id} to completed and saved output.")
                                    # TODO: Trigger the actual callback (webhook or websocket)
                            finally:
                                db.close()

                    except Exception as e:
                        print(f"[ERROR] Error processing WebSocket message: {e}")

        except Exception as e:
            print(f"[ERROR] An unexpected error occurred in the WebSocket listener: {e}. Reconnecting in 5 seconds...")
            await asyncio.sleep(5)


# --- Main Execution ---
if __name__ == "__main__":
    print(f"[INFO] Starting Gatekeeper server on port {GATEKEEPER_PORT}")
    uvicorn.run("gatekeeper:app", host="0.0.0.0", port=GATEKEEPER_PORT, reload=True)
