# libros2pdf

> Convert scanned historical book images into searchable PDFs with an OCR text layer.

**libros2pdf** processes directories of scanned images (JPG, PNG, TIF) and produces PDF files with an invisible OCR layer, making them fully searchable and copy-paste friendly. Designed for historical parish records, it supports five OCR backends — from free local Tesseract to cloud vision models such as Gemini, Claude, and GPT-4o.

[Documentación en español →](README.es.md)

---

## Features

- **Five OCR backends**: Tesseract (local, free), Ollama (local), OpenRouter, Claude, OpenAI
- **Images → PDF+OCR**: one PDF per sub-folder, automatically sorted
- **Existing PDF → PDF+OCR**: add a text layer to any already-scanned PDF
- **Three output formats**: standard PDF, archival PDF/A-2b, compressed (~50% smaller)
- **Interactive TUI**: live progress bars, per-book tracking, real-time log
- **REST API**: background jobs, Server-Sent Events, Swagger UI
- **Resumable**: state is saved after every page — restart and continue where you left off
- **Configurable parallelism**: concurrent workers for vision APIs
- **Custom prompt**: tailor the transcription instructions to your document type
- **Integrity check**: every output PDF is verified before being marked as done
- **i18n**: UI available in Spanish, English, and Catalan

---

## Installation

```bash
# Core dependencies
pip install pillow pikepdf pymupdf rich textual

# Cloud vision backends (install only what you need)
pip install openai          # OpenAI and OpenRouter
pip install anthropic       # Claude

# API server
pip install fastapi uvicorn
```

**Tesseract** (free local OCR):

```bash
# macOS
brew install tesseract tesseract-lang

# Debian / Ubuntu
sudo apt install tesseract-ocr tesseract-ocr-spa tesseract-ocr-lat

# Windows — download installer from https://github.com/UB-Mannheim/tesseract/wiki
```

---

## Quick start

```bash
# Interactive TUI (recommended for first use)
python3 -m libros2pdf

# CLI — images to PDF with Tesseract
python3 -m libros2pdf ./scans ./output

# CLI — images to PDF with OpenRouter (best quality for manuscripts)
python3 -m libros2pdf ./scans ./output \
  --engine openrouter \
  --model google/gemini-2.5-flash-lite \
  --api-key sk-or-v1-...

# Add OCR layer to existing PDFs
python3 -m libros2pdf ocr-pdf ./existing_pdfs ./output_pdfs \
  --engine openrouter \
  --model google/gemini-2.5-flash-lite \
  --api-key sk-or-v1-...

# REST API server
python3 -m libros2pdf serve
# → http://127.0.0.1:8000/docs
```

---

## Directory structure

libros2pdf expects **one sub-folder per book**. Each sub-folder becomes one PDF:

```
scans/
├── BAPTISMS 01. 1850-1860/
│   ├── IMG_0001.JPG
│   ├── IMG_0002.JPG
│   └── ...
├── BAPTISMS 02. 1861-1870/
│   └── ...
└── BAPTISMS 03. 1871-1880/
    └── ...
```

Running `python3 -m libros2pdf ./scans ./output` produces:

```
output/
├── BAPTISMS 01. 1850-1860.pdf
├── BAPTISMS 02. 1861-1870.pdf
├── BAPTISMS 03. 1871-1880.pdf
└── estado.json         ← resumable state
```

If a folder contains images directly (no sub-folders), a single PDF is generated.

Supported image formats: **JPG, JPEG, PNG, TIF, TIFF** (case-insensitive). Files are sorted with natural order (`IMG_2` before `IMG_10`).

---

## CLI reference

### `process` — images → PDF

```bash
python3 -m libros2pdf process <input_dir> [output_dir] [options]
# short form (auto-detected when first argument is a path):
python3 -m libros2pdf <input_dir> [output_dir] [options]
```

| Option | Default | Description |
|---|---|---|
| `--engine` | `tesseract` | OCR backend: `tesseract`, `claude`, `openai`, `openrouter`, `ollama` |
| `--model` | *(per engine)* | Model name (e.g. `google/gemini-2.5-flash-lite`, `claude-sonnet-4-6`) |
| `--api-key` | env var | API key (or set `OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`) |
| `--base-url` | *(per engine)* | Custom API base URL (useful for OpenRouter, Ollama, or any OpenAI-compatible endpoint) |
| `--lang` | `spa+lat` | Tesseract language codes joined by `+` (e.g. `spa`, `spa+lat`, `spa+lat+equ`) |
| `--psm` | `6` | Tesseract page segmentation mode: `3` = auto, `6` = uniform block |
| `--dpi` | `250` | Target resolution for rasterising pages |
| `--workers` | `3` | Parallel pages for vision backends (ignored for Tesseract) |
| `--prompt` | *(built-in)* | Custom transcription prompt for vision backends |
| `--format` | `pdf` | Output format: `pdf`, `pdf_a` (archival PDF/A-2b), `compressed` (~50% smaller) |
| `--no-ocr` | `false` | Skip OCR — produce image-only PDF (much faster) |
| `--force` | `false` | Ignore saved state and reprocess everything |
| `--delete-originals` | `false` | Delete the source image folder after verifying the PDF (**irreversible**) |
| `--tessdata` | `$TESSDATA_PREFIX` | Custom path to Tesseract language data |
| `--no-rich` | `false` | Disable progress bars (useful for scripting / piping) |

### `ocr-pdf` — add OCR to existing PDFs

```bash
python3 -m libros2pdf ocr-pdf <input> [output_dir] [options]
```

`<input>` can be a single PDF file or a directory of PDFs.

| Option | Default | Description |
|---|---|---|
| `--engine` | `openrouter` | OCR backend |
| `--model` | *(per engine)* | Model name |
| `--api-key` | env var | API key |
| `--base-url` | *(per engine)* | Custom API base URL |
| `--prompt` | *(built-in)* | Custom prompt |
| `--format` | `pdf` | Output format: `pdf`, `pdf_a`, `compressed` |
| `--workers` | `3` | Parallel pages |
| `--dpi` | `250` | Resolution for rasterising PDF pages |

### `tui` — interactive terminal UI

```bash
python3 -m libros2pdf tui
python3 -m libros2pdf        # default when called with no arguments
```

### `serve` — REST API server

```bash
python3 -m libros2pdf serve [--host HOST] [--port PORT]
```

| Option | Default | Description |
|---|---|---|
| `--host` | `127.0.0.1` | Bind address (`0.0.0.0` to expose on the network) |
| `--port` | `8000` | TCP port |

### `status` — processing state

```bash
python3 -m libros2pdf status [output_dir] [input_dir]
```

---

## OCR engines

| Engine | Type | Manuscript quality | Cost | Speed |
|---|---|---|---|---|
| `tesseract` | Local | ★★☆☆☆ | Free | Fast (sequential) |
| `ollama` | Local | ★★★☆☆ | Free | Medium |
| `openrouter` | Cloud | ★★★★★ | ~$0.001 / page | Fast (parallel) |
| `claude` | Cloud | ★★★★★ | ~$0.001 / page | Fast (parallel) |
| `openai` | Cloud | ★★★★☆ | ~$0.001 / page | Fast (parallel) |

**Recommendation for historical manuscripts in Spanish/Latin**: OpenRouter with `google/gemini-2.5-flash-lite` — highest accuracy at the lowest cost.

### Model examples

```bash
# OpenRouter
--engine openrouter --model google/gemini-2.5-flash-lite
--engine openrouter --model anthropic/claude-haiku-4-5

# Claude direct
--engine claude --model claude-haiku-4-5-20251001
--engine claude --model claude-sonnet-4-6

# OpenAI
--engine openai --model gpt-4o-mini
--engine openai --model gpt-4o

# Ollama (local, no cost)
--engine ollama --model llava:13b
--engine ollama --model llava:34b
```

---

## Output formats

| Format | Flag | Description |
|---|---|---|
| Standard PDF | `--format pdf` | Image + invisible OCR layer. Maximum fidelity. |
| Archival PDF/A-2b | `--format pdf_a` | ISO 19005-2 compliant. Recommended for long-term preservation. |
| Compressed | `--format compressed` | Image recompressed via WebP→JPEG (~50% size reduction). |

---

## Custom OCR prompt

The default prompt is tuned for historical Spanish/Latin parish records. Override it with `--prompt`:

```bash
python3 -m libros2pdf ./scans ./output \
  --engine openrouter \
  --prompt "Transcribe every word exactly as written. Mark illegible words as [illegible]."
```

In the TUI, edit the prompt in the *Advanced options* section and save it to `config/prompt.txt` for persistence.

Default prompt:

```
Transcribe exactamente el texto visible en este documento histórico manuscrito.

- Copia el texto tal como aparece: respeta ortografía original, tildes y abreviaturas
- Si hay texto en latín, transcríbelo literalmente sin traducir
- Conserva la estructura: saltos de línea, párrafos y numeración de actas
- Marca palabras ilegibles como [ilegible] y palabras dudosas como [palabra?]
- Devuelve ÚNICAMENTE el texto transcrito, sin comentarios ni explicaciones
```

---

## Configuration

Settings are persisted in `config/settings.json` (created automatically on first save in the TUI):

```json
{
  "engine":     "openrouter",
  "model":      "google/gemini-2.5-flash-lite",
  "api_key":    "",
  "base_url":   "https://openrouter.ai/api/v1",
  "output_dir": "./PDF_LIBROS",
  "workers":    3,
  "pdf_format": "pdf",
  "lang":       "spa+lat",
  "skip_ocr":   false,
  "ui_lang":    "es"
}
```

The OCR prompt is stored separately in `config/prompt.txt`.

### Environment variables

```bash
export OPENROUTER_API_KEY=sk-or-v1-...
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
```

---

## TUI guide

Launch with `python3 -m libros2pdf`. Keyboard shortcuts:

| Key | Action |
|---|---|
| Arrow keys / mouse | Navigate |
| Tab / Shift+Tab | Next / previous field |
| Enter / Space | Activate button or toggle |
| Escape | Go back |
| q | Quit |

### Screens

| Screen | Description |
|---|---|
| Main menu | Select workflow, change UI language (ES / EN / CA) |
| Images → PDF | Configure engine, model, API key, format, workers, prompt |
| PDF → PDF+OCR | Same for existing PDFs |
| Processing | Live progress bars per book, global ETA, log, cancel |
| Status | Table of all books with completion state and file sizes |
| API server | Start the REST server from the UI |

The **Test connection** button validates your API key and model before starting any job.

---

## REST API

Start the server:

```bash
python3 -m libros2pdf serve
# Swagger UI: http://127.0.0.1:8000/docs
```

### Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/process` | Start images → PDF job |
| `POST` | `/api/ocr-pdf` | Start existing PDF → PDF+OCR job |
| `GET` | `/api/status` | List all jobs and their progress |
| `GET` | `/api/books` | List input books and generated PDFs |
| `GET` | `/api/books/{name}/download` | Download a generated PDF |
| `GET` | `/api/events` | Server-Sent Events stream (real-time progress) |
| `DELETE` | `/api/cancel` | Cancel the active job (`?job_id=...`) |
| `GET` | `/docs` | Interactive Swagger UI |

### Start a job

```bash
# Images → PDF
curl -X POST http://localhost:8000/api/process \
  -H "Content-Type: application/json" \
  -d '{
    "input_dir":  "/path/to/scans",
    "output_dir": "/path/to/output",
    "engine":     "openrouter",
    "model":      "google/gemini-2.5-flash-lite",
    "api_key":    "sk-or-v1-...",
    "pdf_format": "pdf",
    "workers":    5
  }'

# Existing PDFs → add OCR
curl -X POST http://localhost:8000/api/ocr-pdf \
  -H "Content-Type: application/json" \
  -d '{
    "input_dir":  "/path/to/pdfs",
    "engine":     "openrouter",
    "model":      "google/gemini-2.5-flash-lite",
    "api_key":    "sk-or-v1-...",
    "pdf_format": "compressed"
  }'
```

### Real-time events (SSE)

```bash
curl -N http://localhost:8000/api/events
```

Event kinds:

| Kind | Key fields | Description |
|---|---|---|
| `BOOK_START` | `book`, `total` | Book processing started |
| `PAGE_OK` | `book`, `page`, `total`, `file` | Page OCR succeeded |
| `PAGE_FAIL` | `book`, `page`, `file` | Page OCR failed |
| `MERGE_START` | `book` | Merging page PDFs into final file |
| `BOOK_DONE` | `book`, `pages`, `size_mb` | Book completed |
| `VERIFY_OK` / `VERIFY_FAIL` | `book`, `file` | PDF integrity check result |
| `ALL_DONE` | `result` | All processing completed |
| `LOG` | `message` | Informational message |
| `ping` | — | Keepalive (every 10 s) |

### `ProcessRequest` fields

| Field | Type | Default | Description |
|---|---|---|---|
| `input_dir` | string | **required** | Input directory with images |
| `output_dir` | string | parent of input | Output directory |
| `engine` | string | `tesseract` | OCR backend |
| `model` | string | null | Model name |
| `api_key` | string | null | API key |
| `base_url` | string | null | Custom API base URL |
| `lang` | string | `spa+lat` | Tesseract languages |
| `psm` | int | `6` | Tesseract PSM |
| `dpi` | int | `250` | Target DPI |
| `workers` | int | `5` | Parallel workers |
| `pdf_format` | string | `pdf` | `pdf`, `pdf_a`, or `compressed` |
| `ocr_prompt` | string | null | Custom prompt |
| `skip_ocr` | bool | `false` | Image-only PDF |
| `force` | bool | `false` | Ignore saved state |
| `delete_originals` | bool | `false` | Delete source images after PDF |
| `tessdata` | string | null | Custom TESSDATA_PREFIX |

### `OcrPdfRequest` fields

| Field | Type | Default | Description |
|---|---|---|---|
| `input_dir` | string | **required** | PDF file or directory |
| `output_dir` | string | null | Output directory |
| `engine` | string | `openrouter` | OCR backend |
| `model` | string | null | Model name |
| `api_key` | string | null | API key |
| `base_url` | string | null | Custom API base URL |
| `ocr_prompt` | string | null | Custom prompt |
| `dpi` | int | `250` | Target DPI |
| `workers` | int | `3` | Parallel workers |
| `pdf_format` | string | `pdf` | `pdf`, `pdf_a`, or `compressed` |

---

## License

MIT — see [LICENSE](LICENSE).
