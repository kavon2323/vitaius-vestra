# worker/runner.py
import os, time, json, subprocess, shlex, tempfile
import boto3
from botocore.config import Config as BotoConfig
import redis

AWS_REGION = os.getenv("AWS_REGION", "us-west-2")
S3_BUCKET = os.getenv("S3_BUCKET")
REDIS_URL = os.getenv("REDIS_URL")
BLENDER_BIN = os.getenv("BLENDER_BIN", "blender")
PROCESS_SCRIPT = os.getenv("PROCESS_SCRIPT", "headless/process_cli.py")

JOBS_QUEUE = "vestra:jobs"

r = redis.from_url(REDIS_URL, decode_responses=True)
s3 = boto3.client("s3", region_name=AWS_REGION, config=BotoConfig(s3={"addressing_style": "virtual"}))

def job_key(job_id: str) -> str:
    return f"vestra:job:{job_id}"

def set_status(job_id: str, **updates):
    updates["updated_at"] = str(time.time())
    r.hset(job_key(job_id), mapping={k: (str(v) if isinstance(v, (int, float)) else v) for k,v in updates.items()})

def download_s3(key: str, dst_path: str):
    s3.download_file(S3_BUCKET, key, dst_path)

def upload_s3(src_path: str, key: str):
    s3.upload_file(src_path, S3_BUCKET, key)

def process_job(job_id: str):
    data = r.hgetall(job_key(job_id))
    if not data:
        return

    try:
        set_status(job_id, status="processing")
        axis = data.get("axis", "X")
        base_offset_mm = float(data.get("base_offset_mm", 2.0))
        mold_padding_mm = float(data.get("mold_padding_mm", 10.0))
        in_key = data["input_key"]

        # temp workspace
        with tempfile.TemporaryDirectory() as tmp:
            in_path = os.path.join(tmp, "input.stl")
            download_s3(in_key, in_path)

            out_pro_key = f"stl/{job_id}/vitaius_vestra_prosthetic.stl"
            out_mold_key = f"stl/{job_id}/vitaius_vestra_mold.stl"
            out_pro = os.path.join(tmp, "vitaius_vestra_prosthetic.stl")
            out_mold = os.path.join(tmp, "vitaius_vestra_mold.stl")

            cmd = [
                BLENDER_BIN, "-b", "-P", PROCESS_SCRIPT, "--",
                "--input", in_path,
                "--axis", axis,
                "--base_offset_mm", str(base_offset_mm),
                "--mold_padding_mm", str(mold_padding_mm),
                "--out_prosthetic", out_pro,
                "--out_mold", out_mold
            ]
            print("Running:", " ".join(shlex.quote(c) for c in cmd))
            subprocess.check_call(cmd)

            # Upload results
            upload_s3(out_pro, out_pro_key)
            upload_s3(out_mold, out_mold_key)

            set_status(
                job_id,
                status="done",
                out_prosthetic_key=out_pro_key,
                out_mold_key=out_mold_key,
                error=None
            )
    except subprocess.CalledProcessError as e:
        set_status(job_id, status="failed", error=f"blender failed: {e}")
    except Exception as e:
        set_status(job_id, status="failed", error=str(e))

def main_loop():
    print("Vitaius worker loop started. Waiting for jobs…")
    while True:
        # BLPOP: blocks for up to 5 seconds
        item = r.blpop(JOBS_QUEUE, timeout=5)
        if not item:
            continue
        _queue, job_id = item
        try:
            process_job(job_id)
        except Exception as e:
            set_status(job_id, status="failed", error=str(e))

if __name__ == "__main__":
    main_loop()
