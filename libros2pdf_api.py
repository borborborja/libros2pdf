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
    input_dir:  str
    output_dir: Optional[str] = None
    lang:       str = "spa+lat"
    psm:        int = 6
    dpi:        int = DEFAULT_DPI
    tessdata:   Optional[str] = None
    force:      bool = False
    skip_ocr:   bool = False
    engine:     str = "tesseract"
    model:      Optional[str] = None
    api_key:    Optional[str] = None
    base_url:   Optional[str] = None
    ocr_prompt: Optional[str] = None
    workers:          int  = 5
    delete_originals: bool = False

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
    """Página de resumen con enlaces."""
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>libros2pdf API</title>
  <style>
    body {{ font-family: -apple-system, sans-serif; max-width: 640px; margin: 2em auto; padding: 0 1em; }}
    a {{ color: #2563eb; }}
    .endpoint {{ background: #f4f4f5; padding: 0.5em 1em; border-radius: 8px; margin: 0.5em 0; }}
    code {{ font-size: 1.1em; }}
  </style>
</head>
<body>
  <h1>📄 libros2pdf API</h1>
  <p>API para procesar imágenes de libros parroquiales → PDFs con OCR.</p>

  <div class="endpoint"><code><a href="/docs">📖 /docs</a></code> — Swagger UI (documentación interactiva)</div>
  <div class="endpoint"><code><a href="/api/status">📊 /api/status</a></code> — Estado actual del procesamiento</div>
  <div class="endpoint"><code><a href="/api/books">📚 /api/books</a></code> — Libros escaneados y PDFs generados</div>
  <div class="endpoint"><code>📥 /api/books/&#123;nombre&#125;/download</code> — Descargar PDF</div>
  <div class="endpoint"><code>🔌 /api/events</code> — SSE de eventos en tiempo real</div>

  <h2>🚀 Iniciar proceso</h2>
  <pre style="background:#f4f4f5;padding:1em;border-radius:8px;overflow-x:auto;">
curl -X POST http://localhost:8000/api/process \\
  -H "Content-Type: application/json" \\
  -d '{{
    "input_dir": "/ruta/a/bautismos",
    "output_dir": "./PDF_LIBROS",
    "lang": "spa+lat",
    "psm": 6
  }}'</pre>
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
