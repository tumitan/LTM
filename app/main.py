from __future__ import annotations

import mimetypes
import os
import tempfile
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import exporters, jobs
from .env import load_dotenv
from .transcriber import LOCAL_MODELS, OPENAI_MODELS, available_engines

load_dotenv()
STATIC = Path(__file__).parent / "static"
MAX_UPLOAD = int(os.getenv("MAX_UPLOAD_MB", "2048")) * 1024 * 1024

@asynccontextmanager
async def lifespan(_app: FastAPI):
    jobs.JOBS_DIR.mkdir(parents=True, exist_ok=True)
    jobs.load_existing()
    yield


app = FastAPI(title="Transcritor de audios do WhatsApp", lifespan=lifespan)


def _get(job_id: str) -> jobs.Job:
    job = jobs.JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job nao encontrado")
    return job


@app.get("/api/config")
def config():
    return {"engines": available_engines()}


@app.post("/api/jobs")
async def upload(
    file: UploadFile = File(...),
    engine: str = Form("local"),
    model: str = Form(""),
    language: str = Form("pt"),
):
    engines = available_engines()
    if engine not in engines:
        raise HTTPException(400, "Motor invalido")
    if not engines[engine]["available"]:
        raise HTTPException(400, "Motor indisponivel (falta OPENAI_API_KEY?)")
    model = model or engines[engine]["default_model"]
    if model not in (LOCAL_MODELS if engine == "local" else OPENAI_MODELS):
        raise HTTPException(400, "Modelo invalido")

    jobs.JOBS_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(suffix=".zip", dir=jobs.DATA_DIR)
    size = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise HTTPException(413, "Arquivo muito grande")
                out.write(chunk)
        if not zipfile.is_zipfile(tmp_path):
            raise HTTPException(400, "O arquivo enviado nao e um .zip valido")
    except BaseException:
        os.unlink(tmp_path)
        raise
    job = jobs.create_job(tmp_path, file.filename or "conversa.zip", engine, model,
                          None if language in ("", "auto") else language)
    return job.summary()


@app.get("/api/jobs")
def list_jobs():
    items = [j.summary() for j in jobs.JOBS.values()]
    return sorted(items, key=lambda s: s["created_at"], reverse=True)


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    return _get(job_id).summary()


@app.get("/api/jobs/{job_id}/messages")
def job_messages(job_id: str):
    job = _get(job_id)
    with job.lock:
        return {"summary": job.summary(), "messages": list(job.messages)}


@app.post("/api/jobs/{job_id}/cancel")
def cancel(job_id: str):
    _get(job_id).cancel.set()
    return {"ok": True}


@app.delete("/api/jobs/{job_id}")
def delete(job_id: str):
    _get(job_id)
    jobs.delete_job(job_id)
    return {"ok": True}


@app.get("/api/jobs/{job_id}/audio/{index}")
def audio(job_id: str, index: int):
    job = _get(job_id)
    if index < 0 or index >= len(job.messages) or not job.messages[index].get("audio_path"):
        raise HTTPException(404, "Audio nao encontrado")
    m = job.messages[index]
    with zipfile.ZipFile(job.zip_path) as zf:
        data = zf.read(m["audio_path"])
    name = m["audio_name"]
    ctype = mimetypes.guess_type(name)[0] or "audio/ogg"
    if name.lower().endswith((".opus", ".waptt")):
        ctype = "audio/ogg"
    return Response(data, media_type=ctype)


@app.get("/api/jobs/{job_id}/export")
def export(job_id: str, format: str = "txt", only_audios: bool = False):
    job = _get(job_id)
    with job.lock:
        msgs = list(job.messages)
    base = Path(job.filename).stem
    if format == "txt":
        body, ctype, ext = exporters.to_txt(msgs, only_audios), "text/plain", "txt"
    elif format == "md":
        body, ctype, ext = exporters.to_md(msgs, base, only_audios), "text/markdown", "md"
    elif format == "json":
        body, ctype, ext = exporters.to_json(msgs), "application/json", "json"
    elif format == "csv":
        body, ctype, ext = exporters.to_csv(msgs, only_audios), "text/csv", "csv"
    else:
        raise HTTPException(400, "Formato invalido")
    return Response(
        body.encode("utf-8-sig" if format == "csv" else "utf-8"),
        media_type=f"{ctype}; charset=utf-8",
        headers={"Content-Disposition":
                 f"attachment; filename*=UTF-8''{quote(base)}-transcricao.{ext}"},
    )


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
