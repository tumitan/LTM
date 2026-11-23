"""Parser do export de conversas do WhatsApp (iOS e Android, varios idiomas)."""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePosixPath

AUDIO_EXTS = (
    "opus", "ogg", "oga", "m4a", "mp3", "aac", "wav", "amr", "waptt", "3gp", "flac", "caf",
)
_AUDIO_EXT_RE = re.compile(r"\.(?:%s)\b" % "|".join(AUDIO_EXTS), re.IGNORECASE)

_INVISIBLE = dict.fromkeys(map(ord, "\u200e\u200f\u202a\u202b\u202c\u202d\u202e\ufeff"))

_DATE = r"(\d{1,4}[/.\-]\d{1,2}[/.\-]\d{1,4})"
_TIME = r"(\d{1,2}[:.]\d{2}(?:[:.]\d{2})?(?:\s?[AaPp]\.?\s?[Mm]\.?)?)"
_IOS_RE = re.compile(rf"^\[{_DATE},?\s+{_TIME}\]\s(.*)$")
_ANDROID_RE = re.compile(rf"^{_DATE},?\s+{_TIME}\s[-\u2013]\s(.*)$")


@dataclass
class Message:
    index: int
    raw_date: str | None
    raw_time: str | None
    sender: str | None
    text: str
    timestamp: str | None = None
    audio_path: str | None = None
    audio_name: str | None = None
    audio_orphan: bool = False
    extra_lines: list[str] = field(default_factory=list)


def _clean(s: str) -> str:
    return s.translate(_INVISIBLE)


def _split_sender(rest: str) -> tuple[str | None, str]:
    sender, sep, text = rest.partition(": ")
    if sep and sender and len(sender) <= 80:
        return sender.strip(), text
    return None, rest


def _detect_date_order(dates: list[str]) -> str:
    """Retorna 'dmy', 'mdy' ou 'ymd'."""
    first_is_year = False
    for d in dates:
        parts = re.split(r"[/.\-]", d)
        if len(parts) != 3:
            continue
        if len(parts[0]) == 4:
            first_is_year = True
            continue
        a, b = int(parts[0]), int(parts[1])
        if a > 12:
            return "dmy"
        if b > 12:
            return "mdy"
    return "ymd" if first_is_year else "dmy"


def _parse_dt(raw_date: str, raw_time: str, order: str) -> str | None:
    try:
        p = [int(x) for x in re.split(r"[/.\-]", raw_date)]
        if order == "ymd":
            y, m, d = p
        elif order == "mdy":
            m, d, y = p
        else:
            d, m, y = p
        if y < 100:
            y += 2000
        t = raw_time.strip()
        ampm = None
        mt = re.search(r"([AaPp])\.?\s?[Mm]\.?$", t)
        if mt:
            ampm = mt.group(1).lower()
            t = t[: mt.start()].strip()
        tp = [int(x) for x in re.split(r"[:.]", t)]
        hh, mm = tp[0], tp[1]
        ss = tp[2] if len(tp) > 2 else 0
        if ampm == "p" and hh < 12:
            hh += 12
        if ampm == "a" and hh == 12:
            hh = 0
        return datetime(y, m, d, hh, mm, ss).isoformat()
    except (ValueError, IndexError):
        return None


def list_audio_entries(zf: zipfile.ZipFile) -> dict[str, str]:
    """basename -> caminho dentro do zip, para todos os audios."""
    out: dict[str, str] = {}
    for info in zf.infolist():
        if info.is_dir() or info.filename.startswith("__MACOSX/"):
            continue
        base = PurePosixPath(info.filename).name
        if base.lower().endswith(tuple("." + e for e in AUDIO_EXTS)):
            out.setdefault(base, info.filename)
    return out


def find_chat_entry(zf: zipfile.ZipFile) -> str | None:
    txts = [
        i for i in zf.infolist()
        if not i.is_dir() and i.filename.lower().endswith(".txt")
        and not i.filename.startswith("__MACOSX/")
    ]
    if not txts:
        return None
    preferred = [i for i in txts if PurePosixPath(i.filename).name.startswith("_chat")]
    pool = preferred or txts
    return max(pool, key=lambda i: i.file_size).filename


def parse_chat_text(text: str, audio_entries: dict[str, str]) -> list[Message]:
    lines = _clean(text).splitlines()
    heads: list[tuple[str, str, str]] = []
    entries: list[tuple[str, str, str] | None] = []
    for line in lines:
        m = _IOS_RE.match(line) or _ANDROID_RE.match(line)
        if m:
            heads.append((m.group(1), m.group(2), m.group(3)))
            entries.append((m.group(1), m.group(2), m.group(3)))
        else:
            entries.append(None)

    order = _detect_date_order([h[0] for h in heads])

    messages: list[Message] = []
    cur: Message | None = None
    for line, e in zip(lines, entries):
        if e is None:
            if cur is not None:
                cur.extra_lines.append(line)
            continue
        raw_date, raw_time, rest = e
        sender, body = _split_sender(rest)
        cur = Message(
            index=len(messages),
            raw_date=raw_date,
            raw_time=raw_time,
            sender=sender,
            text=body,
            timestamp=_parse_dt(raw_date, raw_time, order),
        )
        messages.append(cur)

    matched: set[str] = set()
    names = sorted(audio_entries, key=len, reverse=True)
    for msg in messages:
        if msg.extra_lines:
            msg.text = "\n".join([msg.text, *msg.extra_lines])
        msg.extra_lines = []
        if not _AUDIO_EXT_RE.search(msg.text):
            continue
        for name in names:
            if name in msg.text and name not in matched:
                msg.audio_name = name
                msg.audio_path = audio_entries[name]
                matched.add(name)
                break

    for name in sorted(audio_entries):
        if name in matched:
            continue
        messages.append(
            Message(
                index=len(messages), raw_date=None, raw_time=None, sender=None,
                text=f"<audio sem referencia na conversa: {name}>",
                audio_name=name, audio_path=audio_entries[name], audio_orphan=True,
            )
        )
    return messages


def parse_zip(path: str) -> tuple[list[Message], str | None]:
    """Retorna (mensagens, nome_do_arquivo_de_chat)."""
    with zipfile.ZipFile(path) as zf:
        audios = list_audio_entries(zf)
        chat = find_chat_entry(zf)
        if chat is None:
            msgs = [
                Message(index=i, raw_date=None, raw_time=None, sender=None,
                        text=f"<audio: {n}>", audio_name=n, audio_path=p, audio_orphan=True)
                for i, (n, p) in enumerate(sorted(audios.items()))
            ]
            return msgs, None
        raw = zf.read(chat)
    for enc in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    return parse_chat_text(text, audios), chat
