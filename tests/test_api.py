import io
import time
import zipfile

import pytest
from fastapi.testclient import TestClient


class FakeTranscriber:
    def transcribe(self, path, language):
        if "bad" in open(path, "rb").read().decode("latin-1"):
            raise RuntimeError("audio corrompido")
        return "texto transcrito"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import jobs
    monkeypatch.setattr(jobs, "DATA_DIR", tmp_path)
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")
    jobs.JOBS.clear()
    monkeypatch.setattr(jobs, "make_transcriber", lambda e, m: FakeTranscriber())
    from app.main import app
    with TestClient(app) as c:
        yield c


def make_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("_chat.txt",
                   "[23/11/2026 14:33:01] Bruno: <anexado: a1.opus>\n"
                   "[23/11/2026 14:34:01] Ana: <anexado: bad.opus>\n"
                   "[23/11/2026 14:35:01] Ana: oi\n")
        z.writestr("a1.opus", b"ok")
        z.writestr("bad.opus", b"bad")
    return buf.getvalue()


def test_full_flow(client):
    r = client.post("/api/jobs", files={"file": ("Conversa Çá.zip", make_zip())},
                    data={"engine": "local", "model": "tiny", "language": "pt"})
    assert r.status_code == 200, r.text
    jid = r.json()["id"]
    for _ in range(50):
        s = client.get(f"/api/jobs/{jid}").json()
        if s["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert s["status"] == "done"
    assert s["total_audios"] == 2 and s["failed_audios"] == 1
    msgs = client.get(f"/api/jobs/{jid}/messages").json()["messages"]
    assert msgs[0]["transcript"] == "texto transcrito"
    assert msgs[1]["tr_status"] == "error"
    assert client.get(f"/api/jobs/{jid}/audio/0").content == b"ok"
    for fmt in ("txt", "md", "csv", "json"):
        e = client.get(f"/api/jobs/{jid}/export", params={"format": fmt})
        assert e.status_code == 200
    assert "texto transcrito" in client.get(f"/api/jobs/{jid}/export").text


def test_rejects_non_zip(client):
    r = client.post("/api/jobs", files={"file": ("x.zip", b"nao e zip")})
    assert r.status_code == 400
