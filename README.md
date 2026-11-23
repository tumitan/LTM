# Transcritor de áudios do WhatsApp

Envie o `.zip` de uma conversa exportada do WhatsApp (com mídia) e o app transcreve todos os
áudios, mostrando a conversa com as transcrições no lugar de cada áudio. Dá para buscar, filtrar
por pessoa, ouvir o áudio original e exportar (TXT, Markdown, CSV, JSON).

## Como usar

Requisitos: Python 3.10+ e `ffmpeg` instalado.

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

Abra http://localhost:8000, arraste o zip e clique em **Transcrever áudios**.

No WhatsApp: abra a conversa → ⋮ → Mais → Exportar conversa → **Incluir mídia**.

## Motores de transcrição

- **Local** (padrão): [faster-whisper](https://github.com/SYSTRAN/faster-whisper), gratuito e offline.
  O modelo é baixado na primeira execução (`small` ≈ 460 MB; `medium`/`large-v3-turbo` são mais precisos
  e mais lentos). Usa GPU automaticamente se disponível (`WHISPER_DEVICE=cpu|cuda|auto`).
- **OpenAI** (opcional): crie um arquivo `.env` (veja `.env.example`) com `OPENAI_API_KEY=sk-...` ou exporte a variável antes de iniciar o servidor. Quando a chave existe, o app já abre com OpenAI selecionado e transcreve 4 áudios em paralelo (`OPENAI_CONCURRENCY`). Modelos (`whisper-1`, `gpt-4o-mini-transcribe`,
  `gpt-4o-transcribe`). Os áudios são enviados à API.

Variáveis opcionais: `WHISPER_MODEL`, `WHISPER_COMPUTE_TYPE` (`int8`), `WHISPER_BEAM_SIZE` (`5`),
`MAX_UPLOAD_MB` (`2048`), `DATA_DIR` (`./data`).

Os jobs ficam salvos em `data/` (zip original + `result.json`), então você pode reabrir conversas
anteriores. Há um botão para excluí-las.

## Testes

```bash
pytest
python scripts/make_sample_zip.py sample.zip   # zip de exemplo com fala sintetizada (requer espeak-ng)
```

Formatos de export suportados pelo parser: iOS (`[dd/mm/aaaa hh:mm:ss] Nome: ...`) e Android
(`dd/mm/aaaa hh:mm - Nome: ...`), incluindo datas dd/mm ou mm/dd e AM/PM.
