"""Gerenciamento de jobs: upload do zip, parsing e transcricao em background."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from .chat_parser import Message, parse_zip
from .transcriber import Transcriber, make_transcriber

DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
JOBS_DIR = DATA_DIR / "jobs"


class Job:
    def __init__(self, job_id: str, engine: str, model: str, language: str | None,
                 filename: str):
        self.id = job_id
        self.engine = engine
        self.model = model
        self.language = language
        self.filename = filename
        self.status = "queued"  # queued|parsing|transcribing|done|error|cancelled
        self.error: str | None = None
        self.chat_file: str | None = None
        self.created_at = time.time()
        self.messages: list[dict] = []
        self.lock = threading.RLock()
        self.cancel = threading.Event()

    @property
    def dir(self) -> Path:
        return JOBS_DIR / self.id

    @property
    def zip_path(self) -> Path:
        return self.dir / "upload.zip"

    def audio_msgs(self) -> list[dict]:
        return [m for m in self.messages if m.get("audio_path")]

    def summary(self) -> dict:
        audios = self.audio_msgs()
        done = sum(1 for m in audios if m["tr_status"] in ("done", "error"))
        return {
            "id": self.id, "status": self.status, "error": self.error,
            "filename": self.filename, "engine": self.engine, "model": self.model,
            "language": self.language, "created_at": self.created_at,
            "chat_file": self.chat_file, "total_messages": len(self.messages),
            "total_audios": len(audios), "done_audios": done,
            "failed_audios": sum(1 for m in audios if m["tr_status"] == "error"),
        }

    def save(self) -> None:
        with self.lock:
            data = {**self.summary(), "messages": self.messages}
        tmp = self.dir / "result.json.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.dir / "result.json")


JOBS: dict[str, Job] = {}


def load_existing() -> None:
    if not JOBS_DIR.exists():
        return
    for d in JOBS_DIR.iterdir():
        f = d / "result.json"
        if not f.exists():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            job = Job(data["id"], data["engine"], data["model"], data.get("language"),
                      data["filename"])
            job.status = data["status"]
            if job.status in ("queued", "parsing", "transcribing"):
                job.status = "cancelled"
                job.error = "Interrompido por reinicio do servidor."
            job.error = data.get("error") or job.error
            job.chat_file = data.get("chat_file")
            job.created_at = data.get("created_at", job.created_at)
            job.messages = data["messages"]
            for m in job.messages:
                if m.get("tr_status") in ("pending", "running"):
                    m["tr_status"] = "pending"
            JOBS[job.id] = job
        except Exception:
            continue


def create_job(upload_path: str, filename: str, engine: str, model: str,
               language: str | None,
               transcriber_factory: Callable[[str, str], Transcriber] | None = None) -> Job:
    job = Job(uuid.uuid4().hex[:12], engine, model, language, filename)
    job.dir.mkdir(parents=True, exist_ok=True)
    shutil.move(upload_path, job.zip_path)
    JOBS[job.id] = job
    factory = transcriber_factory or (lambda e, m: make_transcriber(e, m))
    threading.Thread(target=_run, args=(job, factory), daemon=True).start()
    return job


def _msg_to_dict(m: Message) -> dict:
    d = asdict(m)
    d.pop("extra_lines", None)
    d["tr_status"] = "pending" if m.audio_path else "none"
    d["transcript"] = None
    d["tr_error"] = None
    return d


def _run(job: Job, transcriber_factory: Callable) -> None:
    try:
        job.status = "parsing"
        msgs, chat_file = parse_zip(str(job.zip_path))
        with job.lock:
            job.chat_file = chat_file
            job.messages = [_msg_to_dict(m) for m in msgs]
        audios = job.audio_msgs()
        if not audios:
            job.status = "done"
            job.error = "Nenhum audio encontrado no zip (exporte a conversa 'com midia')."
            job.save()
            return
        job.save()
        job.status = "transcribing"
        transcriber = transcriber_factory(job.engine, job.model)
        workers = int(os.getenv("OPENAI_CONCURRENCY", "4")) if job.engine == "openai" else 1
        save_lock = threading.Lock()
        last_save = [time.time()]
        zip_lock = threading.Lock()
        zf = zipfile.ZipFile(job.zip_path)

        def work(m: dict) -> None:
            if job.cancel.is_set():
                return
            m["tr_status"] = "running"
            suffix = Path(m["audio_name"]).suffix or ".opus"
            with zip_lock:
                data = zf.read(m["audio_path"])
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(data)
            try:
                m["transcript"] = transcriber.transcribe(tmp.name, job.language)
                m["tr_status"] = "done"
            except Exception as e:  # noqa: BLE001 - um audio ruim nao pode derrubar o job
                m["tr_status"] = "error"
                m["tr_error"] = f"{type(e).__name__}: {e}"
            finally:
                os.unlink(tmp.name)
            with save_lock:
                if time.time() - last_save[0] > 5:
                    job.save()
                    last_save[0] = time.time()

        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(work, audios))
        finally:
            zf.close()
        if job.cancel.is_set():
            job.status = "cancelled"
        if job.status != "cancelled":
            job.status = "done"
    except Exception as e:  # noqa: BLE001
        job.status = "error"
        job.error = f"{type(e).__name__}: {e}"
    finally:
        for m in job.audio_msgs():
            if m["tr_status"] == "running":
                m["tr_status"] = "pending"
        job.save()


def delete_job(job_id: str) -> None:
    job = JOBS.pop(job_id, None)
    if job:
        job.cancel.set()
        shutil.rmtree(job.dir, ignore_errors=True)
