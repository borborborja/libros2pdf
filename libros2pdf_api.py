#!/usr/bin/env python3
"""
libros2pdf API — Servidor REST para procesar imágenes → PDFs con OCR.

Inicio:
    python3 -m libros2pdf serve
    # o directamente:
    python3 -m uvicorn libros2pdf_api:app --host 127.0.0.1 --port 8000 --reload

Endpoints:
    POST   /api/process     → Iniciar procesamiento
    GET    /api/status      → Estado actual
    GET    /api/books       → Lista de libros (input + output)
    GET    /api/books/{name}/download  → Descargar PDF
    GET    /api/events      → SSE de eventos en tiempo real
    DELETE /api/cancel      → Cancelar proceso activo
    GET    /                → Resumen HTML
    GET    /docs            → Swagger UI
"""

import os, json, time, threading, queue, asyncio, uuid
from pathlib import Path
from datetime import datetime

from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse
from pydantic import BaseModel

HERE = Path(__file__).parent.resolve()

# ── Importar core ────────────────────────────────────────────────────────────────
import sys
sys.path.insert(0, str(HERE))

from libros2pdf import (
    scan_books, process_all, load_state, ProgressEvent,
    DEFAULT_DPI, ENGINE_DEFAULTS, natural_sort_key,
    ocr_pdf_dir,
)

# ── FastAPI app ──────────────────────────────────────────────────────────────────

app = FastAPI(
    title="libros2pdf API",
    version="1.0.0",
    description="API para procesar imágenes de libros parroquiales → PDFs con OCR.",
)

# ── Estado compartido ────────────────────────────────────────────────────────────

_jobs: dict[str, dict] = {}          # job_id → {status, progress, ...}
_cancel_events: dict[str, threading.Event] = {}
_event_queues: list[asyncio.Queue] = []  # colas SSE
_queue_lock = threading.Lock()


# ── Modelos ──────────────────────────────────────────────────────────────────────

class ProcessRequest(BaseModel):
    input_dir:        str
    output_dir:       Optional[str] = None
    lang:             str  = "spa+lat"
    psm:              int  = 6
    dpi:              int  = DEFAULT_DPI
    tessdata:         Optional[str] = None
    force:            bool = False
    skip_ocr:         bool = False
    engine:           str  = "tesseract"
    model:            Optional[str] = None
    api_key:          Optional[str] = None
    base_url:         Optional[str] = None
    ocr_prompt:       Optional[str] = None
    workers:          int  = 5
    delete_originals: bool = False
    pdf_format:       str  = "pdf"   # pdf | pdf_a | compressed

class OcrPdfRequest(BaseModel):
    input_dir:  str
    output_dir: Optional[str] = None
    engine:     str  = "openrouter"
    model:      Optional[str] = None
    api_key:    Optional[str] = None
    base_url:   Optional[str] = None
    ocr_prompt: Optional[str] = None
    dpi:        int  = DEFAULT_DPI
    workers:    int  = 3
    pdf_format: str  = "pdf"         # pdf | pdf_a | compressed

class JobStatus(BaseModel):
    job_id: str
    status: str
    created: str
    books_total: int = 0
    books_completed: int = 0
    pages_total: int = 0
    pages_done: int = 0
    current_book: str = ""
    elapsed: int = 0
    result: Optional[dict] = None


# ── Utilidades ───────────────────────────────────────────────────────────────────

def _broadcast_event(ev: ProgressEvent):
    """Envía un evento a todas las colas SSE activas."""
    data = json.dumps(ev.to_dict(), ensure_ascii=False)
    with _queue_lock:
        dead = []
        for q in _event_queues:
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            _event_queues.remove(q)


def _run_job(job_id: str, input_dir: Path, output_dir: Path, **kwargs):
    """Ejecuta process_all en un hilo de fondo y actualiza _jobs."""
    cancel_ev = _cancel_events.get(job_id) or threading.Event()
    q: queue.Queue = queue.Queue()

    job = _jobs[job_id]
    job["status"] = "running"

    # Hilo puente: cola threading → colas asyncio
    def bridge():
        while True:
            try:
                ev = q.get(timeout=1)
            except queue.Empty:
                if not _jobs.get(job_id) or _jobs[job_id]["status"] in ("completed", "cancelled"):
                    break
                continue
            _broadcast_event(ev)
            # Actualizar métricas del job
            d = ev.to_dict()
            if ev.kind == ProgressEvent.BOOK_START:
                job["current_book"] = d.get("book", "")
                job["pages_total"] = job.get("pages_total", 0) + d.get("total", 0)
            elif ev.kind == ProgressEvent.PAGE_OK:
                job["pages_done"] = job.get("pages_done", 0) + 1
            elif ev.kind == ProgressEvent.PAGE_FAIL:
                job["pages_done"] = job.get("pages_done", 0) + 1
            elif ev.kind == ProgressEvent.BOOK_DONE:
                job["books_completed"] = job.get("books_completed", 0) + 1
            elif ev.kind == ProgressEvent.ALL_DONE:
                job["status"] = "completed"
                job["result"] = d.get("result")
                break
            elif ev.kind == ProgressEvent.BOOK_FAIL:
                job["books_completed"] = job.get("books_completed", 0) + 1

    bthread = threading.Thread(target=bridge, daemon=True)
    bthread.start()

    try:
        books = scan_books(input_dir)
        job["books_total"] = len(books)
        job["pages_total"] = sum(len(imgs) for _, imgs in books)

        estado_path = output_dir / "estado.json"
        chunk_dir = output_dir / "_tmp"

        result = process_all(
            books, output_dir, chunk_dir, estado_path,
            event_queue=q, cancel_event=cancel_ev, **kwargs,
        )
        job["result"] = result
        job["status"] = "cancelled" if cancel_ev.is_set() else "completed"
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        _broadcast_event(ProgressEvent(ProgressEvent.LOG, message=f"Error: {e}"))

    job["elapsed"] = int(time.time() - job["_start"])
    bthread.join(timeout=2)


# ── Endpoints ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def root():
    """Documentación completa de la API."""
    return """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>libros2pdf API</title>
  <style>
    :root {
      --bg: #ffffff; --surface: #f8fafc; --border: #e2e8f0;
      --text: #1e293b; --muted: #64748b; --accent: #2563eb;
      --green: #16a34a; --code-bg: #f1f5f9; --radius: 8px;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
           background: var(--bg); color: var(--text); line-height: 1.6; }
    .layout { display: flex; min-height: 100vh; }
    nav { width: 240px; min-width: 240px; background: var(--surface);
          border-right: 1px solid var(--border); padding: 1.5rem 1rem;
          position: sticky; top: 0; height: 100vh; overflow-y: auto; }
    nav h2 { font-size: .75rem; font-weight: 700; text-transform: uppercase;
              letter-spacing: .08em; color: var(--muted); margin: 1.5rem 0 .4rem; }
    nav h2:first-child { margin-top: 0; }
    nav a { display: block; padding: .3rem .6rem; border-radius: 5px;
            color: var(--text); text-decoration: none; font-size: .9rem; }
    nav a:hover { background: var(--border); }
    main { flex: 1; max-width: 860px; padding: 2.5rem 2rem; }
    h1 { font-size: 2rem; font-weight: 800; margin-bottom: .5rem; }
    h2 { font-size: 1.35rem; font-weight: 700; margin: 2.5rem 0 .75rem;
         padding-top: 2rem; border-top: 1px solid var(--border); }
    h2:first-of-type { border-top: none; padding-top: 0; }
    h3 { font-size: 1.05rem; font-weight: 600; margin: 1.5rem 0 .5rem; }
    p  { margin: .6rem 0; color: var(--text); }
    a  { color: var(--accent); }
    code { background: var(--code-bg); padding: .15em .4em; border-radius: 4px;
           font-size: .88em; font-family: "SF Mono", "Fira Code", monospace; }
    pre { background: var(--code-bg); border: 1px solid var(--border);
          border-radius: var(--radius); padding: 1.1rem 1.2rem; overflow-x: auto;
          margin: .8rem 0; font-size: .85rem;
          font-family: "SF Mono", "Fira Code", monospace; line-height: 1.55; }
    table { width: 100%; border-collapse: collapse; font-size: .88rem; margin: .8rem 0; }
    th { background: var(--surface); text-align: left; padding: .5rem .75rem;
         border: 1px solid var(--border); font-weight: 600; }
    td { padding: .45rem .75rem; border: 1px solid var(--border); vertical-align: top; }
    tr:nth-child(even) td { background: var(--surface); }
    .badge { display: inline-block; padding: .15em .55em; border-radius: 4px;
             font-size: .78rem; font-weight: 600; font-family: monospace; }
    .post  { background: #dcfce7; color: #15803d; }
    .get   { background: #dbeafe; color: #1d4ed8; }
    .del   { background: #fee2e2; color: #dc2626; }
    .hero-desc { font-size: 1.05rem; color: var(--muted); margin-bottom: 1.5rem; }
    .lang-toggle { float: right; font-size: .85rem; }
    .lang-toggle button { background: none; border: 1px solid var(--border);
      border-radius: 5px; padding: .25rem .6rem; cursor: pointer; margin-left: .3rem;
      font-size: .82rem; color: var(--text); }
    .lang-toggle button.active { background: var(--accent); color: #fff; border-color: var(--accent); }
    .feature-grid { display: grid; grid-template-columns: 1fr 1fr; gap: .6rem; margin: .8rem 0; }
    .feature { background: var(--surface); border: 1px solid var(--border);
               border-radius: var(--radius); padding: .65rem .9rem; font-size: .9rem; }
    .quick-links { display: flex; gap: .6rem; flex-wrap: wrap; margin: 1rem 0; }
    .quick-links a { background: var(--accent); color: #fff; text-decoration: none;
                     padding: .45rem 1rem; border-radius: var(--radius); font-size: .9rem;
                     font-weight: 500; }
    .quick-links a.secondary { background: var(--surface); color: var(--text);
                                border: 1px solid var(--border); }
    [data-lang] { display: none; }
    [data-lang].visible { display: block; }
    @media (max-width: 700px) {
      nav { display: none; } main { padding: 1.5rem 1rem; }
      .feature-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
<div class="layout">

<nav>
  <h2 id="nav-overview-label">Overview</h2>
  <a href="#features">Features</a>
  <a href="#quickstart">Quick start</a>
  <h2 id="nav-endpoints-label">Endpoints</h2>
  <a href="#process"><span class="badge post">POST</span> /api/process</a>
  <a href="#ocr-pdf"><span class="badge post">POST</span> /api/ocr-pdf</a>
  <a href="#status"><span class="badge get">GET</span> /api/status</a>
  <a href="#books"><span class="badge get">GET</span> /api/books</a>
  <a href="#download"><span class="badge get">GET</span> /api/books/{name}/download</a>
  <a href="#events"><span class="badge get">GET</span> /api/events</a>
  <a href="#cancel"><span class="badge del">DEL</span> /api/cancel</a>
  <h2 id="nav-ref-label">Reference</h2>
  <a href="#engines" id="nav-engines">Engines</a>
  <a href="#formats" id="nav-formats">Formats</a>
  <a href="#event-types" id="nav-events">Event types</a>
  <a href="#cli" id="nav-cli">CLI</a>
  <a href="#tui" id="nav-tui">TUI</a>
</nav>

<main>

<div class="lang-toggle">
  <button class="active" onclick="setLang('es')" id="btn-es">ES</button>
  <button onclick="setLang('en')" id="btn-en">EN</button>
</div>

<h1>📄 libros2pdf</h1>

<!-- ESPAÑOL -->
<div data-lang="es" class="visible">

<p class="hero-desc">Convierte imágenes escaneadas de libros históricos en PDFs con capa OCR de texto.</p>

<div class="quick-links">
  <a href="/docs">Swagger UI</a>
  <a href="/api/status" class="secondary">Estado actual</a>
  <a href="/api/books" class="secondary">Libros</a>
</div>

<h2 id="features">Características</h2>
<div class="feature-grid">
  <div class="feature">⚙️ <strong>5 motores OCR</strong><br>Tesseract, Ollama, OpenRouter, Claude, OpenAI</div>
  <div class="feature">🖼️ <strong>Imágenes → PDF+OCR</strong><br>Un PDF por subcarpeta, ordenación natural</div>
  <div class="feature">📄 <strong>PDF → PDF+OCR</strong><br>Añade capa de texto a PDFs existentes</div>
  <div class="feature">📦 <strong>3 formatos de salida</strong><br>PDF estándar, PDF/A-2b, comprimido</div>
  <div class="feature">🔄 <strong>Reanudable</strong><br>Estado guardado tras cada página</div>
  <div class="feature">⚡ <strong>Paralelo</strong><br>Workers configurables para APIs de visión</div>
  <div class="feature">🔌 <strong>SSE en tiempo real</strong><br>Progreso página a página vía Server-Sent Events</div>
  <div class="feature">✅ <strong>Verificación</strong><br>Integridad comprobada antes de marcar completado</div>
</div>

<h2 id="quickstart">Inicio rápido</h2>
<h3>Imágenes → PDF</h3>
<pre>curl -X POST http://localhost:8000/api/process \\
  -H "Content-Type: application/json" \\
  -d '{
    "input_dir":  "/ruta/a/escaneos",
    "output_dir": "/ruta/a/salida",
    "engine":     "openrouter",
    "model":      "google/gemini-2.5-flash-lite",
    "api_key":    "sk-or-v1-...",
    "pdf_format": "pdf",
    "workers":    5
  }'</pre>

<h3>PDF existente → añadir OCR</h3>
<pre>curl -X POST http://localhost:8000/api/ocr-pdf \\
  -H "Content-Type: application/json" \\
  -d '{
    "input_dir":  "/ruta/a/pdfs",
    "engine":     "openrouter",
    "model":      "google/gemini-2.5-flash-lite",
    "api_key":    "sk-or-v1-...",
    "pdf_format": "compressed"
  }'</pre>

<h3>Escuchar eventos en tiempo real</h3>
<pre>curl -N http://localhost:8000/api/events</pre>

<h2 id="process"><span class="badge post">POST</span> /api/process</h2>
<p>Inicia el procesamiento de un directorio de imágenes en segundo plano. Devuelve un <code>job_id</code> para seguir el progreso.</p>
<h3>Cuerpo de la petición</h3>
<table>
<tr><th>Campo</th><th>Tipo</th><th>Por defecto</th><th>Descripción</th></tr>
<tr><td><code>input_dir</code></td><td>string</td><td><strong>requerido</strong></td><td>Directorio con imágenes o subcarpetas</td></tr>
<tr><td><code>output_dir</code></td><td>string</td><td>padre de entrada</td><td>Directorio de salida</td></tr>
<tr><td><code>engine</code></td><td>string</td><td><code>tesseract</code></td><td><code>tesseract</code>, <code>claude</code>, <code>openai</code>, <code>openrouter</code>, <code>ollama</code></td></tr>
<tr><td><code>model</code></td><td>string</td><td>según motor</td><td>Nombre del modelo (ej. <code>google/gemini-2.5-flash-lite</code>)</td></tr>
<tr><td><code>api_key</code></td><td>string</td><td>variable entorno</td><td>API key del backend</td></tr>
<tr><td><code>base_url</code></td><td>string</td><td>según motor</td><td>URL base personalizada (OpenRouter, Ollama…)</td></tr>
<tr><td><code>lang</code></td><td>string</td><td><code>spa+lat</code></td><td>Idiomas Tesseract separados por <code>+</code></td></tr>
<tr><td><code>psm</code></td><td>int</td><td><code>6</code></td><td>Page segmentation mode de Tesseract (3=auto, 6=bloque)</td></tr>
<tr><td><code>dpi</code></td><td>int</td><td><code>250</code></td><td>Resolución para rasterizar</td></tr>
<tr><td><code>workers</code></td><td>int</td><td><code>5</code></td><td>Workers paralelos (ignorado con Tesseract)</td></tr>
<tr><td><code>pdf_format</code></td><td>string</td><td><code>pdf</code></td><td><code>pdf</code>, <code>pdf_a</code> o <code>compressed</code></td></tr>
<tr><td><code>ocr_prompt</code></td><td>string</td><td>incorporado</td><td>Prompt personalizado para el modelo de visión</td></tr>
<tr><td><code>skip_ocr</code></td><td>bool</td><td><code>false</code></td><td>PDF solo imagen, sin capa OCR</td></tr>
<tr><td><code>force</code></td><td>bool</td><td><code>false</code></td><td>Ignorar estado guardado y reprocesar</td></tr>
<tr><td><code>delete_originals</code></td><td>bool</td><td><code>false</code></td><td>Eliminar imágenes originales tras verificar (<strong>irreversible</strong>)</td></tr>
<tr><td><code>tessdata</code></td><td>string</td><td>null</td><td>TESSDATA_PREFIX personalizado</td></tr>
</table>
<h3>Respuesta</h3>
<pre>{ "job_id": "a3f7c1b2", "status": "queued", "books": 12, "total_pages": 1840 }</pre>

<h2 id="ocr-pdf"><span class="badge post">POST</span> /api/ocr-pdf</h2>
<p>Añade una capa OCR a PDFs ya existentes. Acepta un archivo PDF individual o un directorio de PDFs.</p>
<h3>Cuerpo de la petición</h3>
<table>
<tr><th>Campo</th><th>Tipo</th><th>Por defecto</th><th>Descripción</th></tr>
<tr><td><code>input_dir</code></td><td>string</td><td><strong>requerido</strong></td><td>Archivo PDF o directorio de PDFs</td></tr>
<tr><td><code>output_dir</code></td><td>string</td><td>null</td><td>Directorio de salida (por defecto: <code>&lt;entrada&gt;_OCR</code>)</td></tr>
<tr><td><code>engine</code></td><td>string</td><td><code>openrouter</code></td><td>Motor OCR</td></tr>
<tr><td><code>model</code></td><td>string</td><td>según motor</td><td>Nombre del modelo</td></tr>
<tr><td><code>api_key</code></td><td>string</td><td>variable entorno</td><td>API key</td></tr>
<tr><td><code>base_url</code></td><td>string</td><td>según motor</td><td>URL base personalizada</td></tr>
<tr><td><code>ocr_prompt</code></td><td>string</td><td>incorporado</td><td>Prompt personalizado</td></tr>
<tr><td><code>dpi</code></td><td>int</td><td><code>250</code></td><td>Resolución</td></tr>
<tr><td><code>workers</code></td><td>int</td><td><code>3</code></td><td>Workers paralelos</td></tr>
<tr><td><code>pdf_format</code></td><td>string</td><td><code>pdf</code></td><td><code>pdf</code>, <code>pdf_a</code> o <code>compressed</code></td></tr>
</table>

<h2 id="status"><span class="badge get">GET</span> /api/status</h2>
<p>Devuelve el estado de todos los jobs activos y completados.</p>
<pre>GET /api/status

{
  "jobs": [
    {
      "job_id": "a3f7c1b2",
      "status": "running",
      "books_completed": 3,
      "books_total": 12,
      "pages_done": 420,
      "pages_total": 1840,
      "current_book": "BAUTISMOS 04. 1881-1885",
      "elapsed": 312,
      "created": "2026-04-30T10:00:00"
    }
  ]
}</pre>

<h2 id="books"><span class="badge get">GET</span> /api/books</h2>
<p>Lista los PDFs generados y, opcionalmente, los libros de entrada con su estado.</p>
<pre>GET /api/books?output_dir=./PDF_LIBROS&amp;input_dir=./escaneos</pre>
<table>
<tr><th>Parámetro</th><th>Por defecto</th><th>Descripción</th></tr>
<tr><td><code>output_dir</code></td><td><code>PDF_LIBROS</code></td><td>Directorio de salida</td></tr>
<tr><td><code>input_dir</code></td><td>—</td><td>Directorio de entrada (opcional, para ver pendientes)</td></tr>
</table>

<h2 id="download"><span class="badge get">GET</span> /api/books/{nombre}/download</h2>
<p>Descarga un PDF generado por su nombre (con o sin extensión <code>.pdf</code>).</p>
<pre>GET /api/books/BAUTISMOS%2001.%201850-1860/download?output_dir=./PDF_LIBROS</pre>

<h2 id="events"><span class="badge get">GET</span> /api/events</h2>
<p>Stream <strong>Server-Sent Events</strong> con el progreso en tiempo real de todos los jobs activos. Cada mensaje es un JSON.</p>
<pre>curl -N http://localhost:8000/api/events

data: {"kind":"BOOK_START","book":"BAUTISMOS 01","total":331,"ts":1714467600.1}
data: {"kind":"PAGE_OK","book":"BAUTISMOS 01","page":0,"total":331,"file":"IMG_0001.JPG","ts":1714467602.4}
data: {"kind":"PAGE_OK","book":"BAUTISMOS 01","page":1,"total":331,"file":"IMG_0002.JPG","ts":1714467604.8}
...</pre>

<h2 id="cancel"><span class="badge del">DEL</span> /api/cancel</h2>
<p>Cancela un job activo. Sin <code>job_id</code> cancela el último activo.</p>
<pre>DELETE /api/cancel?job_id=a3f7c1b2</pre>

<h2 id="engines">Motores OCR</h2>
<table>
<tr><th>Motor</th><th>Tipo</th><th>Calidad manuscrito</th><th>Coste</th><th>Velocidad</th></tr>
<tr><td><code>tesseract</code></td><td>Local</td><td>★★☆☆☆</td><td>Gratis</td><td>Rápido (secuencial)</td></tr>
<tr><td><code>ollama</code></td><td>Local</td><td>★★★☆☆</td><td>Gratis</td><td>Medio</td></tr>
<tr><td><code>openrouter</code></td><td>Cloud</td><td>★★★★★</td><td>~$0,001/pág</td><td>Rápido (paralelo)</td></tr>
<tr><td><code>claude</code></td><td>Cloud</td><td>★★★★★</td><td>~$0,001/pág</td><td>Rápido (paralelo)</td></tr>
<tr><td><code>openai</code></td><td>Cloud</td><td>★★★★☆</td><td>~$0,001/pág</td><td>Rápido (paralelo)</td></tr>
</table>

<h2 id="formats">Formatos de salida</h2>
<table>
<tr><th>Valor</th><th>Descripción</th></tr>
<tr><td><code>pdf</code></td><td>PDF estándar con imagen + capa OCR invisible. Máxima fidelidad.</td></tr>
<tr><td><code>pdf_a</code></td><td>PDF/A-2b conforme a ISO 19005-2. Recomendado para preservación archivística.</td></tr>
<tr><td><code>compressed</code></td><td>Imagen recomprimida vía WebP→JPEG. Reduce ~50% el tamaño con pérdida mínima.</td></tr>
</table>

<h2 id="event-types">Tipos de eventos SSE</h2>
<table>
<tr><th>Tipo (<code>kind</code>)</th><th>Campos clave</th><th>Descripción</th></tr>
<tr><td><code>BOOK_START</code></td><td><code>book</code>, <code>total</code></td><td>Inicio del procesamiento de un libro</td></tr>
<tr><td><code>PAGE_OK</code></td><td><code>book</code>, <code>page</code>, <code>total</code>, <code>file</code></td><td>Página OCR completada</td></tr>
<tr><td><code>PAGE_FAIL</code></td><td><code>book</code>, <code>page</code>, <code>file</code></td><td>Fallo en la página</td></tr>
<tr><td><code>MERGE_START</code></td><td><code>book</code></td><td>Uniendo páginas en PDF final</td></tr>
<tr><td><code>BOOK_DONE</code></td><td><code>book</code>, <code>pages</code>, <code>size_mb</code></td><td>Libro completado</td></tr>
<tr><td><code>VERIFY_OK</code> / <code>VERIFY_FAIL</code></td><td><code>book</code>, <code>file</code></td><td>Resultado verificación de integridad</td></tr>
<tr><td><code>ALL_DONE</code></td><td><code>result</code></td><td>Todo el procesamiento completado</td></tr>
<tr><td><code>LOG</code></td><td><code>message</code></td><td>Mensaje informativo</td></tr>
<tr><td><code>ping</code></td><td>—</td><td>Keepalive cada 10 s</td></tr>
</table>

<h2 id="cli">CLI</h2>
<pre># Imágenes → PDF (Tesseract)
python3 -m libros2pdf ./escaneos ./salida

# Imágenes → PDF (OpenRouter)
python3 -m libros2pdf ./escaneos ./salida \\
  --engine openrouter --model google/gemini-2.5-flash-lite \\
  --api-key sk-or-v1-... --workers 5 --format compressed

# PDF existente → añadir OCR
python3 -m libros2pdf ocr-pdf ./pdfs ./pdfs_ocr \\
  --engine openrouter --model google/gemini-2.5-flash-lite \\
  --api-key sk-or-v1-...

# Iniciar servidor API
python3 -m libros2pdf serve --host 0.0.0.0 --port 8000

# Ver estado
python3 -m libros2pdf status ./salida ./escaneos

# TUI interactiva
python3 -m libros2pdf tui</pre>

<h2 id="tui">TUI</h2>
<p>Interfaz interactiva de terminal con barras de progreso por libro, log en vivo y control total del proceso.</p>
<pre>python3 -m libros2pdf</pre>
<p>La TUI incluye: selector de motor y modelo, validación de API key, configuración de prompt personalizado, selector de formato de salida, y visualización del estado de todos los libros.</p>

</div>
<!-- END ESPAÑOL -->

<!-- ENGLISH -->
<div data-lang="en">

<p class="hero-desc">Convert scanned historical book images into searchable PDFs with an OCR text layer.</p>

<div class="quick-links">
  <a href="/docs">Swagger UI</a>
  <a href="/api/status" class="secondary">Current status</a>
  <a href="/api/books" class="secondary">Books</a>
</div>

<h2 id="features-en">Features</h2>
<div class="feature-grid">
  <div class="feature">⚙️ <strong>5 OCR backends</strong><br>Tesseract, Ollama, OpenRouter, Claude, OpenAI</div>
  <div class="feature">🖼️ <strong>Images → PDF+OCR</strong><br>One PDF per sub-folder, natural sort</div>
  <div class="feature">📄 <strong>PDF → PDF+OCR</strong><br>Add a text layer to existing PDFs</div>
  <div class="feature">📦 <strong>3 output formats</strong><br>Standard PDF, PDF/A-2b, compressed</div>
  <div class="feature">🔄 <strong>Resumable</strong><br>State saved after every page</div>
  <div class="feature">⚡ <strong>Parallel</strong><br>Configurable workers for vision APIs</div>
  <div class="feature">🔌 <strong>Real-time SSE</strong><br>Page-by-page progress via Server-Sent Events</div>
  <div class="feature">✅ <strong>Integrity check</strong><br>Every PDF verified before marking done</div>
</div>

<h2>Quick start</h2>
<h3>Images → PDF</h3>
<pre>curl -X POST http://localhost:8000/api/process \\
  -H "Content-Type: application/json" \\
  -d '{
    "input_dir":  "/path/to/scans",
    "output_dir": "/path/to/output",
    "engine":     "openrouter",
    "model":      "google/gemini-2.5-flash-lite",
    "api_key":    "sk-or-v1-...",
    "pdf_format": "pdf",
    "workers":    5
  }'</pre>

<h3>Existing PDF → add OCR</h3>
<pre>curl -X POST http://localhost:8000/api/ocr-pdf \\
  -H "Content-Type: application/json" \\
  -d '{
    "input_dir":  "/path/to/pdfs",
    "engine":     "openrouter",
    "model":      "google/gemini-2.5-flash-lite",
    "api_key":    "sk-or-v1-...",
    "pdf_format": "compressed"
  }'</pre>

<h3>Listen to real-time events</h3>
<pre>curl -N http://localhost:8000/api/events</pre>

<h2><span class="badge post">POST</span> /api/process</h2>
<p>Start a background job to convert image folders into PDFs. Returns a <code>job_id</code> for tracking.</p>
<h3>Request body</h3>
<table>
<tr><th>Field</th><th>Type</th><th>Default</th><th>Description</th></tr>
<tr><td><code>input_dir</code></td><td>string</td><td><strong>required</strong></td><td>Directory with images or sub-folders</td></tr>
<tr><td><code>output_dir</code></td><td>string</td><td>parent of input</td><td>Output directory</td></tr>
<tr><td><code>engine</code></td><td>string</td><td><code>tesseract</code></td><td><code>tesseract</code>, <code>claude</code>, <code>openai</code>, <code>openrouter</code>, <code>ollama</code></td></tr>
<tr><td><code>model</code></td><td>string</td><td>per engine</td><td>Model name (e.g. <code>google/gemini-2.5-flash-lite</code>)</td></tr>
<tr><td><code>api_key</code></td><td>string</td><td>env var</td><td>Backend API key</td></tr>
<tr><td><code>base_url</code></td><td>string</td><td>per engine</td><td>Custom API base URL (OpenRouter, Ollama…)</td></tr>
<tr><td><code>lang</code></td><td>string</td><td><code>spa+lat</code></td><td>Tesseract languages joined by <code>+</code></td></tr>
<tr><td><code>psm</code></td><td>int</td><td><code>6</code></td><td>Tesseract page segmentation mode (3=auto, 6=block)</td></tr>
<tr><td><code>dpi</code></td><td>int</td><td><code>250</code></td><td>Target rasterisation DPI</td></tr>
<tr><td><code>workers</code></td><td>int</td><td><code>5</code></td><td>Parallel workers (ignored for Tesseract)</td></tr>
<tr><td><code>pdf_format</code></td><td>string</td><td><code>pdf</code></td><td><code>pdf</code>, <code>pdf_a</code>, or <code>compressed</code></td></tr>
<tr><td><code>ocr_prompt</code></td><td>string</td><td>built-in</td><td>Custom prompt for vision model</td></tr>
<tr><td><code>skip_ocr</code></td><td>bool</td><td><code>false</code></td><td>Image-only PDF, skip OCR</td></tr>
<tr><td><code>force</code></td><td>bool</td><td><code>false</code></td><td>Ignore saved state and reprocess</td></tr>
<tr><td><code>delete_originals</code></td><td>bool</td><td><code>false</code></td><td>Delete source images after verifying PDF (<strong>irreversible</strong>)</td></tr>
<tr><td><code>tessdata</code></td><td>string</td><td>null</td><td>Custom TESSDATA_PREFIX</td></tr>
</table>
<h3>Response</h3>
<pre>{ "job_id": "a3f7c1b2", "status": "queued", "books": 12, "total_pages": 1840 }</pre>

<h2><span class="badge post">POST</span> /api/ocr-pdf</h2>
<p>Add an OCR layer to existing PDFs. Accepts a single PDF file or a directory.</p>
<h3>Request body</h3>
<table>
<tr><th>Field</th><th>Type</th><th>Default</th><th>Description</th></tr>
<tr><td><code>input_dir</code></td><td>string</td><td><strong>required</strong></td><td>PDF file or directory of PDFs</td></tr>
<tr><td><code>output_dir</code></td><td>string</td><td>null</td><td>Output directory (default: <code>&lt;input&gt;_OCR</code>)</td></tr>
<tr><td><code>engine</code></td><td>string</td><td><code>openrouter</code></td><td>OCR backend</td></tr>
<tr><td><code>model</code></td><td>string</td><td>per engine</td><td>Model name</td></tr>
<tr><td><code>api_key</code></td><td>string</td><td>env var</td><td>API key</td></tr>
<tr><td><code>base_url</code></td><td>string</td><td>per engine</td><td>Custom API base URL</td></tr>
<tr><td><code>ocr_prompt</code></td><td>string</td><td>built-in</td><td>Custom prompt</td></tr>
<tr><td><code>dpi</code></td><td>int</td><td><code>250</code></td><td>Target DPI</td></tr>
<tr><td><code>workers</code></td><td>int</td><td><code>3</code></td><td>Parallel workers</td></tr>
<tr><td><code>pdf_format</code></td><td>string</td><td><code>pdf</code></td><td><code>pdf</code>, <code>pdf_a</code>, or <code>compressed</code></td></tr>
</table>

<h2><span class="badge get">GET</span> /api/status</h2>
<p>Returns all active and completed jobs with their progress.</p>
<pre>GET /api/status

{
  "jobs": [
    {
      "job_id": "a3f7c1b2",
      "status": "running",
      "books_completed": 3, "books_total": 12,
      "pages_done": 420,    "pages_total": 1840,
      "current_book": "BAPTISMS 04. 1881-1885",
      "elapsed": 312,
      "created": "2026-04-30T10:00:00"
    }
  ]
}</pre>

<h2><span class="badge get">GET</span> /api/books</h2>
<p>Lists generated PDFs and optionally input books with their processing state.</p>
<pre>GET /api/books?output_dir=./PDF_LIBROS&amp;input_dir=./scans</pre>

<h2><span class="badge get">GET</span> /api/books/{name}/download</h2>
<p>Download a generated PDF by name (with or without <code>.pdf</code> extension).</p>
<pre>GET /api/books/BAPTISMS%2001.%201850-1860/download?output_dir=./PDF_LIBROS</pre>

<h2><span class="badge get">GET</span> /api/events</h2>
<p><strong>Server-Sent Events</strong> stream with real-time progress for all active jobs. Each message is JSON.</p>
<pre>curl -N http://localhost:8000/api/events

data: {"kind":"BOOK_START","book":"BAPTISMS 01","total":331,"ts":1714467600.1}
data: {"kind":"PAGE_OK","book":"BAPTISMS 01","page":0,"total":331,"file":"IMG_0001.JPG","ts":1714467602.4}
...</pre>

<h2><span class="badge del">DEL</span> /api/cancel</h2>
<p>Cancel an active job. Without <code>job_id</code>, cancels the most recent active job.</p>
<pre>DELETE /api/cancel?job_id=a3f7c1b2</pre>

<h2>OCR Engines</h2>
<table>
<tr><th>Engine</th><th>Type</th><th>Manuscript quality</th><th>Cost</th><th>Speed</th></tr>
<tr><td><code>tesseract</code></td><td>Local</td><td>★★☆☆☆</td><td>Free</td><td>Fast (sequential)</td></tr>
<tr><td><code>ollama</code></td><td>Local</td><td>★★★☆☆</td><td>Free</td><td>Medium</td></tr>
<tr><td><code>openrouter</code></td><td>Cloud</td><td>★★★★★</td><td>~$0.001/page</td><td>Fast (parallel)</td></tr>
<tr><td><code>claude</code></td><td>Cloud</td><td>★★★★★</td><td>~$0.001/page</td><td>Fast (parallel)</td></tr>
<tr><td><code>openai</code></td><td>Cloud</td><td>★★★★☆</td><td>~$0.001/page</td><td>Fast (parallel)</td></tr>
</table>

<h2>Output formats</h2>
<table>
<tr><th>Value</th><th>Description</th></tr>
<tr><td><code>pdf</code></td><td>Standard PDF with image + invisible OCR layer. Maximum fidelity.</td></tr>
<tr><td><code>pdf_a</code></td><td>PDF/A-2b, ISO 19005-2 compliant. Best for long-term archival.</td></tr>
<tr><td><code>compressed</code></td><td>Image recompressed via WebP→JPEG. ~50% size reduction with minimal visual loss.</td></tr>
</table>

<h2>SSE event types</h2>
<table>
<tr><th><code>kind</code></th><th>Key fields</th><th>Description</th></tr>
<tr><td><code>BOOK_START</code></td><td><code>book</code>, <code>total</code></td><td>Book processing started</td></tr>
<tr><td><code>PAGE_OK</code></td><td><code>book</code>, <code>page</code>, <code>total</code>, <code>file</code></td><td>Page OCR succeeded</td></tr>
<tr><td><code>PAGE_FAIL</code></td><td><code>book</code>, <code>page</code>, <code>file</code></td><td>Page OCR failed</td></tr>
<tr><td><code>MERGE_START</code></td><td><code>book</code></td><td>Merging page PDFs into final file</td></tr>
<tr><td><code>BOOK_DONE</code></td><td><code>book</code>, <code>pages</code>, <code>size_mb</code></td><td>Book completed</td></tr>
<tr><td><code>VERIFY_OK</code> / <code>VERIFY_FAIL</code></td><td><code>book</code>, <code>file</code></td><td>PDF integrity check result</td></tr>
<tr><td><code>ALL_DONE</code></td><td><code>result</code></td><td>All processing completed</td></tr>
<tr><td><code>LOG</code></td><td><code>message</code></td><td>Informational message</td></tr>
<tr><td><code>ping</code></td><td>—</td><td>Keepalive every 10 s</td></tr>
</table>

<h2>CLI</h2>
<pre># Images → PDF (Tesseract)
python3 -m libros2pdf ./scans ./output

# Images → PDF (OpenRouter)
python3 -m libros2pdf ./scans ./output \\
  --engine openrouter --model google/gemini-2.5-flash-lite \\
  --api-key sk-or-v1-... --workers 5 --format compressed

# Existing PDF → add OCR
python3 -m libros2pdf ocr-pdf ./pdfs ./pdfs_ocr \\
  --engine openrouter --model google/gemini-2.5-flash-lite \\
  --api-key sk-or-v1-...

# Start API server
python3 -m libros2pdf serve --host 0.0.0.0 --port 8000

# Check status
python3 -m libros2pdf status ./output ./scans

# Interactive TUI
python3 -m libros2pdf tui</pre>

<h2>TUI</h2>
<p>Interactive terminal UI with per-book progress bars, live log, and full process control.</p>
<pre>python3 -m libros2pdf</pre>
<p>The TUI includes: engine and model selector, API key validation, custom prompt editor, output format selector, and a status view of all books.</p>

</div>
<!-- END ENGLISH -->

</main>
</div>

<script>
function setLang(lang) {
  document.querySelectorAll('[data-lang]').forEach(el => {
    el.classList.toggle('visible', el.dataset.lang === lang);
  });
  document.getElementById('btn-es').classList.toggle('active', lang === 'es');
  document.getElementById('btn-en').classList.toggle('active', lang === 'en');
}
</script>
</body>
</html>"""


@app.post("/api/process")
def start_process(req: ProcessRequest):
    """Inicia el procesamiento de un directorio en segundo plano."""
    input_dir = Path(req.input_dir).resolve()

    if not input_dir.is_dir():
        raise HTTPException(400, f"El directorio '{req.input_dir}' no existe")

    output_dir = Path(req.output_dir).resolve() if req.output_dir else input_dir.parent

    output_dir.mkdir(parents=True, exist_ok=True)
    books = scan_books(input_dir)
    if not books:
        raise HTTPException(400, f"No se encontraron imágenes en '{req.input_dir}'")

    job_id = str(uuid.uuid4())[:8]
    cancel_ev = threading.Event()
    _cancel_events[job_id] = cancel_ev

    _jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "created": datetime.now().isoformat(),
        "books_total": len(books),
        "books_completed": 0,
        "pages_total": sum(len(imgs) for _, imgs in books),
        "pages_done": 0,
        "current_book": "",
        "elapsed": 0,
        "_start": time.time(),
    }

    threading.Thread(
        target=_run_job,
        args=(job_id, input_dir, output_dir),
        kwargs=dict(
            lang=req.lang, psm=req.psm, target_dpi=req.dpi,
            tessdata=req.tessdata, force=req.force, skip_ocr=req.skip_ocr,
            engine=req.engine, model=req.model,
            api_key=req.api_key, base_url=req.base_url,
            ocr_prompt=req.ocr_prompt, workers=req.workers,
            delete_originals=req.delete_originals,
            pdf_format=req.pdf_format,
        ),
        daemon=True,
    ).start()

    return {"job_id": job_id, "status": "queued", "books": len(books), "total_pages": sum(len(imgs) for _, imgs in books)}


@app.get("/api/status")
def get_status():
    """Estado de todos los jobs activos."""
    if not _jobs:
        return {"jobs": [], "message": "No hay procesos activos"}
    jobs = []
    for jid, job in list(_jobs.items()):
        elapsed = int(time.time() - job.get("_start", time.time()))
        jobs.append({
            "job_id": jid,
            "status": job.get("status", "unknown"),
            "books_completed": job.get("books_completed", 0),
            "books_total": job.get("books_total", 0),
            "pages_done": job.get("pages_done", 0),
            "pages_total": job.get("pages_total", 0),
            "current_book": job.get("current_book", ""),
            "elapsed": elapsed,
            "created": job.get("created", ""),
            "result": job.get("result"),
            "error": job.get("error"),
        })
    return {"jobs": jobs}


@app.get("/api/books")
def list_books(input_dir: Optional[str] = Query(None, description="Directorio de entrada para escanear"),
               output_dir: str = Query("PDF_LIBROS", description="Directorio de salida")):
    """Lista libros disponibles y PDFs generados."""
    result = {"pdfs": []}

    # PDFs generados
    out_path = Path(output_dir).resolve()
    if out_path.is_dir():
        pdfs = sorted(out_path.glob("*.pdf"), key=lambda p: natural_sort_key(p.stem))
        result["pdfs"] = [
            {"name": p.name, "size_mb": round(p.stat().st_size / (1024 * 1024), 1),
             "path": str(p)}
            for p in pdfs
        ]

    # Input scan
    if input_dir:
        in_path = Path(input_dir).resolve()
        if in_path.is_dir():
            books = scan_books(in_path)
            estado_path = out_path / "estado.json" if out_path.is_dir() else None
            state = load_state(estado_path) if estado_path and estado_path.exists() else {}
            done = set(state.get("done", []))
            progress = state.get("progress", {})

            result["books"] = [
                {"name": name, "pages": len(imgs),
                 "status": "done" if name in done
                           else ("processing" if name in progress else "pending"),
                 "progress": progress.get(name, 0)}
                for name, imgs in books
            ]

    return result


@app.get("/api/books/{name:path}/download")
def download_pdf(name: str, output_dir: str = Query("PDF_LIBROS")):
    """Descarga un PDF generado."""
    out_path = Path(output_dir).resolve()
    pdf = out_path / f"{name}.pdf"
    if Path(name).suffix:
        pdf = out_path / name  # ya viene con extensión

    if not pdf.exists() or pdf.stat().st_size < 500:
        raise HTTPException(404, f"PDF '{name}' no encontrado en {out_path}")

    return FileResponse(str(pdf), media_type="application/pdf",
                        filename=pdf.name)


@app.get("/api/events")
async def event_stream():
    """SSE — Stream de eventos de progreso en tiempo real."""
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    with _queue_lock:
        _event_queues.append(q)

    async def generate():
        try:
            while True:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=10)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'kind': 'ping'})}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            with _queue_lock:
                if q in _event_queues:
                    _event_queues.remove(q)

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "Connection": "keep-alive"})


def _run_ocr_pdf_job(job_id: str, input_dir: Path, output_dir: Path, **kwargs):
    """Ejecuta ocr_pdf_dir en un hilo de fondo y actualiza _jobs."""
    cancel_ev = _cancel_events.get(job_id) or threading.Event()
    q: queue.Queue = queue.Queue()

    job = _jobs[job_id]
    job["status"] = "running"

    def bridge():
        while True:
            try:
                ev = q.get(timeout=1)
            except queue.Empty:
                if _jobs.get(job_id, {}).get("status") in ("completed", "cancelled", "error"):
                    break
                continue
            _broadcast_event(ev)
            d = ev.to_dict()
            if ev.kind == ProgressEvent.PAGE_OK:
                job["pages_done"] = job.get("pages_done", 0) + 1
            elif ev.kind == ProgressEvent.PAGE_FAIL:
                job["pages_done"] = job.get("pages_done", 0) + 1
            elif ev.kind == ProgressEvent.BOOK_DONE:
                job["books_completed"] = job.get("books_completed", 0) + 1
            elif ev.kind == ProgressEvent.ALL_DONE:
                job["status"] = "completed"
                job["result"] = d.get("result")
                break

    bthread = threading.Thread(target=bridge, daemon=True)
    bthread.start()

    try:
        result = ocr_pdf_dir(input_dir, output_dir,
                             event_queue=q, cancel_event=cancel_ev, **kwargs)
        job["result"] = result
        job["status"] = "cancelled" if cancel_ev.is_set() else "completed"
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        _broadcast_event(ProgressEvent(ProgressEvent.LOG, message=f"Error: {e}"))

    job["elapsed"] = int(time.time() - job["_start"])
    bthread.join(timeout=2)


@app.post("/api/ocr-pdf")
def start_ocr_pdf(req: OcrPdfRequest):
    """Aplica OCR a PDFs existentes (PDF → PDF con capa de texto)."""
    input_dir = Path(req.input_dir).resolve()

    if not input_dir.exists():
        raise HTTPException(400, f"La ruta '{req.input_dir}' no existe")

    # Acepta archivo PDF individual o directorio
    if input_dir.is_file():
        if input_dir.suffix.lower() != ".pdf":
            raise HTTPException(400, "El archivo debe ser un PDF")
        pdf_files = [input_dir]
        input_dir = input_dir.parent
    else:
        pdf_files = list(input_dir.glob("*.pdf")) or list(input_dir.glob("**/*.pdf"))

    if not pdf_files:
        raise HTTPException(400, f"No se encontraron PDFs en '{req.input_dir}'")

    output_dir = Path(req.output_dir).resolve() if req.output_dir else input_dir.parent / "PDFs_OCR"
    output_dir.mkdir(parents=True, exist_ok=True)

    job_id = str(uuid.uuid4())[:8]
    cancel_ev = threading.Event()
    _cancel_events[job_id] = cancel_ev

    _jobs[job_id] = {
        "job_id":          job_id,
        "status":          "queued",
        "created":         datetime.now().isoformat(),
        "books_total":     len(pdf_files),
        "books_completed": 0,
        "pages_total":     0,
        "pages_done":      0,
        "current_book":    "",
        "elapsed":         0,
        "_start":          time.time(),
        "type":            "ocr-pdf",
    }

    threading.Thread(
        target=_run_ocr_pdf_job,
        args=(job_id, input_dir, output_dir),
        kwargs=dict(
            engine=req.engine, model=req.model,
            api_key=req.api_key, base_url=req.base_url,
            ocr_prompt=req.ocr_prompt, target_dpi=req.dpi,
            workers=req.workers, pdf_format=req.pdf_format,
        ),
        daemon=True,
    ).start()

    return {
        "job_id": job_id,
        "status": "queued",
        "pdfs":   len(pdf_files),
        "output_dir": str(output_dir),
    }


@app.delete("/api/cancel")
def cancel_process(job_id: Optional[str] = Query(None)):
    """Cancela un proceso activo. Si no se especifica job_id, cancela el último."""
    if job_id:
        ev = _cancel_events.get(job_id)
        if ev:
            ev.set()
            _jobs[job_id]["status"] = "cancelling"
            return {"status": "cancelling", "job_id": job_id}
        raise HTTPException(404, f"Job '{job_id}' no encontrado")

    # Cancelar el último activo
    for jid, job in list(_jobs.items()):
        if job.get("status") in ("running", "queued"):
            ev = _cancel_events.get(jid)
            if ev:
                ev.set()
                job["status"] = "cancelling"
                return {"status": "cancelling", "job_id": jid}

    return {"status": "no_active_jobs"}


# ── Entry point directo ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    print(f"🚀 libros2pdf API — http://127.0.0.1:8000")
    print(f"   📖 Swagger UI: http://127.0.0.1:8000/docs")
    uvicorn.run(app, host="127.0.0.1", port=8000)
