"""
libros2pdf TUI — Interfaz interactiva de terminal con Textual.

Modo interactivo con menús, progreso en vivo y control de procesos.
Se lanza con:  python3 -m libros2pdf tui
"""

import sys, os, time, threading, queue, asyncio, json
from pathlib import Path
from typing import Optional

try:
    from textual.app import App, ComposeResult
    from textual.screen import Screen, ModalScreen
    from textual.widgets import (
        Header, Footer, Button, Static, ListView, ListItem,
        Input, Label, Select, Switch, ProgressBar, RichLog, DataTable,
        TabbedContent, TabPane, Rule, LoadingIndicator, TextArea, Collapsible,
    )
    from textual.containers import Horizontal, Vertical, Container, ScrollableContainer
    from textual.binding import Binding
    from textual.reactive import reactive
    from textual.message import Message
except ImportError:
    print("❌ Textual no instalado. Ejecuta: pip install textual")
    sys.exit(1)

from libros2pdf import (
    scan_books, process_all, load_state, test_backend, ProgressEvent,
    DEFAULT_DPI, DEFAULT_VISION_PROMPT, ENGINE_DEFAULTS, natural_sort_key,
)

# ── Config persistente ───────────────────────────────────────────────────────────

_CONFIG_DIR  = Path(__file__).parent.parent / "config"
_CONFIG_PATH = _CONFIG_DIR / "settings.json"
_PROMPT_PATH = _CONFIG_DIR / "prompt.txt"


def _load_tui_config() -> dict:
    cfg = {}
    try:
        if _CONFIG_PATH.exists():
            cfg = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    # El prompt se lee de prompt.txt (tiene prioridad sobre el campo json legado)
    try:
        if _PROMPT_PATH.exists():
            cfg["ocr_prompt"] = _PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        pass
    return cfg


def _save_tui_config(cfg: dict) -> None:
    try:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        # Separar el prompt del resto de ajustes
        prompt = cfg.pop("ocr_prompt", None)
        _CONFIG_PATH.write_text(
            json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        if prompt is not None:
            _PROMPT_PATH.write_text(prompt, encoding="utf-8")
    except Exception:
        pass


# ── Modelos conocidos por motor ──────────────────────────────────────────────────

ENGINE_MODELS: dict = {
    "tesseract": [],
    "claude": [
        ("claude-haiku-4-5  · rápido · barato",  "claude-haiku-4-5-20251001"),
        ("claude-sonnet-4-6 · equilibrado",        "claude-sonnet-4-6"),
        ("claude-opus-4-7   · máxima calidad",     "claude-opus-4-7"),
    ],
    "openai": [
        ("gpt-4o-mini · rápido · barato", "gpt-4o-mini"),
        ("gpt-4o     · máxima calidad",   "gpt-4o"),
    ],
    "openrouter": [
        ("gemini-2.5-flash-lite · muy barato",      "google/gemini-2.5-flash-lite"),
        ("gemini-2.5-flash      · equilibrado",      "google/gemini-2.5-flash"),
        ("gemini-2.5-pro        · máxima calidad",   "google/gemini-2.5-pro"),
        ("claude-haiku-4.5      · rápido · barato",  "anthropic/claude-haiku-4.5"),
        ("claude-sonnet-4.6     · calidad",          "anthropic/claude-sonnet-4.6"),
        ("claude-opus-4.7       · máxima calidad",   "anthropic/claude-opus-4.7"),
        ("gpt-4o-mini",                              "openai/gpt-4o-mini"),
        ("gpt-4o",                                   "openai/gpt-4o"),
        ("qwen2.5-vl-72b        · open source",      "qwen/qwen2.5-vl-72b-instruct"),
        ("qwen-vl-max           · open source",      "qwen/qwen-vl-max"),
        ("llama-3.2-11b-vision  · open source",      "meta-llama/llama-3.2-11b-vision-instruct"),
        ("pixtral-large-2411    · Mistral",           "mistralai/pixtral-large-2411"),
    ],
    "ollama": [],  # se detectan dinámicamente del servidor local
}


# ── Pantalla principal ───────────────────────────────────────────────────────────

class MainScreen(Screen):
    """Menú principal con selección de modo."""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Container(
            Static("\n📄 [bold]libros2pdf[/bold] — Genera PDFs con OCR\n", id="title"),
            Static("Elige un modo:", id="subtitle"),
            ListView(
                ListItem(Static("🚀  Procesar todo el directorio → PDFs (1 por subcarpeta)", id="opt-process")),
                ListItem(Static("🌐  Iniciar API REST", id="opt-serve")),
                ListItem(Static("📊  Ver estado", id="opt-status")),
                ListItem(Static("❌  Salir", id="opt-exit")),
                id="main-menu",
            ),
            id="main-container",
        )
        yield Footer()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item_id = event.item.children[0].id
        if item_id == "opt-process":
            self.app.push_screen(ProcessConfigScreen())
        elif item_id == "opt-serve":
            self.app.push_screen(ServeScreen())
        elif item_id == "opt-status":
            self.app.push_screen(StatusScreen())
        elif item_id == "opt-exit":
            self.app.exit()


# ── Pantalla de configuración de proceso ────────────────────────────────────────

class ProcessConfigScreen(Screen):
    """Configuración antes de iniciar el procesamiento."""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield ScrollableContainer(

            # ── Siempre visible ────────────────────────────────────────────────
            Static("[bold]📁 Directorios[/bold]", classes="cfg-section"),
            Label("Entrada (cada subcarpeta = un PDF):"),
            Input(placeholder="/Users/.../bautismos", id="input-dir"),
            Label("Salida:"),
            Input(placeholder="PDF_LIBROS", value="PDF_LIBROS", id="output-dir"),

            Static("[bold]🤖 Motor OCR[/bold]", classes="cfg-section"),
            Label("Motor:"),
            Select([(e, e) for e in ENGINE_DEFAULTS], value="tesseract", id="engine"),
            Label("Modelo:"),
            Select([("(no aplica)", Select.BLANK)], value=Select.BLANK,
                   id="model", disabled=True),
            Input(placeholder="o escribe un modelo personalizado (tiene prioridad)",
                  id="model-custom"),
            Label("API Key (o variable ANTHROPIC / OPENAI / OPENROUTER_API_KEY):"),
            Input(placeholder="sk-…  (vacío = usa variable de entorno)",
                  password=True, id="api-key"),
            Button("🔌 Probar conexión", variant="default", id="btn-test-connection"),
            Static("", id="test-result"),

            # ── Opciones avanzadas (colapsadas por defecto) ────────────────────
            Collapsible(
                Label("Base URL (OpenRouter / Ollama — vacío = defecto):"),
                Input(placeholder="https://openrouter.ai/api/v1", id="base-url"),

                Label("Workers (páginas en paralelo — solo visión):"),
                Select([("1 — secuencial",  "1"),
                        ("3 — recomendado", "3"),
                        ("5 — rápido",      "5"),
                        ("10 — agresivo",   "10"),
                        ("20 — máximo",     "20")],
                       value="3", id="workers"),

                Label("Idioma Tesseract:"),
                Select([("spa+lat — español + latín", "spa+lat"),
                        ("spa — solo español",         "spa"),
                        ("spa+lat+equ — con fórmulas", "spa+lat+equ")],
                       value="spa+lat", id="lang"),

                Label("OCR activado (desactivar = PDF sin capa de texto):"),
                Switch(value=True, id="ocr-switch"),

                Label("Forzar reprocesado (ignora estado guardado, solo esta vez):"),
                Switch(value=False, id="force-switch"),

                Label("🗑  Eliminar imágenes originales tras verificar PDF (¡irreversible!):"),
                Switch(value=False, id="delete-originals-switch"),

                Label("Prompt para el modelo de visión:"),
                TextArea(DEFAULT_VISION_PROMPT, id="ocr-prompt", language=None),
                Button("↺  Restaurar prompt por defecto", variant="default",
                       id="btn-reset-prompt"),

                title="⚙️  Opciones avanzadas",
                collapsed=True,
            ),

            Button("▶  Iniciar", variant="primary", id="btn-start"),
            Button("⬅  Volver", variant="default", id="btn-back"),
        )
        yield Footer()

    def on_mount(self) -> None:
        cfg = _load_tui_config()
        # ── Persistentes ──────────────────────────────────────────────────────
        if cfg.get("input_dir"):
            self.query_one("#input-dir", Input).value = cfg["input_dir"]
        if cfg.get("output_dir"):
            self.query_one("#output-dir", Input).value = cfg["output_dir"]
        if cfg.get("api_key"):
            self.query_one("#api-key", Input).value = cfg["api_key"]
        if cfg.get("base_url"):
            self.query_one("#base-url", Input).value = cfg["base_url"]
        if cfg.get("workers"):
            self.query_one("#workers", Select).value = str(cfg["workers"])
        if cfg.get("lang"):
            self.query_one("#lang", Select).value = cfg["lang"]
        if cfg.get("skip_ocr") is not None:
            self.query_one("#ocr-switch", Switch).value = not cfg["skip_ocr"]
        if cfg.get("ocr_prompt"):
            self.query_one("#ocr-prompt", TextArea).load_text(cfg["ocr_prompt"])
        # ── Motor y modelo ────────────────────────────────────────────────────
        engine = cfg.get("engine", "tesseract")
        self.query_one("#engine", Select).value = engine
        saved_model = cfg.get("model") or None
        self._update_model_select(engine, saved_model)
        if saved_model:
            known = [v for _, v in ENGINE_MODELS.get(engine, [])]
            if saved_model not in known:
                self.query_one("#model-custom", Input).value = saved_model
        # ── Efímeros: force y delete_originals siempre arrancan a False ───────

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "engine":
            self._update_model_select(str(event.value))

    def on_input_changed(self, event) -> None:
        # Recargar modelos de OpenRouter cuando cambia la API key
        if event.input.id == "api-key":
            engine = str(self.query_one("#engine", Select).value)
            if engine == "openrouter":
                self._update_model_select("openrouter")

    def _update_model_select(self, engine: str,
                              saved_model: Optional[str] = None) -> None:
        sel = self.query_one("#model", Select)
        models = ENGINE_MODELS.get(engine, [])

        if engine == "tesseract":
            sel.set_options([("(no aplica)", Select.BLANK)])
            sel.value    = Select.BLANK
            sel.disabled = True
            return

        if engine == "ollama":
            sel.set_options([("⏳ detectando modelos instalados…", Select.BLANK)])
            sel.value    = Select.BLANK
            sel.disabled = True
            threading.Thread(target=self._fetch_ollama_models, daemon=True).start()
            return

        if engine == "openrouter":
            sel.set_options([("⏳ cargando modelos de OpenRouter…", Select.BLANK)])
            sel.value    = Select.BLANK
            sel.disabled = True
            threading.Thread(target=self._fetch_openrouter_models,
                             args=(saved_model,), daemon=True).start()
            return

        sel.set_options(models)
        sel.disabled = False
        default = saved_model or ENGINE_DEFAULTS.get(engine, {}).get("model", "")
        values  = [v for _, v in models]
        sel.value = default if default in values else (values[0] if values else Select.BLANK)

    def _fetch_openrouter_models(self, saved_model: Optional[str] = None) -> None:
        import urllib.request
        api_key = self.query_one("#api-key", Input).value.strip()
        if not api_key:
            api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            self.app.call_from_thread(
                self._apply_vision_models,
                [("(introduce una API key para ver los modelos disponibles)", Select.BLANK)],
                saved_model,
            )
            return
        try:
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/models",
                headers={"Authorization": f"Bearer {api_key}",
                         "HTTP-Referer": "libros2pdf"},
            )
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read())

            opts = []
            for m in data.get("data", []):
                modality = m.get("architecture", {}).get("modality", "")
                if "image" not in modality:
                    continue
                mid   = m["id"]
                name  = m.get("name", mid)
                price = float(m.get("pricing", {}).get("prompt", 0)) * 1_000_000
                tag   = f"${price:.3f}/M" if price > 0 else "free"
                opts.append((f"{name}  ·  {tag}", mid))

            opts.sort(key=lambda x: x[0].lower())
            if not opts:
                opts = [("(ningún modelo de visión disponible)", Select.BLANK)]
        except Exception as e:
            opts = [(f"(error al cargar modelos: {e})", Select.BLANK)]

        self.app.call_from_thread(self._apply_vision_models, opts, saved_model)

    def _apply_vision_models(self, opts: list,
                              saved_model: Optional[str] = None) -> None:
        sel   = self.query_one("#model", Select)
        blank = len(opts) == 1 and opts[0][1] == Select.BLANK
        sel.set_options(opts)
        sel.disabled = blank
        if not blank:
            values  = [v for _, v in opts]
            default = saved_model or ENGINE_DEFAULTS.get("openrouter", {}).get("model", "")
            sel.value = default if default in values else values[0]

    def _fetch_ollama_models(self) -> None:
        import urllib.request
        base = (self.query_one("#base-url", Input).value.strip()
                or "http://localhost:11434")
        base = base.rstrip("/").replace("/v1", "")
        try:
            with urllib.request.urlopen(f"{base}/api/tags", timeout=3) as r:
                data = json.loads(r.read())
            names = [m["name"] for m in data.get("models", [])]
            opts  = [(n, n) for n in names] if names else [("(ningún modelo instalado)", Select.BLANK)]
        except Exception:
            opts = [("(Ollama no disponible en localhost)", Select.BLANK)]
        self.call_from_thread(self._apply_ollama_models, opts)

    def _apply_ollama_models(self, opts: list) -> None:
        sel   = self.query_one("#model", Select)
        blank = len(opts) == 1 and opts[0][1] == Select.BLANK
        sel.set_options(opts)
        sel.disabled = blank
        if not blank:
            sel.value = opts[0][1]

    def _run_connection_test(self) -> None:
        engine    = str(self.query_one("#engine", Select).value)
        model_val = self.query_one("#model", Select).value
        model     = (self.query_one("#model-custom", Input).value.strip()
                     or (None if model_val == Select.BLANK else str(model_val)))
        api_key   = self.query_one("#api-key", Input).value.strip() or None
        base_url  = self.query_one("#base-url", Input).value.strip() or None
        result_w  = self.query_one("#test-result", Static)
        btn       = self.query_one("#btn-test-connection", Button)

        result_w.update("[yellow]⏳ Probando conexión…[/yellow]")
        btn.disabled = True

        def _test():
            ok, msg = test_backend(engine, model=model,
                                   api_key=api_key, base_url=base_url)
            self.app.call_from_thread(_show, ok, msg)

        def _show(ok: bool, msg: str):
            icon = "[green]✔[/green]" if ok else "[red]✗[/red]"
            result_w.update(f"{icon} {msg}")
            btn.disabled = False

        threading.Thread(target=_test, daemon=True).start()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.app.pop_screen()
        elif event.button.id == "btn-reset-prompt":
            self.query_one("#ocr-prompt", TextArea).load_text(DEFAULT_VISION_PROMPT)
        elif event.button.id == "btn-test-connection":
            self._run_connection_test()
        elif event.button.id == "btn-start":
            # Limpiar escapes de shell (ej: LIBRO\ 21 → LIBRO 21, peñarroya\, → peñarroya,)
            import re as _re
            input_dir = _re.sub(r'\\(.)', r'\1',
                                self.query_one("#input-dir", Input).value.strip())
            engine       = str(self.query_one("#engine", Select).value)
            model_custom = self.query_one("#model-custom", Input).value.strip()
            model_val    = self.query_one("#model", Select).value
            # El campo personalizado tiene prioridad sobre el Select
            model = model_custom or (None if model_val == Select.BLANK else str(model_val))
            api_key   = self.query_one("#api-key", Input).value.strip() or None
            base_url  = self.query_one("#base-url", Input).value.strip() or None
            workers    = int(str(self.query_one("#workers", Select).value))
            lang       = str(self.query_one("#lang", Select).value)
            psm        = 6
            skip_ocr   = not self.query_one("#ocr-switch", Switch).value
            force            = self.query_one("#force-switch", Switch).value
            delete_originals = self.query_one("#delete-originals-switch", Switch).value
            ocr_prompt       = self.query_one("#ocr-prompt", TextArea).text.strip() or None

            if not input_dir:
                self.app.push_screen(ErrorScreen("El directorio de entrada es obligatorio"))
                return

            in_path    = Path(input_dir).resolve()
            output_dir = self.query_one("#output-dir", Input).value.strip() or str(in_path.parent)
            if not in_path.is_dir():
                self.app.push_screen(ErrorScreen(f"No existe: {in_path}"))
                return
            books = scan_books(in_path)
            if not books:
                self.app.push_screen(ErrorScreen(
                    f"No se encontraron imágenes en:\n{in_path}\n\n"
                    "Acepta:\n"
                    "• Directorio con subcarpetas de imágenes (1 PDF por subcarpeta)\n"
                    "• Directorio con imágenes directamente (1 PDF)"
                ))
                return

            _save_tui_config({
                "input_dir":  str(in_path),
                "output_dir": output_dir,
                "engine":     engine,
                "model":      model or "",
                "api_key":    api_key or "",
                "base_url":   base_url or "",
                "workers":    workers,
                "lang":       lang,
                "skip_ocr":   skip_ocr,
                "ocr_prompt": ocr_prompt or "",
                # force y delete_originals NO se guardan (son acciones puntuales)
            })

            self.app.push_screen(ProcessScreen(
                in_path, Path(output_dir), lang, psm, skip_ocr,
                engine=engine, model=model, api_key=api_key, base_url=base_url,
                force=force, workers=workers, ocr_prompt=ocr_prompt,
                delete_originals=delete_originals,
            ))


# ── Pantalla de procesamiento en vivo ───────────────────────────────────────────

class ProcessScreen(Screen):
    """Procesamiento con barras de progreso y log en vivo."""

    def __init__(self, input_dir: Path, output_dir: Path,
                 lang: str, psm: int, skip_ocr: bool = False,
                 engine: str = "tesseract", model: Optional[str] = None,
                 api_key: Optional[str] = None, base_url: Optional[str] = None,
                 force: bool = False, workers: int = 5,
                 ocr_prompt: Optional[str] = None,
                 delete_originals: bool = False, **kwargs):
        super().__init__(**kwargs)
        self._input_dir        = input_dir
        self._output_dir       = output_dir
        self._lang             = lang
        self._psm              = psm
        self._skip_ocr         = skip_ocr
        self._engine           = engine
        self._model            = model
        self._api_key          = api_key
        self._base_url         = base_url
        self._force            = force
        self._workers          = workers
        self._ocr_prompt       = ocr_prompt
        self._delete_originals = delete_originals
        self._event_queue: queue.Queue = queue.Queue()
        self._cancel_event = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._books: list = []
        self._total_pages = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Container(
            Static(id="process-title", classes="section-title"),
            Horizontal(
                Static("General: ", id="global-label"),
                ProgressBar(id="global-progress", show_eta=True),
            ),
            ScrollableContainer(id="book-progress-container"),
            Rule(),
            RichLog(id="log-view", highlight=True, markup=True, max_lines=50),
            Horizontal(
                Button("⬅ Volver al menú", variant="error", id="btn-cancel"),
                id="footer-buttons",
            ),
            id="process-container",
        )
        yield Footer()

    def on_mount(self) -> None:
        books = scan_books(self._input_dir)
        self._books = books
        self._total_pages = sum(len(imgs) for _, imgs in books)

        title = self.query_one("#process-title", Static)
        ocr_status = "[dim]sin OCR[/dim]" if self._skip_ocr else self._engine
        title.update(f"[bold]📖 {self._input_dir.name}[/bold]  ·  {len(books)} libros  ·  {self._total_pages} páginas  ·  {ocr_status}")

        # Crear progress bars por libro
        container = self.query_one("#book-progress-container", ScrollableContainer)
        for name, imgs in books:
            short = name[:55]
            safe_id = name.replace(" ", "_").replace(".", "_")
            row = Horizontal(
                Static(f"[cyan]{short}[/cyan]", classes="book-label"),
                ProgressBar(total=len(imgs), id=f"pb-{safe_id}", show_eta=False),
                classes="book-row",
            )
            container.mount(row)

        self.query_one("#global-progress", ProgressBar).update(total=self._total_pages, progress=0)

        # Arrancar worker
        log = self.query_one("#log-view", RichLog)
        log.write("[green]▶ Iniciando procesamiento...[/green]")

        output_dir = self._output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        chunk_dir = output_dir / "_tmp"
        estado_path = output_dir / "estado.json"

        books_to_process = books

        self._worker = threading.Thread(
            target=self._run_worker,
            args=(books_to_process, output_dir, chunk_dir, estado_path),
            daemon=True,
        )
        self._worker.start()

        # Hilo de eventos
        self._event_consumer_running = True
        self._event_consumer = threading.Thread(target=self._consume_events, daemon=True)
        self._event_consumer.start()

        self.set_interval(0.25, self._check_worker)

    def _run_worker(self, books, output_dir, chunk_dir, estado_path):
        process_all(
            books, output_dir, chunk_dir, estado_path,
            lang=self._lang, psm=self._psm,
            skip_ocr=self._skip_ocr, force=self._force,
            workers=self._workers, delete_originals=self._delete_originals,
            engine=self._engine, model=self._model,
            api_key=self._api_key, base_url=self._base_url,
            ocr_prompt=self._ocr_prompt,
            event_queue=self._event_queue,
            cancel_event=self._cancel_event,
        )

    def _consume_events(self):
        while getattr(self, '_event_consumer_running', True):
            try:
                ev = self._event_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            self.app.call_from_thread(self._handle_event, ev)

    def _handle_event(self, ev: ProgressEvent):
        try:
            self._handle_event_inner(ev)
        except Exception as exc:
            try:
                self.query_one("#log-view", RichLog).write(
                    f"[red]   ! error UI: {exc}[/red]"
                )
            except Exception:
                pass

    def _handle_event_inner(self, ev: ProgressEvent):
        d    = ev.to_dict()
        bk   = d.get("book", "")
        page = d.get("page")
        total = d.get("total", 0)
        log  = self.query_one("#log-view", RichLog)
        gpb  = self.query_one("#global-progress", ProgressBar)

        if ev.kind == ProgressEvent.PAGE_OK:
            log.write(f"   ✓ {d.get('file', '')}")
            gpb.advance(1)
            self._try_update_book_pb(bk, page)

        elif ev.kind == ProgressEvent.PAGE_FAIL:
            log.write(f"[yellow]   ⚠ {d.get('file', '')} (fallo)[/yellow]")
            gpb.advance(1)
            self._try_update_book_pb(bk, page)

        elif ev.kind == ProgressEvent.MERGE_START:
            log.write(f"[cyan]   ⎇ Mergeando {bk}...[/cyan]")

        elif ev.kind == ProgressEvent.VERIFY_OK:
            log.write(f"[green]   ✔ Verificado: {d.get('message', '')}[/green]")

        elif ev.kind == ProgressEvent.VERIFY_FAIL:
            log.write(f"[red]   ✗ Verificación fallida: {d.get('message', '')}[/red]")

        elif ev.kind == ProgressEvent.LOG:
            log.write(f"   {d.get('message', '')}")

        elif ev.kind == ProgressEvent.BOOK_FAIL:
            log.write(f"[red]   ✗ {bk}: merge fallido — activa 'Forzar reprocesado' para reintentar[/red]")

        elif ev.kind == ProgressEvent.BOOK_DONE:
            log.write(f"[green]   ✓ {bk}: {d.get('pages',0)}/{d.get('total',0)} págs, {d.get('size_mb',0)} MB[/green]")
            title = self.query_one("#process-title", Static)
            done = len([n for n, _ in self._books
                       if n in (load_state(self._output_dir / "estado.json").get("done", []))])
            title.update(f"[bold]📖 {self._input_dir.name}[/bold]  ·  {done}/{len(self._books)} libros completados")

        elif ev.kind == ProgressEvent.ALL_DONE:
            result = d.get("result", {})
            elapsed = result.get("elapsed", 0)
            completed = result.get("completed", 0)
            log.write(f"\n[bold green]🎉 ¡Proceso completado! {elapsed}s · {completed} libros[/bold green]")
            if result.get("pdfs"):
                total_mb = result.get("total_size_mb", 0)
                log.write(f"[bold]📄 {len(result['pdfs'])} PDFs · {total_mb} MB[/bold]")
                for p in result["pdfs"]:
                    log.write(f"   {p['name']}  {p['size_mb']} MB")
            self.query_one("#btn-cancel", Button).label = "⬅ Volver"

    def _try_update_book_pb(self, book_name: str, page: Optional[int]):
        if page is None:
            return
        safe_id = book_name.replace(" ", "_").replace(".", "_")
        try:
            pb = self.query_one(f"#pb-{safe_id}", ProgressBar)
            pb.update(progress=page + 1)
        except Exception:
            pass

    def _check_worker(self) -> None:
        if self._worker and not self._worker.is_alive():
            self._event_consumer_running = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self._cancel_event.set()
            self._event_consumer_running = False
            log = self.query_one("#log-view", RichLog)
            log.write("[yellow]⚠ Proceso cancelado[/yellow]")
            self.query_one("#btn-cancel", Button).label = "⬅ Volver"
            # Esperar un momento y volver
            self.app.pop_screen()


# ── Pantalla de estado ──────────────────────────────────────────────────────────

class StatusScreen(Screen):
    """Estado actual de libros y PDFs generados."""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield ScrollableContainer(
            Static("\n[bold]📊 Estado de procesamiento[/bold]\n"),
            Static("Directorio de salida:"),
            Input(placeholder="PDF_LIBROS", value="PDF_LIBROS", id="status-outdir"),
            Static("\nDirectorio de entrada (opcional, para ver pendientes):"),
            Input(placeholder="Ej: /Users/.../bautismos", id="status-indir"),
            Horizontal(
                Button("🔄 Actualizar", variant="primary", id="btn-refresh"),
                Button("⬅ Volver", id="btn-back"),
            ),
            DataTable(id="status-table"),
            Static(id="status-summary"),
        )
        yield Footer()

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        out_dir = Path(self.query_one("#status-outdir", Input).value.strip() or "PDF_LIBROS")
        in_dir_str = self.query_one("#status-indir", Input).value.strip()

        table = self.query_one("#status-table", DataTable)
        table.clear(columns=True)
        table.add_column("Libro")
        table.add_column("Páginas", width=8)
        table.add_column("Estado", width=14)

        estado_path = out_dir / "estado.json" if out_dir.is_dir() else None
        state = load_state(estado_path) if estado_path and estado_path.exists() else {}
        done = set(state.get("done", []))
        progress = state.get("progress", {})

        if in_dir_str:
            in_path = Path(in_dir_str).resolve()
            if in_path.is_dir():
                books = scan_books(in_path)
                for name, imgs in books:
                    if name in done:
                        status = "[green]✅ completo[/green]"
                    elif name in progress:
                        p = progress[name]
                        status = f"[yellow]⏳ {p}/{len(imgs)}[/yellow]"
                    else:
                        status = "[white]⏸ pendiente[/white]"
                    table.add_row(name[:50], str(len(imgs)), status)

        # PDFs generados
        summary = self.query_one("#status-summary", Static)
        if out_dir.is_dir():
            pdfs = sorted(out_dir.glob("*.pdf"), key=lambda p: natural_sort_key(p.stem))
            if pdfs:
                total_mb = sum(p.stat().st_size for p in pdfs) / (1024 * 1024)
                summary.update(f"\n📄 [bold]{len(pdfs)} PDFs · {total_mb:.0f} MB[/bold]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.app.pop_screen()
        elif event.button.id == "btn-refresh":
            self._refresh()


# ── Pantalla de API Serve ───────────────────────────────────────────────────────

class ServeScreen(Screen):
    """Información para iniciar el servidor API."""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Container(
            Static("\n[bold]🌐 API REST[/bold]\n", classes="section-title"),
            Static("El servidor API permite conectar una web u otros clientes.\n"),
            Static("Host:"),
            Input(placeholder="127.0.0.1", value="127.0.0.1", id="serve-host"),
            Static("\nPuerto:"),
            Input(placeholder="8000", value="8000", id="serve-port"),
            Horizontal(
                Button("▶  Iniciar servidor", variant="primary", id="btn-serve-start"),
                Button("⬅ Volver", id="btn-back"),
            ),
            RichLog(id="serve-log", highlight=True, max_lines=30),
            id="serve-container",
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.app.pop_screen()
        elif event.button.id == "btn-serve-start":
            host = self.query_one("#serve-host", Input).value.strip() or "127.0.0.1"
            port = int(self.query_one("#serve-port", Input).value.strip() or "8000")
            log = self.query_one("#serve-log", RichLog)
            log.write(f"[green]▶ Iniciando API en http://{host}:{port}[/green]")
            log.write(f"[green]   Swagger: http://{host}:{port}/docs[/green]")
            log.write("[yellow]   (el servidor se ejecuta en la terminal donde lanzaste el TUI)[/yellow]")
            log.write("[yellow]   Vuelve al menú y selecciona 'Salir' para detener el TUI[/yellow]")
            log.write("")
            log.write("[dim]Para iniciar el API en otra terminal:[/dim]")
            log.write(f"[dim]  python3 -m libros2pdf serve --host {host} --port {port}[/dim]")

            # Arrancar uvicorn en hilo separado
            import uvicorn
            from libros2pdf_api import app
            t = threading.Thread(
                target=uvicorn.run,
                args=(app,),
                kwargs={"host": host, "port": port, "log_level": "info"},
                daemon=True,
            )
            t.start()
            self.query_one("#btn-serve-start", Button).disabled = True
            self.query_one("#btn-serve-start", Button).label = "✅ Servidor activo"


# ── Pantalla de error ───────────────────────────────────────────────────────────

class ErrorScreen(ModalScreen):
    """Pantalla modal para errores."""

    def __init__(self, message: str, **kwargs):
        super().__init__(**kwargs)
        self._error_msg = message

    def compose(self) -> ComposeResult:
        yield Container(
            Static(f"\n[red]❌ {self._error_msg}[/red]\n"),
            Button("OK", variant="primary", id="btn-ok"),
            id="error-container",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.app.pop_screen()


# ── App principal ───────────────────────────────────────────────────────────────

class Libros2PDFApp(App):
    """Aplicación TUI principal."""

    CSS = """
    Screen {
        background: $surface;
    }

    #main-container {
        align: center middle;
        width: 60;
        height: auto;
        padding: 1;
    }

    #title {
        text-align: center;
        padding: 1 0;
    }

    #subtitle {
        text-align: center;
        padding: 0 0 1 0;
    }

    #main-menu {
        width: 100%;
        height: auto;
    }

    #main-menu ListItem {
        padding: 1 2;
    }

    #main-menu ListItem:hover {
        background: $accent;
    }

    ListView {
        border: solid $primary;
    }

    .cfg-section {
        padding: 1 0 0 0;
        color: $accent;
    }

    #ocr-prompt {
        height: 8;
        margin: 0 0 1 0;
    }

    #test-result {
        margin: 0 0 1 0;
        padding: 0 1;
    }

    #process-container {
        padding: 1;
        height: 100%;
    }

    #book-progress-container {
        max-height: 12;
    }

    #process-title {
        padding: 0 0 1 0;
    }

    .book-row {
        height: 1;
        padding: 0 1;
    }

    .book-label {
        width: 55;
        min-width: 20;
    }

    #global-label {
        width: 12;
    }

    #global-progress {
        width: 1fr;
    }

    #log-view {
        height: 1fr;
        border: solid $primary;
        margin: 1 0;
    }

    #footer-buttons {
        align: center middle;
        height: auto;
    }

    #serve-container {
        padding: 1;
        height: 100%;
    }

    #serve-log {
        height: 1fr;
        border: solid $primary;
        margin: 1 0;
    }

    #error-container {
        align: center middle;
        width: 50;
        height: auto;
        padding: 2;
        border: solid $error;
        background: $surface;
    }

    #status-table {
        margin: 1 0;
    }

    .section-title {
        text-align: center;
    }

    Input, Select {
        margin: 0 0 1 0;
    }

    Button {
        margin: 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Salir"),
        Binding("escape", "back", "Volver"),
    ]

    def action_back(self):
        if len(self.screen_stack) > 1:
            self.pop_screen()

    def on_mount(self) -> None:
        self.push_screen(MainScreen())


def run():
    """Punto de entrada para el modo TUI."""
    app = Libros2PDFApp()
    app.run()


if __name__ == "__main__":
    run()
