"""
libros2pdf — Procesa imágenes de libros parroquiales y genera PDFs con OCR.

Uso CLI:
    python3 -m libros2pdf <directorio> [salida]
    python3 -m libros2pdf serve                # Inicia API REST

Ejemplo:
    python3 -m libros2pdf ./bautismos ./PDFs
"""

import os, sys, json, subprocess, time, io, re, threading, queue, base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from PIL import Image, ImageOps
import pikepdf

__version__ = "1.0.0"

# ── Constantes por defecto ───────────────────────────────────────────────────────

DEFAULT_DPI  = 250
PAGE_TIMEOUT = 120   # segundos (solo Tesseract)
COMPRESS_PDF = True

# Prompt para backends de visión (Claude, OpenAI, OpenRouter, Ollama…)
DEFAULT_VISION_PROMPT = """\
Transcribe exactamente el texto visible en este documento histórico manuscrito.

- Copia el texto tal como aparece: respeta ortografía original, tildes y abreviaturas (Dn., Dña., Nro., fol., idem…)
- Si hay texto en latín, transcríbelo literalmente sin traducir
- Conserva la estructura: saltos de línea, párrafos y numeración de actas
- Marca palabras ilegibles como [ilegible] y palabras dudosas como [palabra?]
- Devuelve ÚNICAMENTE el texto transcrito, sin comentarios ni explicaciones\
"""

# Configuración por defecto para cada motor OCR
ENGINE_DEFAULTS: dict = {
    "tesseract":  {},
    "claude":     {"model": "claude-haiku-4-5-20251001"},
    "openai":     {"model": "gpt-4o-mini"},
    "openrouter": {
        "model":    "google/gemini-2.5-flash-lite",
        "base_url": "https://openrouter.ai/api/v1",
    },
    "ollama": {
        "model":    "llava:13b",
        "base_url": "http://localhost:11434/v1",
        "api_key":  "ollama",
    },
}


# ── Eventos de progreso (compartido entre CLI y API) ────────────────────────────

class ProgressEvent:
    PAGE_OK      = "page_ok"
    PAGE_FAIL    = "page_fail"
    BOOK_START   = "book_start"
    BOOK_DONE    = "book_done"
    BOOK_FAIL    = "book_fail"
    MERGE_START  = "merge_start"
    MERGE_DONE   = "merge_done"
    VERIFY_OK    = "verify_ok"
    VERIFY_FAIL  = "verify_fail"
    ALL_DONE     = "all_done"
    LOG          = "log"

    def __init__(self, kind: str, **data):
        self.kind = kind
        self.data = data
        self.ts   = time.time()

    def to_dict(self):
        return {"kind": self.kind, "ts": self.ts, **self.data}


# ── Ordenación natural ───────────────────────────────────────────────────────────

def natural_sort_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', str(s))]


# ── Escaneo de directorios ───────────────────────────────────────────────────────

def scan_books(input_dir: Path):
    """
    Devuelve lista de (book_id: str, images: list[Path]).
    Cada subdirectorio con imágenes es un libro; si no hay subdirectorios,
    el propio input_dir se trata como un único libro.
    """
    dirs = sorted(
        [d for d in input_dir.iterdir() if d.is_dir()],
        key=lambda d: natural_sort_key(d.name),
    )
    result = []
    for d in dirs:
        imgs = sorted(
            [f for f in d.iterdir()
             if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".tif", ".tiff")],
            key=natural_sort_key,
        )
        if imgs:
            result.append((d.name, imgs))

    if not result:
        imgs = sorted(
            [f for f in input_dir.iterdir()
             if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".tif", ".tiff")],
            key=natural_sort_key,
        )
        if imgs:
            result.append((input_dir.name, imgs))
    return result


# ── Estado persistente ───────────────────────────────────────────────────────────

def load_state(path: Path):
    if path.exists():
        return json.loads(path.read_text())
    return {"done": [], "progress": {}}


def save_state(state, path: Path):
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False))


# ── Preprocesado de imagen ───────────────────────────────────────────────────────

def preprocess_image(img: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(img) or img
    return img.convert("L")


# ── Backend: Tesseract ───────────────────────────────────────────────────────────

def _run_tesseract(img_data: bytes, output_stem: str, *,
                   lang: str = "spa+lat",
                   psm: int = 6,
                   tessdata: Optional[str] = None,
                   target_dpi: int = DEFAULT_DPI) -> bool:
    env = {**os.environ}
    if tessdata:
        env["TESSDATA_PREFIX"] = tessdata

    cmd = ["tesseract", "stdin", output_stem,
           "-l", lang, "--psm", str(psm), "--oem", "1", "pdf",
           "-c", f"page_dpi={target_dpi}"]
    try:
        subprocess.run(cmd, input=img_data, capture_output=True,
                       env=env, timeout=PAGE_TIMEOUT)
        return True
    except (subprocess.TimeoutExpired, Exception):
        return False


# ── Backend: Claude (Anthropic) ──────────────────────────────────────────────────

def _ocr_via_anthropic(img_data: bytes, *,
                        model: str = "claude-haiku-4-5-20251001",
                        api_key: Optional[str] = None,
                        prompt: Optional[str] = None) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image",
                 "source": {"type": "base64",
                            "media_type": "image/jpeg",
                            "data": base64.b64encode(img_data).decode()}},
                {"type": "text", "text": prompt or DEFAULT_VISION_PROMPT},
            ],
        }],
    )
    return response.content[0].text


# ── Backend: OpenAI-compatible (OpenAI, OpenRouter, Ollama) ─────────────────────

def _ocr_via_openai_compat(img_data: bytes, *,
                            model: str,
                            api_key: Optional[str] = None,
                            base_url: Optional[str] = None,
                            prompt: Optional[str] = None) -> str:
    from openai import OpenAI
    client = OpenAI(
        api_key=api_key or os.environ.get("OPENAI_API_KEY", "none"),
        base_url=base_url,
    )
    img_b64 = base64.b64encode(img_data).decode()
    response = client.chat.completions.create(
        model=model,
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{img_b64}",
                               "detail": "high"}},
                {"type": "text", "text": prompt or DEFAULT_VISION_PROMPT},
            ],
        }],
    )
    return response.choices[0].message.content


# ── PDF con capa de texto invisible (para backends de visión) ────────────────────

def _build_searchable_pdf(img_data: bytes, text: str,
                           out_pdf: Path, actual_dpi: int) -> bool:
    """
    Crea un PDF con la imagen como fondo y el texto OCR como capa invisible
    pero buscable (render_mode=3). Requiere pymupdf; si no está instalado,
    genera un PDF solo-imagen como fallback.
    """
    try:
        import fitz  # pymupdf
        img = Image.open(io.BytesIO(img_data))
        w_px, h_px = img.size
        img.close()
        # Píxeles → puntos tipográficos (1 pt = 1/72 pulgada)
        w_pt = w_px * 72 / actual_dpi
        h_pt = h_px * 72 / actual_dpi
        doc  = fitz.open()
        page = doc.new_page(width=w_pt, height=h_pt)
        page.insert_image(page.rect, stream=img_data)
        # render_mode=3 → texto invisible pero seleccionable/buscable en PDF
        page.insert_textbox(page.rect, text, fontsize=8, render_mode=3)
        doc.save(str(out_pdf), garbage=4, deflate=True)
        doc.close()
        return out_pdf.exists() and out_pdf.stat().st_size > 500
    except ImportError:
        # Sin pymupdf: PDF solo imagen (no buscable, pero funcional)
        img = Image.open(io.BytesIO(img_data))
        img.save(str(out_pdf), "PDF", dpi=(actual_dpi, actual_dpi))
        img.close()
        return out_pdf.exists() and out_pdf.stat().st_size > 500
    except Exception:
        return False


# ── Procesar una página ──────────────────────────────────────────────────────────

def process_page(img_path: Path, out_pdf: Path, *,
                 lang: str = "spa+lat",
                 psm: int = 6,
                 tessdata: Optional[str] = None,
                 target_dpi: int = DEFAULT_DPI,
                 skip_ocr: bool = False,
                 engine: str = "tesseract",
                 model: Optional[str] = None,
                 api_key: Optional[str] = None,
                 base_url: Optional[str] = None,
                 ocr_prompt: Optional[str] = None) -> bool:
    try:
        img = Image.open(str(img_path))
        img = preprocess_image(img)

        w, h = img.size
        page_width_inches = 11.69 if w > h else 8.27
        actual_dpi = max(int(w / page_width_inches), 150)

        if skip_ocr:
            img.save(str(out_pdf), "PDF", dpi=(actual_dpi, actual_dpi))
            img.close()
            return out_pdf.exists() and out_pdf.stat().st_size > 500

        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=95, dpi=(actual_dpi, actual_dpi))
        img_data = buf.getvalue()
        buf.close()
        img.close()

        if engine == "tesseract":
            stem = str(out_pdf.with_suffix(""))
            ok = _run_tesseract(img_data, stem, lang=lang, psm=psm,
                                tessdata=tessdata, target_dpi=actual_dpi)
            return ok and out_pdf.exists() and out_pdf.stat().st_size > 500

        # Backend de visión: resolver configuración efectiva
        defaults     = ENGINE_DEFAULTS.get(engine, {})
        eff_model    = model    or defaults.get("model", "")
        eff_base_url = base_url or defaults.get("base_url")
        eff_api_key  = api_key  or defaults.get("api_key")

        if engine == "claude":
            text = _ocr_via_anthropic(img_data, model=eff_model,
                                      api_key=eff_api_key, prompt=ocr_prompt)
        else:  # openai | openrouter | ollama | cualquier compatible
            text = _ocr_via_openai_compat(img_data, model=eff_model,
                                          api_key=eff_api_key, base_url=eff_base_url,
                                          prompt=ocr_prompt)

        return _build_searchable_pdf(img_data, text, out_pdf, actual_dpi)

    except Exception as exc:
        # Re-lanzar errores de rate limit para que _do_page los detecte
        msg = str(exc).lower()
        if "429" in msg or "rate" in msg or "ratelimit" in type(exc).__name__.lower():
            raise
        return False


# ── Test de conectividad del backend ────────────────────────────────────────────

def test_backend(engine: str, *,
                 model: Optional[str] = None,
                 api_key: Optional[str] = None,
                 base_url: Optional[str] = None) -> tuple:
    """
    Comprueba que el backend responde y acepta peticiones de visión.
    Devuelve (ok: bool, mensaje: str).
    Hace una petición mínima (imagen 32×32) para validar autenticación y visión.
    """
    if engine == "tesseract":
        import subprocess
        try:
            r = subprocess.run(["tesseract", "--version"],
                               capture_output=True, timeout=5)
            version = (r.stdout or r.stderr).decode().splitlines()[0]
            return True, f"OK — {version}"
        except FileNotFoundError:
            return False, "tesseract no encontrado en PATH"
        except Exception as exc:
            return False, str(exc)

    if engine == "ollama":
        import urllib.request
        base = (base_url or "http://localhost:11434").rstrip("/").replace("/v1", "")
        try:
            with urllib.request.urlopen(f"{base}/api/tags", timeout=5) as r:
                data = json.loads(r.read())
            names = [m["name"] for m in data.get("models", [])]
            return True, f"OK — {len(names)} modelos instalados"
        except Exception as exc:
            return False, f"Ollama no disponible: {exc}"

    # ── Backends de visión (Claude, OpenAI, OpenRouter) ──
    # Imagen de prueba: cuadrado gris 32×32
    try:
        img = Image.new("RGB", (32, 32), color=(180, 180, 180))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        img_data = buf.getvalue()
        buf.close()
    except Exception as exc:
        return False, f"Error creando imagen de prueba: {exc}"

    defaults     = ENGINE_DEFAULTS.get(engine, {})
    eff_model    = model    or defaults.get("model", "")
    eff_base_url = base_url or defaults.get("base_url")
    eff_api_key  = api_key  or defaults.get("api_key")
    test_prompt  = "What color is this square? Reply in one word."

    try:
        if engine == "claude":
            text = _ocr_via_anthropic(img_data, model=eff_model,
                                      api_key=eff_api_key, prompt=test_prompt)
        else:
            text = _ocr_via_openai_compat(img_data, model=eff_model,
                                          api_key=eff_api_key, base_url=eff_base_url,
                                          prompt=test_prompt)
        preview = text.strip().replace("\n", " ")[:60]
        return True, f"OK — {eff_model} · \"{preview}\""
    except Exception as exc:
        msg = str(exc)
        # Mensajes más claros para errores comunes
        if "401" in msg or "auth" in msg.lower():
            return False, "API key inválida o sin permisos"
        if "404" in msg or "not found" in msg.lower():
            return False, f"Modelo '{eff_model}' no encontrado"
        if "429" in msg:
            return False, "Rate limit — espera un momento y vuelve a probar"
        return False, msg[:120]


# ── Verificación de integridad del PDF final ────────────────────────────────────

def verify_pdf(pdf_path: Path, expected_pages: int) -> tuple:
    """
    Abre el PDF con pikepdf y comprueba que:
      - Se puede leer sin errores
      - Tiene al menos 1 página
      - No hay menos del 50 % de las páginas esperadas

    Devuelve (ok: bool, mensaje: str).
    """
    try:
        pdf   = pikepdf.Pdf.open(str(pdf_path))
        count = len(pdf.pages)
        pdf.close()
        if count == 0:
            return False, "PDF sin páginas"
        if count < max(1, expected_pages // 2):
            return False, f"solo {count}/{expected_pages} páginas"
        return True, f"{count} páginas OK"
    except Exception as exc:
        return False, f"error al abrir PDF: {exc}"


# ── Borrado seguro de un directorio de imágenes ──────────────────────────────────

def _delete_dir(path: Path) -> bool:
    """Elimina un directorio completo. Devuelve True si lo consigue."""
    import shutil
    try:
        shutil.rmtree(str(path))
        return True
    except Exception:
        return False


# ── Página con reintentos (backoff exponencial para errores de API) ──────────────

def _do_page(i: int, images: list, page_dir: Path, *,
             retries: int = 4, **page_kwargs) -> tuple:
    """
    Procesa una página con reintentos automáticos.
    Detecta rate-limit (429) y espera mucho más antes de reintentar.
    Devuelve (page_index, success).
    """
    page_pdf = page_dir / f"p{i:05d}.pdf"
    for attempt in range(retries + 1):
        rate_limited = False
        try:
            ok = process_page(images[i], page_pdf, **page_kwargs)
        except Exception as exc:
            # Detectar rate limit por nombre de clase o mensaje
            msg = str(exc).lower()
            rate_limited = ("429" in msg or "rate" in msg or "ratelimit" in type(exc).__name__.lower())
            ok = False
        if ok:
            return i, True
        if attempt < retries:
            # 429 → espera larga con jitter; otros errores → backoff corto
            wait = (30 + attempt * 15) if rate_limited else (2 ** (attempt + 1))
            time.sleep(wait)
    page_pdf.write_bytes(b'%PDF-1.4\n')
    return i, False


# ── Merge de PDFs individuales → PDF final ───────────────────────────────────────

def merge_pages(page_dir: Path, num_pages: int, output_pdf: Path) -> int:
    """Combina todos los PDFs individuales en output_pdf. Devuelve páginas válidas."""
    fails = 0
    try:
        pdf = pikepdf.Pdf.new()
        for pi in range(num_pages):
            pp = page_dir / f"p{pi:05d}.pdf"
            if pp.exists() and pp.stat().st_size > 100:
                try:
                    src = pikepdf.Pdf.open(str(pp))
                    pdf.pages.extend(src.pages)
                except Exception:
                    fails += 1
            else:
                fails += 1
        if fails < num_pages:
            pdf.save(str(output_pdf), compress_streams=COMPRESS_PDF)
            pdf.close()
            return num_pages - fails
        pdf.close()
        return 0
    except Exception:
        return 0


# ── Procesar un libro completo ───────────────────────────────────────────────────

def process_book(book_id: str, images: list,
                 out_dir: Path, chunk_dir: Path,
                 estado_path: Path, state: dict,
                 *,
                 lang: str = "spa+lat",
                 psm: int = 6,
                 tessdata: Optional[str] = None,
                 target_dpi: int = DEFAULT_DPI,
                 skip_ocr: bool = False,
                 engine: str = "tesseract",
                 model: Optional[str] = None,
                 api_key: Optional[str] = None,
                 base_url: Optional[str] = None,
                 ocr_prompt: Optional[str] = None,
                 workers: int = 3,
                 delete_originals: bool = False,
                 images_dir: Optional[Path] = None,
                 cancel_event: Optional[threading.Event] = None,
                 event_queue: Optional[queue.Queue] = None) -> bool:
    n        = len(images)
    out_pdf  = out_dir / f"{book_id}.pdf"
    page_dir = chunk_dir / book_id
    page_dir.mkdir(parents=True, exist_ok=True)

    def emit(kind, **kw):
        if event_queue:
            event_queue.put(ProgressEvent(kind, book=book_id, **kw))

    # Páginas pendientes (no procesadas o placeholder)
    todo = [i for i in range(n)
            if not ((page_dir / f"p{i:05d}.pdf").exists()
                    and (page_dir / f"p{i:05d}.pdf").stat().st_size > 500)]
    done_before = n - len(todo)
    emit(ProgressEvent.BOOK_START, total=n, resumed=done_before)

    state_lock  = threading.Lock()
    pages_done  = [done_before]

    page_kwargs = dict(lang=lang, psm=psm, tessdata=tessdata,
                       target_dpi=target_dpi, skip_ocr=skip_ocr,
                       engine=engine, model=model, api_key=api_key,
                       base_url=base_url, ocr_prompt=ocr_prompt)

    def handle(idx: int, ok: bool):
        emit(ProgressEvent.PAGE_OK if ok else ProgressEvent.PAGE_FAIL,
             page=idx, file=images[idx].name)
        with state_lock:
            pages_done[0] += 1
            state["progress"][book_id] = pages_done[0]
            save_state(state, estado_path)

    # Tesseract es CPU-bound → siempre secuencial
    # APIs de visión son I/O-bound → paralelas si workers > 1
    effective = 1 if engine == "tesseract" else max(1, workers)

    if effective == 1:
        for i in todo:
            if cancel_event and cancel_event.is_set():
                break
            _, ok = _do_page(i, images, page_dir, **page_kwargs)
            handle(i, ok)
    else:
        with ThreadPoolExecutor(max_workers=effective) as ex:
            futs = {ex.submit(_do_page, i, images, page_dir, **page_kwargs): i
                    for i in todo
                    if not (cancel_event and cancel_event.is_set())}
            for fut in as_completed(futs):
                if cancel_event and cancel_event.is_set():
                    ex.shutdown(wait=False, cancel_futures=True)
                    break
                idx, ok = fut.result()
                handle(idx, ok)

    emit(ProgressEvent.MERGE_START)
    ok_pages = merge_pages(page_dir, n, out_pdf)

    if ok_pages == 0:
        emit(ProgressEvent.BOOK_FAIL)
        return False

    # ── Verificación de integridad ──
    ok_verify, msg_verify = verify_pdf(out_pdf, ok_pages)
    if ok_verify:
        emit(ProgressEvent.VERIFY_OK, message=msg_verify)
    else:
        emit(ProgressEvent.VERIFY_FAIL, message=msg_verify)
        # PDF corrupto: no marcamos como hecho para que se pueda reintentar
        return False

    sz_mb = out_pdf.stat().st_size / (1024 * 1024)
    emit(ProgressEvent.BOOK_DONE, pages=ok_pages, total=n, size_mb=round(sz_mb, 1))

    state["done"].append(book_id)
    state["progress"].pop(book_id, None)
    save_state(state, estado_path)

    # ── Limpiar PDFs temporales de páginas ──
    import shutil
    try:
        shutil.rmtree(str(page_dir))
    except Exception:
        pass

    # ── Borrar imágenes originales si se solicitó ──
    if delete_originals and images_dir and Path(images_dir).is_dir():
        deleted = _delete_dir(Path(images_dir))
        emit(ProgressEvent.LOG,
             message=f"{'🗑 Originales eliminados' if deleted else '⚠ No se pudieron eliminar los originales'}: {images_dir}")

    return True


# ── Procesar múltiples libros ────────────────────────────────────────────────────

def process_all(books: list,
                out_dir: Path, chunk_dir: Path, estado_path: Path,
                *,
                lang: str = "spa+lat",
                psm: int = 6,
                tessdata: Optional[str] = None,
                target_dpi: int = DEFAULT_DPI,
                force: bool = False,
                skip_ocr: bool = False,
                engine: str = "tesseract",
                model: Optional[str] = None,
                api_key: Optional[str] = None,
                base_url: Optional[str] = None,
                ocr_prompt: Optional[str] = None,
                workers: int = 1,
                delete_originals: bool = False,
                event_queue: Optional[queue.Queue] = None,
                cancel_event: Optional[threading.Event] = None) -> dict:
    state = load_state(estado_path) if not force else {"done": [], "progress": {}}
    if event_queue is None:
        event_queue = queue.Queue()
    if cancel_event is None:
        cancel_event = threading.Event()

    done_ids = set(state.get("done", []))
    pending  = [(n, imgs) for n, imgs in books if n not in done_ids]

    t0 = time.time()
    for book_name, images in pending:
        if cancel_event.is_set():
            break
        # images_dir = directorio fuente de imágenes del libro (para borrado opcional)
        images_dir = images[0].parent if images else None
        process_book(book_name, images, out_dir, chunk_dir, estado_path, state,
                     lang=lang, psm=psm, tessdata=tessdata,
                     target_dpi=target_dpi, skip_ocr=skip_ocr,
                     engine=engine, model=model, api_key=api_key,
                     base_url=base_url, ocr_prompt=ocr_prompt,
                     workers=workers, delete_originals=delete_originals,
                     images_dir=images_dir,
                     cancel_event=cancel_event, event_queue=event_queue)

    elapsed = time.time() - t0
    state   = load_state(estado_path)
    done    = len(state.get("done", []))

    result = {
        "elapsed":      round(elapsed),
        "total_books":  len(books),
        "completed":    done,
        "cancelled":    cancel_event.is_set(),
    }
    pdfs      = sorted(out_dir.glob("*.pdf"), key=lambda p: natural_sort_key(p.stem))
    total_mb  = sum(p.stat().st_size for p in pdfs) / (1024 * 1024) if pdfs else 0
    result["pdfs"]          = [{"name": p.name,
                                 "size_mb": round(p.stat().st_size / (1024 * 1024), 1)}
                                for p in pdfs]
    result["total_size_mb"] = round(total_mb, 1)

    event_queue.put(ProgressEvent(ProgressEvent.ALL_DONE, result=result))
    return result
