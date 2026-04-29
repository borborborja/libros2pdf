#!/usr/bin/env python3
"""
libros2pdf — Genera PDFs con OCR a partir de imágenes de libros parroquiales.

Para cada subdirectorio dentro del directorio de entrada, genera un PDF con:
  - Imágenes en escala de grises, con resolución adaptativa (apunta a ~200 DPI)
  - Preprocesado para mejorar OCR en texto manuscrito
  - Capa de texto OCR (Tesseract con español + latín)
  - Estado guardado tras cada página (reanudable)

Uso:
    python3 libros2pdf.py <directorio_entrada> [directorio_salida]

Ejemplo:
    python3 libros2pdf.py ./TEST/bautismos ./PDF_LIBROS
"""

import os, sys, json, subprocess, time, io, argparse
from pathlib import Path
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import pikepdf

# ── Configuración ────────────────────────────────────────────────────────────────

# Resolución objetivo para OCR (pulgadas). Tesseract rinde mejor a 200-300 DPI.
TARGET_DPI = 200

# Tamaño máximo en píxeles para el lado más largo de la imagen.
# Si una imagen es más grande, se redimensiona para que el lado más largo
# tenga este valor. Calculado para ~200 DPI en una página A4 (~8.27").
MAX_DIMENSION = int(TARGET_DPI * 8.27)  # ~1654 px

# Calidad JPEG para las imágenes intermedias
JPEG_QUALITY = 85

# Timeout por página (segundos) para Tesseract
PAGE_TIMEOUT = 120

# Número de procesos Tesseract simultáneos. 1 = seguro con FUSE/distribuciones
# que no soportan acceso concurrente a tessdata.
WORKERS = 2

# Comprimir PDF final
COMPRESS_PDF = True


# ── Utilidades ───────────────────────────────────────────────────────────────────

def log(msg="", end="\n", flush=True):
    print(msg, end=end, flush=flush)


def natural_sort_key(s):
    """Ordena nombres con números naturales (libro 9 < libro 10)."""
    import re
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', str(s))]


def get_image_dirs(input_dir: Path):
    """Retorna lista de (nombre, lista_imágenes) para procesar.

    Si el directorio contiene subdirectorios, cada subdirectorio se trata
    como un libro. Si contiene imágenes directamente, se trata como un
    único libro.
    """
    # Buscar subdirectorios con imágenes
    dirs = sorted(
        [d for d in input_dir.iterdir() if d.is_dir()],
        key=lambda d: natural_sort_key(d.name)
    )
    result = []
    for d in dirs:
        imgs = sorted(
            [f for f in d.iterdir() if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".tif", ".tiff")],
            key=lambda f: natural_sort_key(f.name)
        )
        if imgs:
            result.append((d.name, imgs))

    # Si no hay subdirectorios, buscar imágenes directamente en input_dir
    if not result:
        imgs = sorted(
            [f for f in input_dir.iterdir() if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".tif", ".tiff")],
            key=lambda f: natural_sort_key(f.name)
        )
        if imgs:
            result.append((input_dir.name, imgs))

    return result


# ── Estados (reanudación) ────────────────────────────────────────────────────────

def load_state(estado_path: Path):
    if estado_path.exists():
        return json.loads(estado_path.read_text())
    return {"done": [], "progress": {}}


def save_state(state, estado_path: Path):
    estado_path.write_text(json.dumps(state, indent=2, ensure_ascii=False))


# ── Procesado de imagen ──────────────────────────────────────────────────────────

def preprocess_image(img: Image.Image) -> Image.Image:
    """
    Preprocesa la imagen para mejorar OCR en texto manuscrito:
      1. Escala de grises
      2. Ecualización del histograma (mejora contraste local)
      3. Reducción de ruido ligera (filtro mediano conserva bordes)
      4. Realce de contraste moderado

    NOTA: No binarizamos a blanco y negro — Tesseract LSTM rinde mejor
    con imágenes en escala de grises para texto manuscrito.
    """
    img = img.convert("L")
    img = ImageOps.equalize(img)
    img = img.filter(ImageFilter.MedianFilter(size=3))
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.3)
    # Aumentar nitidez
    img = img.filter(ImageFilter.UnsharpMask(radius=1, percent=80, threshold=2))
    return img


def resize_for_ocr(img: Image.Image) -> Image.Image:
    """
    Redimensiona manteniendo aspecto para que el lado más largo
    no supere MAX_DIMENSION. Imágenes pequeñas se dejan tal cual.
    """
    w, h = img.size
    longest = max(w, h)
    if longest <= MAX_DIMENSION:
        return img
    scale = MAX_DIMENSION / longest
    new_w = int(w * scale)
    new_h = int(h * scale)
    return img.resize((new_w, new_h), Image.LANCZOS)


# ── Procesar una página ──────────────────────────────────────────────────────────

def process_page(img_path: Path, out_pdf: Path, tessdata_prefix: str = None,
                 psm: int = 6, lang: str = "spa+lat") -> bool:
    """
    Carga, preprocesa y pasa por OCR una imagen. Genera un PDF individual.
    La imagen se pipea por stdin a Tesseract para evitar problemas de
    permisos de archivo en macOS.
    """
    try:
        img = Image.open(str(img_path))
        img = resize_for_ocr(img)
        img = preprocess_image(img)

        # Escribir la imagen preprocesada a un buffer en memoria
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True)
        img_data = buf.getvalue()
        buf.close()
        img.close()

        stem = str(out_pdf.with_suffix(""))
        env = {**os.environ}
        if tessdata_prefix:
            env["TESSDATA_PREFIX"] = tessdata_prefix

        cmd = [
            "tesseract", "stdin", stem,
            "-l", lang,
            "--psm", str(psm),
            "--oem", "1",
            "pdf"
        ]

        result = subprocess.run(cmd, input=img_data, capture_output=True, env=env, timeout=PAGE_TIMEOUT)

        return out_pdf.exists() and out_pdf.stat().st_size > 500

    except subprocess.TimeoutExpired:
        log(f"  ! {img_path.name}: timeout")
        return False
    except Exception as e:
        log(f"  ! {img_path.name}: {e}")
        return False


# ── Merge de PDFs individuales → PDF final ────────────────────────────────────────

def merge_pages(page_dir: Path, num_pages: int, output_pdf: Path) -> int:
    """
    Combina todos los PDFs individuales en el PDF final.
    Retorna el número de páginas exitosas (0 = fallo completo).
    """
    # Primero intentar con pikepdf (rápido, mantiene OCR)
    fails = 0
    try:
        pdf = pikepdf.Pdf.new()
        for pi in range(num_pages):
            pp = page_dir / f"p{pi:05d}.pdf"
            if pp.exists() and pp.stat().st_size > 100:
                try:
                    src = pikepdf.Pdf.open(str(pp))
                    pdf.pages.extend(src.pages)
                except Exception as e:
                    log(f"    ⚠ p{pi}: {e}")
                    fails += 1
            else:
                fails += 1

        if fails < num_pages:  # al menos una página
            pdf.save(str(output_pdf), compress_streams=COMPRESS_PDF)
            pdf.close()
            return num_pages - fails
        pdf.close()
        return 0

    except Exception as e:
        log(f"  Error en merge: {e}")
        return 0


# ── Procesar un libro completo (un subdirectorio) ───────────────────────────────

def process_book(book_name: str, images: list, out_dir: Path,
                 chunk_dir: Path, estado_path: Path, state: dict,
                 tessdata_prefix: str = None, psm: int = 6,
                 lang: str = "spa+lat") -> bool:
    """
    Procesa todas las imágenes de un libro (subdirectorio).
    - book_name: nombre del subdirectorio (ej. "LIBRO DE BAUTISMOS 07")
    - images: lista de Paths a imágenes
    - out_dir: donde guardar el PDF final
    - chunk_dir: directorio para PDFs temporales por página
    - estado_path: ruta al archivo de estado
    - state: dict de estado (se modifica in-place)
    """
    n = len(images)
    bid = book_name  # id único = nombre del libro

    out_pdf = out_dir / f"{book_name}.pdf"
    page_dir = chunk_dir / bid
    page_dir.mkdir(parents=True, exist_ok=True)

    # Progreso previo
    prog = state["progress"].get(bid, 0)

    log(f"\n📖 {book_name} ({n} páginas)")

    if prog > 0:
        log(f"   Reanudando desde página {prog}/{n}")

    # ── Procesar páginas secuencialmente ──
    i = prog
    while i < n:
        page_pdf = page_dir / f"p{i:05d}.pdf"

        if not (page_pdf.exists() and page_pdf.stat().st_size > 500):
            log(f"   [{i+1}/{n}] {images[i].name}...", end="")
            ok = process_page(images[i], page_pdf, tessdata_prefix, psm=psm, lang=lang)

            if not ok:
                log(f" ⚠ fallo — creando placeholder")
                # Placeholder PDF mínimo para no bloquear
                page_pdf.write_bytes(b'%PDF-1.4\n')
            else:
                log(f" ✓")

        i += 1
        state["progress"][bid] = i
        save_state(state, estado_path)

    # ── Libro completo → merge ──
    log(f"   Ensamblando PDF final...")
    ok_pages = merge_pages(page_dir, n, out_pdf)

    if ok_pages > 0:
        sz = out_pdf.stat().st_size / (1024 * 1024)
        log(f"   ✓ {out_pdf.name}  {sz:.1f} MB  ({ok_pages}/{n} págs, {n-ok_pages} fallos)")
    else:
        log(f"   ✗ {out_pdf.name} — no se generaron páginas válidas")
        return False

    # Marcar como completado
    state["done"].append(bid)
    state["progress"].pop(bid, None)
    save_state(state, estado_path)

    # Liberar páginas temporales
    for pi in range(n):
        pp = page_dir / f"p{pi:05d}.pdf"
        try:
            pp.unlink()
        except OSError:
            try:
                pp.write_bytes(b'x')
            except:
                pass

    # Intentar eliminar el directorio vacío
    try:
        page_dir.rmdir()
    except OSError:
        pass

    return True


# ── Main ─────────────────────────────────────────────────────────────────────────

def main():
    global MAX_DIMENSION, TARGET_DPI  # modificar constantes de módulo si --dpi cambia
    parser = argparse.ArgumentParser(
        description="libros2pdf — Genera PDFs con OCR a partir de imágenes de libros parroquiales.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  %(prog)s ./TEST/bautismos ./PDF_LIBROS
  %(prog)s ./bautismos             # salida: ./PDF_LIBROS
  %(prog)s ./bautismos --workers 4 # más paralelismo si el sistema lo soporta
        """
    )
    parser.add_argument("input_dir", type=str,
                        help="Directorio con subcarpetas de imágenes (cada subcarpeta = un PDF)")
    parser.add_argument("output_dir", type=str, nargs="?",
                        default="PDF_LIBROS",
                        help="Directorio de salida (defecto: ./PDF_LIBROS)")
    parser.add_argument("--workers", type=int, default=WORKERS,
                        help=f"Número de procesos paralelos (defecto: {WORKERS})")
    parser.add_argument("--dpi", type=int, default=TARGET_DPI,
                        help=f"Resolución objetivo en DPI (defecto: {TARGET_DPI})")
    parser.add_argument("--tessdata", type=str, default=None,
                        help="Directorio TESSDATA_PREFIX personalizado")
    parser.add_argument("--force", action="store_true",
                        help="Ignorar estado guardado y reprocesar todo")
    parser.add_argument("--psm", type=int, default=6,
                        help="Modo de segmentación de página Tesseract (defecto: 6). "
                             "3=automático, 4=columna única, 6=bloque uniforme")
    parser.add_argument("--lang", type=str, default="spa+lat",
                        help='Idiomas para OCR (defecto: "spa+lat"). '
                             'Ej: --lang "spa+lat+equ"')

    args = parser.parse_args()
    input_dir = Path(args.input_dir)
    out_dir = Path(args.output_dir)

    if not input_dir.is_dir():
        log(f"Error: '{input_dir}' no es un directorio válido")
        sys.exit(1)

    TARGET_DPI = args.dpi
    MAX_DIMENSION = int(TARGET_DPI * 8.27)

    # Crear directorios
    chunk_dir = out_dir / "_tmp"
    estado_path = out_dir / "estado.json"
    for d in [out_dir, chunk_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # Cargar libros
    books = get_image_dirs(input_dir)
    if not books:
        log(f"No se encontraron subdirectorios con imágenes en '{input_dir}'")
        sys.exit(0)

    total_imgs = sum(len(imgs) for _, imgs in books)
    log(f"\n📚 {len(books)} libros encontrados · {total_imgs} páginas totales")
    for name, imgs in books:
        log(f"   {name}: {len(imgs)} páginas")

    # Estado
    state = load_state(estado_path) if not args.force else {"done": [], "progress": {}}
    if args.force:
        log("   (modo --force: ignorando estado previo)")

    done_ids = state.get("done", [])
    pending = [(n, imgs) for n, imgs in books if n not in done_ids]

    if not pending:
        log("\n✓ Todos los libros ya están procesados. Usa --force para reprocesar.")
        sys.exit(0)

    log(f"\n{'='*60}")
    log(f"Pendientes: {len(pending)}/{len(books)} libros")
    if done_ids:
        log(f"Completados: {len(done_ids)}/{len(books)}")
    log(f"{'='*60}\n")

    t0 = time.time()

    # ── Procesar cada libro secuencialmente ──
    for book_name, images in pending:
        ok = process_book(
            book_name=book_name,
            images=images,
            out_dir=out_dir,
            chunk_dir=chunk_dir,
            estado_path=estado_path,
            state=state,
            tessdata_prefix=args.tessdata,
            psm=args.psm,
            lang=args.lang,
        )

    # ── Resumen final ──
    elapsed = time.time() - t0
    state = load_state(estado_path)
    done = len(state.get("done", []))

    log(f"\n{'='*60}")
    log(f"⏱  {elapsed:.0f}s · {done}/{len(books)} libros completados")

    pdfs = sorted(out_dir.glob("*.pdf"), key=lambda p: natural_sort_key(p.stem))
    if pdfs:
        total_mb = sum(p.stat().st_size for p in pdfs) / (1024 * 1024)
        log(f"📄 {len(pdfs)} PDFs · {total_mb:.0f} MB total")
        for p in pdfs:
            log(f"   {p.name}  {p.stat().st_size/(1024*1024):.1f} MB")

    if done < len(books):
        log("\nℹ️  Vuelve a ejecutar el programa para continuar donde se quedó.")
    else:
        log("\n🎉 ¡Todos los libros procesados!")


if __name__ == "__main__":
    main()
