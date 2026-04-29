#!/usr/bin/env python3
"""
libros2pdf CLI — Interfaz de línea de comandos con barra de progreso.

Uso:
    python3 -m libros2pdf <directorio> [salida] [opciones]
    python3 -m libros2pdf serve [--host HOST] [--port PORT]
    python3 -m libros2pdf --help
"""

import sys, time, threading, queue
from pathlib import Path
from typing import Optional

from libros2pdf import (
    __version__, scan_books, load_state, save_state, process_all, ProgressEvent,
    DEFAULT_DPI, ENGINE_DEFAULTS,
)


def cli():
    import argparse

    # Detectar si el primer argumento posicional es un directorio → auto-route a process
    commands = {"process", "tui", "serve", "status", "--help", "-h", "--version"}
    argv = sys.argv[1:]
    if argv and argv[0] not in commands and not argv[0].startswith("-"):
        argv.insert(0, "process")
        sys.argv[1:] = argv

    parser = argparse.ArgumentParser(
        prog="libros2pdf",
        description="📄 Genera PDFs con OCR a partir de imágenes de libros parroquiales.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Ejemplos:
  %(prog)s ./bautismos ./PDFs              # proceso completo
  %(prog)s ./bautismos --psm 3 --lang spa  # solo entrada, salida automática
  %(prog)s serve                           # API REST (fastapi)
  %(prog)s tui                             # interfaz interactiva

Documentación: python3 -m libros2pdf <comando> --help
        """,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    sub = parser.add_subparsers(dest="command", help="Comandos disponibles")

    # ── Comando: process ──
    p_proc = sub.add_parser("process", help="Procesar imágenes → PDFs (modo no interactivo)")
    p_proc.add_argument("input_dir", type=str, help="Directorio con imágenes o subcarpetas (1 PDF por subdirectorio)")
    p_proc.add_argument("output_dir", type=str, nargs="?", default=None,
                        help="Directorio de salida (defecto: misma carpeta que entrada)")
    p_proc.add_argument("--dpi", type=int, default=DEFAULT_DPI,
                        help=f"Resolución objetivo (defecto: {DEFAULT_DPI})")
    p_proc.add_argument("--psm", type=int, default=6,
                        help="Modo segmentación Tesseract (3=auto, 6=bloque, defecto: 6)")
    p_proc.add_argument("--lang", type=str, default="spa+lat",
                        help='Idiomas OCR (defecto: "spa+lat")')
    p_proc.add_argument("--no-ocr", action="store_true",
                        help="Saltar OCR (mucho más rápido, PDF sin capa de texto)")
    p_proc.add_argument("--engine", type=str, default="tesseract",
                        choices=list(ENGINE_DEFAULTS.keys()),
                        help="Motor OCR (defecto: tesseract)")
    p_proc.add_argument("--model", type=str, default=None,
                        help="Modelo para backends de visión (defecto según --engine). "
                             "Ej: claude-sonnet-4-6, gpt-4o, google/gemini-flash-1.5")
    p_proc.add_argument("--api-key", type=str, default=None,
                        help="API key del backend (o usa ANTHROPIC_API_KEY / "
                             "OPENAI_API_KEY / OPENROUTER_API_KEY como variable de entorno)")
    p_proc.add_argument("--base-url", type=str, default=None,
                        help="URL base de la API (OpenRouter, Ollama u otro compatible). "
                             "Ej: https://openrouter.ai/api/v1")
    p_proc.add_argument("--prompt", type=str, default=None,
                        help="Prompt personalizado para el backend de visión")
    p_proc.add_argument("--workers", type=int, default=3,
                        help="Páginas en paralelo para backends de visión (defecto: 5). "
                             "Ignorado con Tesseract (siempre secuencial).")
    p_proc.add_argument("--tessdata", type=str, default=None,
                        help="Directorio TESSDATA_PREFIX personalizado (solo Tesseract)")
    p_proc.add_argument("--delete-originals", action="store_true",
                        help="Eliminar el directorio de imágenes originales tras verificar el PDF")
    p_proc.add_argument("--force", action="store_true",
                        help="Ignorar estado guardado y reprocesar")
    p_proc.add_argument("--no-rich", action="store_true",
                        help="Desactivar barras de progreso (útil para piping)")

    # ── Comando: tui ──
    p_tui = sub.add_parser("tui", help="Interfaz interactiva de terminal (TUI)")

    # ── Comando: serve ──
    p_srv = sub.add_parser("serve", help="Iniciar API REST")
    p_srv.add_argument("--host", type=str, default="127.0.0.1", help="Host (defecto: 127.0.0.1)")
    p_srv.add_argument("--port", type=int, default=8000, help="Puerto (defecto: 8000)")

    # ── Comando: status ──
    p_st = sub.add_parser("status", help="Ver estado de procesamiento")
    p_st.add_argument("output_dir", type=str, nargs="?", default="PDF_LIBROS",
                      help="Directorio de salida (defecto: ./PDF_LIBROS)")
    p_st.add_argument("input_dir", type=str, nargs="?",
                      help="Directorio de entrada (para ver pendientes)")

    args = parser.parse_args()

    if args.command == "serve":
        return run_api(args.host, args.port)

    if args.command == "status":
        return show_status(Path(args.output_dir), Path(args.input_dir) if args.input_dir else None)

    if args.command == "process":
        return run_process(args)

    # Default: TUI
    return run_tui()


# ── Barra de progreso con Rich ──────────────────────────────────────────────────

def run_process(args):
    input_dir = Path(args.input_dir)

    if not input_dir.is_dir():
        print(f"❌ Error: '{input_dir}' no es un directorio válido")
        sys.exit(1)

    output_dir = Path(args.output_dir) if args.output_dir else input_dir.parent

    books = scan_books(input_dir)
    if not books:
        print(f"📭 No se encontraron imágenes en '{input_dir}'")
        sys.exit(0)

    total_imgs = sum(len(imgs) for _, imgs in books)
    estado_path = output_dir / "estado.json"
    chunk_dir = output_dir / "_tmp"
    chunk_dir.mkdir(parents=True, exist_ok=True)

    # Estado inicial
    state = load_state(estado_path) if not args.force else {"done": [], "progress": {}}
    done_ids = set(state.get("done", []))
    pending = [(n, imgs) for n, imgs in books if n not in done_ids]

    if not pending:
        print("✅ Todos los libros ya están procesados. Usa --force para reprocesar.")
        sys.exit(0)

    output_dir.mkdir(parents=True, exist_ok=True)
    event_queue: queue.Queue = queue.Queue()
    cancel_event = threading.Event()

    # ── Rich progress ──
    use_rich = not args.no_rich and sys.stdout.isatty()
    if use_rich:
        from rich.console import Console
        from rich.progress import (
            Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn,
            TimeRemainingColumn, TimeElapsedColumn,
        )
        from rich.panel import Panel
        from rich.live import Live
        from rich.table import Table
        from rich.layout import Layout

        console = Console()
        book_progress = {}
        overall_progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
        )
        overall_task = overall_progress.add_task("Global", total=total_imgs, visible=True)

        status_text = TextColumn("[bold]{task.description}")
        live = Live(Panel(overall_progress), refresh_per_second=4)
        progress_active = True
        last_result = None

        def consume_events():
            nonlocal last_result
            while progress_active:
                try:
                    ev = event_queue.get(timeout=0.25)
                except queue.Empty:
                    continue

                d = ev.to_dict()
                bk = d.get("book", "")
                total = d.get("total", 0)
                page = d.get("page")

                if ev.kind == ProgressEvent.BOOK_START:
                    if bk not in book_progress:
                        bp = Progress(
                            TextColumn("  {task.description}"),
                            BarColumn(),
                            TaskProgressColumn(),
                            TimeRemainingColumn(),
                        )
                        bp.add_task(f"[cyan]{bk}", total=total)
                        book_progress[bk] = bp

                elif ev.kind in (ProgressEvent.PAGE_OK, ProgressEvent.PAGE_FAIL):
                    if page is not None:
                        overall_progress.update(overall_task, advance=1, description=f"📄 {bk}  ")
                        if bk in book_progress:
                            bp = book_progress[bk]
                            for t in bp.tasks:
                                bp.update(t.id, completed=page + 1)

                elif ev.kind == ProgressEvent.BOOK_DONE:
                    if bk in book_progress:
                        bp = book_progress[bk]
                        for t in bp.tasks:
                            bp.update(t.id, completed=total, description=f"[green]✓ {bk}")
                    overall_progress.update(overall_task, description=f"[green]✓ {bk}")

                elif ev.kind == ProgressEvent.MERGE_START:
                    overall_progress.update(overall_task, description=f"[yellow]⎇  Mergeando {bk}...")

                elif ev.kind == ProgressEvent.ALL_DONE:
                    last_result = d.get("result")

        # Hilo consumidor de eventos para actualizar UI
        consumer = threading.Thread(target=consume_events, daemon=True)
        consumer.start()

        # Layout con tabla de libros y progreso general
        table = Table(title=f"📚 {len(books)} libros · {total_imgs} páginas")
        table.add_column("Libro", style="cyan")
        table.add_column("Páginas", justify="right")
        table.add_column("Estado", style="green")
        for name, imgs in pending:
            table.add_row(name[:50], str(len(imgs)), "⏳ pendiente")

        console.print(table)

        with live:
            # Lanzar procesamiento en hilo separado
            worker = threading.Thread(
                target=process_all,
                args=(pending, output_dir, chunk_dir, estado_path),
                kwargs=dict(
                    lang=args.lang, psm=args.psm, tessdata=args.tessdata,
                    target_dpi=args.dpi, force=args.force, skip_ocr=args.no_ocr,
                    engine=args.engine, model=args.model,
                    api_key=args.api_key, base_url=args.base_url,
                    ocr_prompt=args.prompt, workers=args.workers,
                    delete_originals=args.delete_originals,
                    event_queue=event_queue, cancel_event=cancel_event,
                ),
                daemon=True,
            )
            worker.start()
            worker.join()
            progress_active = False
        consumer.join()

        # Resumen final
        result = last_result or {}
        console.print(f"\n[bold]⏱  {result.get('elapsed', 0)}s · "
                       f"{result.get('completed', 0)}/{len(books)} libros[/bold]")
        if result.get("pdfs"):
            total_mb = result.get("total_size_mb", 0)
            console.print(f"[bold]📄 {len(result['pdfs'])} PDFs · {total_mb} MB[/bold]")
            for p in result["pdfs"]:
                console.print(f"   {p['name']}  {p['size_mb']} MB")
        if result.get("cancelled"):
            console.print("\n⚠️  Proceso cancelado. Ejecuta de nuevo para continuar.")
        elif result.get("completed", 0) < len(books):
            console.print("\nℹ️  Vuelve a ejecutar para continuar donde se quedó.")
        else:
            console.print("\n[green]🎉 ¡Todos los libros procesados![/green]")

    else:
        # ── Modo texto simple (sin Rich) ──
        print(f"\n📚 {len(pending)}/{len(books)} libros · {sum(len(i) for _, i in pending)} págs pendientes\n")
        worker = threading.Thread(
            target=process_all,
            args=(pending, output_dir, chunk_dir, estado_path),
            kwargs=dict(
                lang=args.lang, psm=args.psm, tessdata=args.tessdata,
                target_dpi=args.dpi, force=args.force, skip_ocr=args.no_ocr,
                engine=args.engine, model=args.model,
                api_key=args.api_key, base_url=args.base_url,
                ocr_prompt=args.prompt, workers=args.workers,
                delete_originals=args.delete_originals,
                event_queue=event_queue, cancel_event=cancel_event,
            ),
            daemon=True,
        )
        worker.start()

        while worker.is_alive():
            try:
                ev = event_queue.get(timeout=0.5)
                d = ev.to_dict()
                bk = d.get("book", "")
                if ev.kind == ProgressEvent.PAGE_OK:
                    print(f"   [{d.get('page', 0)+1}/{d.get('total', '?')}] {d.get('file', '')} ✓", flush=True)
                elif ev.kind == ProgressEvent.PAGE_FAIL:
                    print(f"   [{d.get('page', 0)+1}/{d.get('total', '?')}] {d.get('file', '')} ⚠", flush=True)
                elif ev.kind == ProgressEvent.BOOK_DONE:
                    print(f"   ✓ {bk}: {d.get('pages', 0)}/{d.get('total', 0)} págs, {d.get('size_mb', 0)} MB", flush=True)
                elif ev.kind == ProgressEvent.MERGE_START:
                    print(f"   ⎇ Mergeando {bk}...", flush=True)
                elif ev.kind == ProgressEvent.ALL_DONE:
                    result = d.get("result", {})
                    print(f"\n=== {result.get('elapsed', 0)}s · {result.get('completed', 0)}/{len(books)} libros ===")
                    for p in result.get("pdfs", []):
                        print(f"   {p['name']}  {p['size_mb']} MB")
                    if result.get("completed", 0) < len(books):
                        print("\nVuelve a ejecutar para continuar.")
                    else:
                        print("\n¡Todos los libros procesados!")
            except queue.Empty:
                continue
        worker.join()


# ── Estado ───────────────────────────────────────────────────────────────────────

def show_status(output_dir: Path, input_dir: Optional[Path] = None):
    estado_path = output_dir / "estado.json"
    if not estado_path.exists():
        print(f"📭 No hay estado en '{output_dir}'")
        return

    state = load_state(estado_path)
    done = state.get("done", [])
    progress = state.get("progress", {})

    print(f"\n📊 Estado de procesamiento")
    print(f"   Directorio: {output_dir}")
    print(f"   Completados: {len(done)} libros")

    if input_dir:
        books = scan_books(input_dir)
        print(f"   Total: {len(books)} libros")
        for name, imgs in books:
            if name in done:
                status = "✅ completo"
            elif name in progress:
                p = progress[name]
                status = f"⏳ {p}/{len(imgs)} páginas"
            else:
                status = "⏸️  pendiente"
            print(f"     {name[:55]}  {status}")

    pdfs = sorted(output_dir.glob("*.pdf"), key=lambda p: natural_sort_key(p.stem))
    if pdfs:
        total_mb = sum(p.stat().st_size for p in pdfs) / (1024 * 1024)
        print(f"\n📄 {len(pdfs)} PDFs · {total_mb:.0f} MB")
        for p in pdfs:
            print(f"   {p.name}  {p.stat().st_size/(1024*1024):.1f} MB")


# ── API ──────────────────────────────────────────────────────────────────────────

def run_api(host: str, port: int):
    """Arranca el servidor API FastAPI."""
    try:
        from libros2pdf_api import app
        import uvicorn
    except ImportError:
        print("❌ Dependencias necesarias: fastapi y uvicorn")
        print("   pip install fastapi uvicorn python-multipart")
        sys.exit(1)

    print(f"\n🚀 libros2pdf API — http://{host}:{port}")
    print(f"   📖 Swagger UI: http://{host}:{port}/docs")
    print(f"   📋 Resumen:    http://{host}:{port}/")
    print()
    uvicorn.run(app, host=host, port=port)


# ── TUI ──────────────────────────────────────────────────────────────────────────

def run_tui():
    """Lanza la interfaz interactiva de terminal."""
    try:
        from libros2pdf.tui import run as tui_run
        tui_run()
    except ImportError as e:
        print(f"❌ Error al cargar TUI: {e}")
        print("   Asegúrate de tener textual instalado: pip install textual")
        sys.exit(1)


if __name__ == "__main__":
    cli()
