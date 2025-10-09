import os, uuid, zipfile, io
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.responses import JSONResponse
import boto3, redis
from rq import Queue

load_dotenv()
app = FastAPI()

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_methods=["*"], 
    allow_headers=["*"]
)

s3 = boto3.client("s3", region_name=os.getenv("AWS_REGION"))
BUCKET = os.getenv("S3_BUCKET")
IN_PREFIX = os.getenv("S3_INPUT_PREFIX","inputs/")
OUT_PREFIX = os.getenv("S3_OUTPUT_PREFIX","outputs/")
r = redis.from_url(os.getenv("REDIS_URL"))
q = Queue(connection=r)

@app.post("/upload")
async def upload(zipfile_in: UploadFile):
    case_id = f"case_{uuid.uuid4().hex[:8]}"
    data = await zipfile_in.read()

    # quick manifest check
    zf = zipfile.ZipFile(io.BytesIO(data))
    if "manifest.json" not in zf.namelist():
        raise HTTPException(400, "manifest.json missing")

    key = f"{IN_PREFIX}{case_id}.zip"
    s3.put_object(Bucket=BUCKET, Key=key, Body=data)

    # enqueue job (worker pulls from S3, runs blender, pushes outputs)
    job = q.enqueue("worker.process_case", case_id)
    return {"case_id": case_id, "job_id": job.id, "status": "queued"}

@app.get("/status/{job_id}")
def status(job_id: str):
    from rq.job import Job
    try:
        job = Job.fetch(job_id, connection=r)
    except Exception:
        raise HTTPException(404, "Unknown job")
    return {"status": job.get_status(), "meta": job.meta}

def _signed(key, expires=3600):
    return s3.generate_presigned_url("get_object", Params={"Bucket": BUCKET, "Key": key}, ExpiresIn=expires)

@app.get("/download/{case_id}")
def download_links(case_id: str):
    prosth_key = f"{OUT_PREFIX}{case_id}_prosthesis.stl"
    mold_key   = f"{OUT_PREFIX}{case_id}_mold.stl"
    # we return links regardless; client can 404 if not yet present
    return {
        "prosthetic_url": _signed(prosth_key),
        "mold_url": _signed(mold_key)
    }
