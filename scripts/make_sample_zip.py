"""Gera um zip de exemplo (estilo iOS) com audios sintetizados via espeak-ng, para testes."""
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

PHRASES = [
    ("Ana", "Oi Bruno, tudo bem? Preciso que você me mande o relatório até sexta-feira."),
    ("Bruno", "Claro, eu envio amanhã de manhã. O orçamento ficou em cinco mil reais."),
    ("Ana", "Perfeito. Vamos marcar a reunião com o cliente para segunda às dez horas."),
]

out = Path(sys.argv[1] if len(sys.argv) > 1 else "sample_whatsapp.zip")
chat = []
with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(out, "w") as z:
    for i, (who, text) in enumerate(PHRASES, 1):
        wav, opus = f"{tmp}/{i}.wav", f"{tmp}/{i}.opus"
        subprocess.run(["espeak-ng", "-v", "pt-br", "-s", "150", "-w", wav, text], check=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-c:a", "libopus", opus],
                       check=True)
        name = f"0000000{i}-AUDIO-2026-11-23-10-0{i}-00.opus"
        z.write(opus, name)
        chat.append(f"[23/11/2026 10:0{i}:00] {who}: \u200e<anexado: {name}>")
        chat.append(f"[23/11/2026 10:0{i}:30] {who}: ok, valeu")
    z.writestr("_chat.txt", "\n".join(chat))
print("gerado", out)
