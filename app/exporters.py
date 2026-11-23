from __future__ import annotations

import csv
import io
import json


def _when(m: dict) -> str:
    if m.get("raw_date"):
        return f"{m['raw_date']} {m['raw_time']}"
    return ""


def _body(m: dict) -> str:
    if m.get("audio_path"):
        t = m.get("transcript")
        if m["tr_status"] == "error":
            return f"[AUDIO - erro na transcricao: {m.get('tr_error')}]"
        if t is None:
            return "[AUDIO - nao transcrito]"
        return f"[AUDIO] {t}" if t else "[AUDIO - sem fala detectada]"
    return m["text"]


def to_txt(messages: list[dict], only_audios: bool = False) -> str:
    out = []
    for m in messages:
        if only_audios and not m.get("audio_path"):
            continue
        who = f"{m['sender']}: " if m.get("sender") else ""
        out.append(f"[{_when(m)}] {who}{_body(m)}" if _when(m) else f"{who}{_body(m)}")
    return "\n".join(out) + "\n"


def to_md(messages: list[dict], title: str, only_audios: bool = False) -> str:
    out = [f"# Transcricao: {title}", ""]
    for m in messages:
        if only_audios and not m.get("audio_path"):
            continue
        who = m.get("sender") or "Sistema"
        out.append(f"**{who}** _{_when(m)}_  ")
        out.append(_body(m).replace("\n", "  \n"))
        out.append("")
    return "\n".join(out)


def to_json(messages: list[dict]) -> str:
    return json.dumps(messages, ensure_ascii=False, indent=2)


def to_csv(messages: list[dict], only_audios: bool = False) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["data", "hora", "remetente", "tipo", "arquivo_audio", "texto"])
    for m in messages:
        is_audio = bool(m.get("audio_path"))
        if only_audios and not is_audio:
            continue
        w.writerow([
            m.get("raw_date") or "", m.get("raw_time") or "", m.get("sender") or "",
            "audio" if is_audio else "texto", m.get("audio_name") or "",
            (m.get("transcript") or "") if is_audio else m["text"],
        ])
    return buf.getvalue()
