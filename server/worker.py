import os, io, zipfile, tempfile, subprocess, boto3
from dotenv import load_dotenv
load_dotenv()

S3 = boto3.client("s3", region_name=os.getenv("AWS_REGION"))
BUCKET = os.getenv("S3_BUCKET")
IN_PREFIX = os.getenv("S3_INPUT_PREFIX","inputs/")
OUT_PREFIX = os.getenv("S3_OUTPUT_PREFIX","outputs/")
BLENDER = os.getenv("BLENDER_PATH","/usr/local/blender/blender")
PROCESS = "/app/headless/process_cli.py"  # mounted into worker

def process_case(case_id: str):
    # 1) download ZIP
    in_key = f"{IN_PREFIX}{case_id}.zip"
    obj = S3.get_object(Bucket=BUCKET, Key=in_key)
    data = obj["Body"].read()

    with tempfile.TemporaryDirectory() as tmp:
        case_dir = os.path.join(tmp, case_id); os.makedirs(case_dir, exist_ok=True)
        zipfile.ZipFile(io.BytesIO(data)).extractall(case_dir)

        out_prosthetic = os.path.join(tmp, f"{case_id}_prosthesis.stl")
        out_mold = os.path.join(tmp, f"{case_id}_mold.stl")

        # 2) run Blender headless
        cmd = [BLENDER,"-b","-P",PROCESS,"--",case_dir,out_prosthetic,out_mold]
        subprocess.run(cmd, check=True)

        # 3) upload results
        with open(out_prosthetic,"rb") as f:
            S3.put_object(Bucket=BUCKET, Key=f"{OUT_PREFIX}{case_id}_prosthesis.stl", Body=f.read())
        with open(out_mold,"rb") as f:
            S3.put_object(Bucket=BUCKET, Key=f"{OUT_PREFIX}{case_id}_mold.stl", Body=f.read())

    return {"ok": True}
