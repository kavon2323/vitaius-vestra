# server/api.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os, time, uuid, json, shlex, subprocess

import boto3
from botocore.config import Config as BotoConfig
import redis

BRAND_NAME = os.getenv("BRAND_NAME", "Vitaius")
PRODUCT_NAME = os.getenv("PRODUCT_NAME", "Vestra Forms")

BLENDER_BIN = os.getenv("BLENDER_BIN", "blender")
PROCESS_SCRIPT = os.getenv("PROCESS_SCRIPT", "headless/process_cli.py")

AWS_REGION = os.getenv("AWS_REGION", "us-west-2")
S3_BUCKET = os.getenv("S3_BUCKET")
REDIS_URL = os.getenv("REDIS_URL")

# --- FastAPI ---
app = FastAPI(
    title="Vitaius API",
    description=f"Backend for {PRODUCT_NAME} scanning, mirroring, and fulfillment",
    version="1.0.0",
)

# CORS (allow your app/site)
origins = os.getenv("ALLOWED_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if origins == "*" else [o.strip() for o in origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- AWS S3 client ---
if not S3_BUCKET:
    print("WARNING: S3_BUCKET not set; /upload-url will fail until configured.")
s3 = boto3.client(
    "s3",
    region_name=AWS_REGION,
    config=BotoConfig(s3={"addressing_style": "virtual"})
)

# --- Redis client ---
r = redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None
if not r:
    print("WARNING: REDIS_URL not set; job queue endpoints will fail until configured.")

# Simple job key helpers
def job_key(job_id: str) -> str:
    return f"vestra:job:{job_id}"

JOBS_QUEUE = "vestra:jobs"  # a simple Redis list

# ---------- MODELS ----------
class UploadURLRequest(BaseModel):
    filename: str             # e.g., scan_123.stl
    content_type: str = "application/octet-stream"  # mobile may send this
    folder: str = "scans"     # default S3 prefix
    expires_sec: int = 3600

class UploadURLResponse(BaseModel):
    url: str                  # presigned URL
    method: str               # PUT
    headers: dict             # required headers (e.g., Content-Type)
    s3_key: str               # s3 object key you should store

class NewJobRequest(BaseModel):
    s3_key: str               # where the input scan lives
    axis: str = "X"
    base_offset_mm: float = 2.0
    mold_padding_mm: float = 10.0

class JobStatusResponse(BaseModel):
    id: str
    status: str               # queued | processing | done | failed
    created_at: float
    updated_at: float
    input_key: str | None = None
    out_prosthetic_key: str | None = None
    out_mold_key: str | None = None
    error: str | None = None

# ---------- ROUTES ----------
@app.get("/healthz")
def healthz():
    return {"ok": True, "brand": BRAND_NAME, "product": PRODUCT_NAME}

# Dev helper (local only)
class LocalRunRequest(BaseModel):
    input: str
    chest_wall: str | None = None
    axis: str = "X"
    base_offset_mm: float = 2.0
    mold_padding_mm: float = 10.0
    out_prosthetic: str | None = None
    out_mold: str | None = None

@app.post("/run-local")
def run_local(req: LocalRunRequest):
    if not os.path.isfile(req.input):
        raise HTTPException(400, f"Input not found: {req.input}")

    cmd = [
        BLENDER_BIN, "-b", "-P", PROCESS_SCRIPT, "--",
        "--input", req.input,
        "--axis", req.axis,
        "--base_offset_mm", str(req.base_offset_mm),
        "--mold_padding_mm", str(req.mold_padding_mm),
    ]
    if req.chest_wall:
        cmd += ["--chest_wall", req.chest_wall]
    if req.out_prosthetic:
        cmd += ["--out_prosthetic", req.out_prosthetic]
    if req.out_mold:
        cmd += ["--out_mold", req.out_mold]

    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        return {"ok": True, "log": out}
    except subprocess.CalledProcessError as e:
        raise HTTPException(500, f"Blender failed:\n{e.output}")

# --- PHASE 1 ENDPOINTS ---

@app.post("/upload-url", response_model=UploadURLResponse)
def upload_url(req: UploadURLRequest):
    """
    Returns a presigned S3 PUT URL so the app can upload directly to S3.
    """
    if not S3_BUCKET:
        raise HTTPException(500, "S3 not configured")

    # Make a namespaced key: scans/<uuid>_<filename>
    uid = uuid.uuid4().hex
    key = f"{req.folder}/{uid}_{req.filename}"

    # Generate presigned PUT URL
    try:
        url = s3.generate_presigned_url(
            ClientMethod="put_object",
            Params={
                "Bucket": S3_BUCKET,
                "Key": key,
                "ContentType": req.content_type,
            },
            ExpiresIn=req.expires_sec,
        )
    except Exception as e:
        raise HTTPException(500, f"Failed to presign: {e}")

    return UploadURLResponse(
        url=url,
        method="PUT",
        headers={"Content-Type": req.content_type},
        s3_key=key,
    )

@app.post("/jobs/new")
def jobs_new(req: NewJobRequest):
    """
    Create a job: references the uploaded scan in S3 and desired options.
    Enqueues job ID on a Redis list.
    """
    if not r:
        raise HTTPException(500, "Redis not configured")

    job_id = uuid.uuid4().hex
    now = time.time()
    job = {
        "id": job_id,
        "status": "queued",
        "created_at": now,
        "updated_at": now,
        "input_key": req.s3_key,
        "axis": req.axis,
        "base_offset_mm": req.base_offset_mm,
        "mold_padding_mm": req.mold_padding_mm,
        "out_prosthetic_key": None,
        "out_mold_key": None,
        "error": None,
    }

    # Store job and enqueue ID
    r.hset(job_key(job_id), mapping=job)
    r.lpush(JOBS_QUEUE, job_id)
    return {"id": job_id, "status": "queued"}

@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
def jobs_status(job_id: str):
    if not r:
        raise HTTPException(500, "Redis not configured")
    data = r.hgetall(job_key(job_id))
    if not data:
        raise HTTPException(404, "Job not found")
    # Cast numeric fields
    for f in ("created_at", "updated_at", "base_offset_mm", "mold_padding_mm"):
        if f in data and data[f] is not None:
            try:
                data[f] = float(data[f])
            except Exception:
                pass
    return data
