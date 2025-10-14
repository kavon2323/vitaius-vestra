# server/api.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import subprocess
import shlex

BRAND_NAME = os.getenv("BRAND_NAME", "Vitaius")
PRODUCT_NAME = os.getenv("PRODUCT_NAME", "Vestra Forms")

# Path assumptions (repo layout)
BLENDER_BIN = os.getenv("BLENDER_BIN", "blender")  # rely on PATH or set absolute
PROCESS_SCRIPT = os.getenv("PROCESS_SCRIPT", "headless/process_cli.py")

app = FastAPI(
    title="Vitaius API",
    description=f"Backend for {PRODUCT_NAME} scanning, mirroring, and fulfillment",
    version="1.0.0",
)

class LocalRunRequest(BaseModel):
    input: str
    chest_wall: str | None = None
    axis: str = "X"
    base_offset_mm: float = 2.0
    mold_padding_mm: float = 10.0
    out_prosthetic: str | None = None
    out_mold: str | None = None

@app.get("/healthz")
def healthz():
    return {"ok": True, "brand": BRAND_NAME, "product": PRODUCT_NAME}

@app.post("/run-local")
def run_local(req: LocalRunRequest):
    """DEV ONLY: run Blender headless locally to verify end-to-end."""
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
        print("Running:", " ".join(shlex.quote(c) for c in cmd))
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        return {"ok": True, "log": out}
    except subprocess.CalledProcessError as e:
        raise HTTPException(500, f"Blender failed:\n{e.output}")
