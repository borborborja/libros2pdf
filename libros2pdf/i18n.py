"""
libros2pdf — Internacionalización (i18n)
Idiomas soportados: es (español), en (English), ca (català)
"""

_LANG: str = "es"

SUPPORTED = ("es", "en", "ca")
LANG_LABELS = {"es": "Español", "en": "English", "ca": "Català"}


def set_lang(lang: str) -> None:
    global _LANG
    if lang in SUPPORTED:
        _LANG = lang


def get_lang() -> str:
    return _LANG


_T: dict = {

    # ── Genérico ─────────────────────────────────────────────────────────────────
    "quit_binding":     {"es": "Salir",                    "en": "Quit",                     "ca": "Surt"},
    "back_binding":     {"es": "Volver",                   "en": "Back",                     "ca": "Torna"},
    "btn_start":        {"es": "▶  Iniciar",              "en": "▶  Start",               "ca": "▶  Inicia"},
    "btn_back":         {"es": "⬅  Volver",               "en": "⬅  Back",                "ca": "⬅  Torna"},
    "btn_back_menu":    {"es": "⬅ Volver al menú",        "en": "⬅ Back to menu",         "ca": "⬅ Torna al menú"},
    "btn_cancel":       {"es": "⬅ Volver al menú",        "en": "⬅ Back to menu",         "ca": "⬅ Torna al menú"},
    "btn_test":         {"es": "🔌 Probar conexión",      "en": "🔌 Test connection",      "ca": "🔌 Prova connexió"},
    "btn_reset_prompt": {"es": "↺  Restaurar prompt por defecto", "en": "↺  Restore default prompt", "ca": "↺  Restaurar prompt per defecte"},
    "btn_refresh":      {"es": "🔄 Actualizar",           "en": "🔄 Refresh",              "ca": "🔄 Actualitza"},
    "btn_ok":           {"es": "OK",                      "en": "OK",                      "ca": "D'acord"},
    "testing":          {"es": "⏳ Probando…",            "en": "⏳ Testing…",             "ca": "⏳ Provant…"},
    "advanced_opts":    {"es": "⚙️  Opciones avanzadas",  "en": "⚙️  Advanced options",    "ca": "⚙️  Opcions avançades"},

    # ── Menú principal ────────────────────────────────────────────────────────────
    "app_subtitle":  {"es": "Elige un modo:",     "en": "Choose a mode:",     "ca": "Tria un mode:"},
    "menu_images":   {
        "es": "🖼️   Imágenes → PDF / PDF+OCR   (procesar imágenes desde cero)",
        "en": "🖼️   Images → PDF / PDF+OCR      (process images from scratch)",
        "ca": "🖼️   Imatges → PDF / PDF+OCR      (processar imatges des de zero)",
    },
    "menu_pdf_ocr":  {
        "es": "📄   PDF → PDF+OCR              (añadir OCR a PDFs existentes)",
        "en": "📄   PDF → PDF+OCR               (add OCR to existing PDFs)",
        "ca": "📄   PDF → PDF+OCR               (afegir OCR a PDFs existents)",
    },
    "menu_status":   {"es": "📊   Ver estado",        "en": "📊   View status",      "ca": "📊   Veure estat"},
    "menu_api":      {"es": "🌐   Iniciar API REST",   "en": "🌐   Start REST API",   "ca": "🌐   Iniciar API REST"},
    "menu_exit":     {"es": "❌   Salir",              "en": "❌   Exit",             "ca": "❌   Surt"},
    "menu_language": {"es": "🌐 Idioma",              "en": "🌐 Language",           "ca": "🌐 Idioma"},

    # ── Secciones ─────────────────────────────────────────────────────────────────
    "sec_dirs":     {"es": "[bold]📁 Directorios[/bold]",      "en": "[bold]📁 Directories[/bold]",     "ca": "[bold]📁 Directoris[/bold]"},
    "sec_engine":   {"es": "[bold]🤖 Motor OCR[/bold]",        "en": "[bold]🤖 OCR Engine[/bold]",      "ca": "[bold]🤖 Motor OCR[/bold]"},
    "sec_prompt":   {"es": "[bold]💬 Prompt OCR[/bold]",       "en": "[bold]💬 OCR Prompt[/bold]",      "ca": "[bold]💬 Prompt OCR[/bold]"},

    # ── Labels de campos ──────────────────────────────────────────────────────────
    "lbl_input_dir":    {"es": "Entrada (cada subcarpeta = un PDF):",           "en": "Input (each subfolder = one PDF):",            "ca": "Entrada (cada subcarpeta = un PDF):"},
    "lbl_output_dir":   {"es": "Salida:",                                        "en": "Output:",                                      "ca": "Sortida:"},
    "lbl_engine":       {"es": "Motor:",                                         "en": "Engine:",                                      "ca": "Motor:"},
    "lbl_model":        {"es": "Modelo:",                                        "en": "Model:",                                       "ca": "Model:"},
    "lbl_model_custom": {"es": "o escribe un modelo personalizado (tiene prioridad)", "en": "or type a custom model (takes priority)", "ca": "o escriu un model personalitzat (té prioritat)"},
    "lbl_api_key":      {"es": "API Key (o variable ANTHROPIC / OPENAI / OPENROUTER_API_KEY):", "en": "API Key (or ANTHROPIC / OPENAI / OPENROUTER_API_KEY env var):", "ca": "API Key (o variable ANTHROPIC / OPENAI / OPENROUTER_API_KEY):"},
    "lbl_base_url":     {"es": "Base URL (OpenRouter / Ollama — vacío = defecto):",             "en": "Base URL (OpenRouter / Ollama — empty = default):",              "ca": "Base URL (OpenRouter / Ollama — buit = defecte):"},
    "lbl_format":       {"es": "Formato de salida:",            "en": "Output format:",               "ca": "Format de sortida:"},
    "lbl_workers":      {"es": "Workers (páginas en paralelo — solo visión):", "en": "Workers (parallel pages — vision only):", "ca": "Workers (pàgines en paral·lel — només visió):"},
    "lbl_lang_tess":    {"es": "Idioma Tesseract:",              "en": "Tesseract language:",           "ca": "Idioma Tesseract:"},
    "lbl_ocr_on":       {"es": "OCR activado (desactivar = PDF sin capa de texto):", "en": "OCR enabled (disable = PDF without text layer):", "ca": "OCR activat (desactivar = PDF sense capa de text):"},
    "lbl_force":        {"es": "Forzar reprocesado (ignora estado guardado, solo esta vez):", "en": "Force reprocess (ignore saved state, this time only):", "ca": "Forçar reproces (ignora estat guardat, només aquest cop):"},
    "lbl_delete_orig":  {"es": "🗑  Eliminar imágenes originales tras verificar PDF (¡irreversible!):", "en": "🗑  Delete original images after verifying PDF (irreversible!):", "ca": "🗑  Eliminar imatges originals després de verificar el PDF (irreversible!):"},
    "lbl_prompt":       {"es": "Instrucciones para el modelo de visión:",        "en": "Instructions for the vision model:",           "ca": "Instruccions per al model de visió:"},
    "lbl_pdf_input":    {"es": "PDF de entrada o directorio con PDFs:",          "en": "Input PDF or directory with PDFs:",            "ca": "PDF d'entrada o directori amb PDFs:"},
    "lbl_pdf_output":   {"es": "Directorio de salida (PDFs con OCR):",           "en": "Output directory (OCR PDFs):",                 "ca": "Directori de sortida (PDFs amb OCR):"},

    # ── Formatos PDF ──────────────────────────────────────────────────────────────
    "fmt_pdf":          {"es": "PDF estándar",                                   "en": "Standard PDF",                                 "ca": "PDF estàndard"},
    "fmt_pdf_a":        {"es": "PDF/A-2b — archival",                            "en": "PDF/A-2b — archival",                          "ca": "PDF/A-2b — arxiu"},
    "fmt_compressed":   {"es": "Comprimido (WebP→JPEG) — ~50% más pequeño",     "en": "Compressed (WebP→JPEG) — ~50% smaller",        "ca": "Comprimit (WebP→JPEG) — ~50% més petit"},

    # ── Progreso / log ────────────────────────────────────────────────────────────
    "log_starting":     {"es": "▶ Iniciando procesamiento...", "en": "▶ Starting processing...", "ca": "▶ Iniciant el processament..."},
    "log_merging":      {"es": "⎇ Mergeando",                  "en": "⎇ Merging",                "ca": "⎇ Fusionant"},
    "log_rebuilding":   {"es": "⎇ Reconstruyendo PDF…",        "en": "⎇ Rebuilding PDF…",        "ca": "⎇ Reconstruint PDF…"},
    "log_verified":     {"es": "✔ Verificado",                 "en": "✔ Verified",               "ca": "✔ Verificat"},
    "log_verify_fail":  {"es": "✗ Verificación fallida",       "en": "✗ Verification failed",    "ca": "✗ Verificació fallida"},
    "log_cancelled":    {"es": "[yellow]⚠ Proceso cancelado[/yellow]",          "en": "[yellow]⚠ Process cancelled[/yellow]",      "ca": "[yellow]⚠ Procés cancel·lat[/yellow]"},
    "log_completed":    {"es": "🎉 ¡Proceso completado!",      "en": "🎉 Process completed!",     "ca": "🎉 Procés completat!"},
    "log_pdfs_done":    {"es": "PDFs con OCR",                 "en": "OCR PDFs",                 "ca": "PDFs amb OCR"},
    "log_merge_fail":   {"es": "merge fallido — activa 'Forzar reprocesado' para reintentar", "en": "merge failed — enable 'Force reprocess' to retry", "ca": "fusió fallida — activa 'Forçar reproces' per reintentar"},
    "log_fail":         {"es": "fallo",                        "en": "failed",                   "ca": "error"},
    "log_del_ok":       {"es": "🗑 Originales eliminados",     "en": "🗑 Originals deleted",     "ca": "🗑 Originals eliminats"},
    "log_del_fail":     {"es": "⚠ No se pudieron eliminar los originales", "en": "⚠ Could not delete originals", "ca": "⚠ No s'han pogut eliminar els originals"},
    "back_done":        {"es": "⬅ Volver",                    "en": "⬅ Back",                   "ca": "⬅ Torna"},

    # ── Estado ────────────────────────────────────────────────────────────────────
    "status_title":     {"es": "\n[bold]📊 Estado de procesamiento[/bold]\n",   "en": "\n[bold]📊 Processing status[/bold]\n",         "ca": "\n[bold]📊 Estat del processament[/bold]\n"},
    "status_outdir":    {"es": "Directorio de salida:",         "en": "Output directory:",            "ca": "Directori de sortida:"},
    "status_indir":     {"es": "Directorio de entrada (opcional, para ver pendientes):", "en": "Input directory (optional, to see pending):", "ca": "Directori d'entrada (opcional, per veure pendents):"},
    "col_book":         {"es": "Libro",                         "en": "Book",                         "ca": "Llibre"},
    "col_pages":        {"es": "Páginas",                       "en": "Pages",                        "ca": "Pàgines"},
    "col_status":       {"es": "Estado",                        "en": "Status",                       "ca": "Estat"},
    "st_done":          {"es": "[green]✅ completo[/green]",    "en": "[green]✅ done[/green]",       "ca": "[green]✅ fet[/green]"},
    "st_pending":       {"es": "[white]⏸ pendiente[/white]",   "en": "[white]⏸ pending[/white]",    "ca": "[white]⏸ pendent[/white]"},

    # ── Errores ───────────────────────────────────────────────────────────────────
    "err_input_req":    {"es": "El directorio de entrada es obligatorio", "en": "Input directory is required", "ca": "El directori d'entrada és obligatori"},
    "err_not_exists":   {"es": "No existe",                     "en": "Does not exist",               "ca": "No existeix"},
    "err_no_images":    {
        "es": "No se encontraron imágenes.\n\nAcepta:\n• Directorio con subcarpetas de imágenes (1 PDF por subcarpeta)\n• Directorio con imágenes directamente (1 PDF)",
        "en": "No images found.\n\nAccepts:\n• Directory with image subfolders (1 PDF per subfolder)\n• Directory with images directly (1 PDF)",
        "ca": "No s'han trobat imatges.\n\nAccepta:\n• Directori amb subcarpetes d'imatges (1 PDF per subcarpeta)\n• Directori amb imatges directament (1 PDF)",
    },
    "err_ui":           {"es": "error UI",                      "en": "UI error",                     "ca": "error UI"},

    # ── API Serve ─────────────────────────────────────────────────────────────────
    "serve_title":      {"es": "\n[bold]🌐 API REST[/bold]\n",  "en": "\n[bold]🌐 REST API[/bold]\n", "ca": "\n[bold]🌐 API REST[/bold]\n"},
    "serve_desc":       {"es": "El servidor API permite conectar una web u otros clientes.", "en": "The API server allows connecting a web app or other clients.", "ca": "El servidor API permet connectar una web o altres clients."},
    "serve_host":       {"es": "Host:",                         "en": "Host:",                        "ca": "Host:"},
    "serve_port":       {"es": "Puerto:",                       "en": "Port:",                        "ca": "Port:"},
    "btn_serve_start":  {"es": "▶  Iniciar servidor",          "en": "▶  Start server",              "ca": "▶  Inicia servidor"},
    "serve_active":     {"es": "✅ Servidor activo",            "en": "✅ Server running",            "ca": "✅ Servidor actiu"},
    "serve_hint":       {"es": "Para iniciar el API en otra terminal:", "en": "To start the API in another terminal:", "ca": "Per iniciar l'API en un altre terminal:"},

    # ── PDF→OCR pantalla ──────────────────────────────────────────────────────────
    "pdf_ocr_title":    {"es": "[bold]📄 PDF → PDF+OCR[/bold]", "en": "[bold]📄 PDF → PDF+OCR[/bold]", "ca": "[bold]📄 PDF → PDF+OCR[/bold]"},
    "pdf_proc_start":   {"es": "▶ Iniciando…",                  "en": "▶ Starting…",                  "ca": "▶ Iniciant…"},
    "pdf_done_fmt":     {"es": "PDFs procesados",               "en": "PDFs processed",               "ca": "PDFs processats"},

    # ── Model selection ───────────────────────────────────────────────────────────
    "no_applies":           {"es": "(no aplica)",                         "en": "(n/a)",                              "ca": "(no aplica)"},
    "detecting_ollama":     {"es": "⏳ detectando modelos instalados…",   "en": "⏳ detecting installed models…",      "ca": "⏳ detectant models instal·lats…"},
    "loading_openrouter":   {"es": "⏳ cargando modelos de OpenRouter…",  "en": "⏳ loading OpenRouter models…",       "ca": "⏳ carregant models d'OpenRouter…"},
    "enter_api_key":        {"es": "(introduce una API key para ver los modelos disponibles)", "en": "(enter an API key to see available models)", "ca": "(introdueix una API key per veure els models disponibles)"},
    "no_vision_models":     {"es": "(ningún modelo de visión disponible)", "en": "(no vision models available)",      "ca": "(cap model de visió disponible)"},
    "error_loading":        {"es": "(error al cargar modelos:",           "en": "(error loading models:",             "ca": "(error en carregar models:"},
    "no_models_installed":  {"es": "(ningún modelo instalado)",           "en": "(no models installed)",              "ca": "(cap model instal·lat)"},
    "ollama_unavailable":   {"es": "(Ollama no disponible en localhost)", "en": "(Ollama not available on localhost)", "ca": "(Ollama no disponible en localhost)"},

    # ── Worker options ────────────────────────────────────────────────────────────
    "worker_1":  {"es": "1 — secuencial",  "en": "1 — sequential",  "ca": "1 — seqüencial"},
    "worker_3":  {"es": "3 — recomendado", "en": "3 — recommended", "ca": "3 — recomanat"},
    "worker_5":  {"es": "5 — rápido",      "en": "5 — fast",        "ca": "5 — ràpid"},
    "worker_10": {"es": "10 — agresivo",   "en": "10 — aggressive", "ca": "10 — agressiu"},
    "worker_20": {"es": "20 — máximo",     "en": "20 — maximum",    "ca": "20 — màxim"},

    # ── Format labels (short) ─────────────────────────────────────────────────────
    "fmt_short_pdf":        {"es": "PDF",         "en": "PDF",          "ca": "PDF"},
    "fmt_short_pdf_a":      {"es": "PDF/A",       "en": "PDF/A",        "ca": "PDF/A"},
    "fmt_short_compressed": {"es": "Comprimido",  "en": "Compressed",   "ca": "Comprimit"},

    # ── Test / connection ─────────────────────────────────────────────────────────
    "test_ok":      {"es": "[green]✔[/green]", "en": "[green]✔[/green]", "ca": "[green]✔[/green]"},
    "test_fail":    {"es": "[red]✗[/red]",     "en": "[red]✗[/red]",     "ca": "[red]✗[/red]"},
    "testing_conn": {"es": "⏳ Probando conexión…", "en": "⏳ Testing connection…", "ca": "⏳ Provant la connexió…"},
    "conn_ok":      {"es": "Conexión OK",           "en": "Connection OK",          "ca": "Connexió OK"},
    "conn_fail":    {"es": "Fallo de conexión",     "en": "Connection failed",      "ca": "Fallo de connexió"},

    # ── Process screen ────────────────────────────────────────────────────────────
    "proc_general":     {"es": "General: ",     "en": "General: ",    "ca": "General: "},
    "log_no_ocr":       {"es": "[dim]sin OCR[/dim]",        "en": "[dim]no OCR[/dim]",         "ca": "[dim]sense OCR[/dim]"},
    "log_ui_error":     {"es": "error UI",                  "en": "UI error",                   "ca": "error UI"},
    "log_books_of":     {"es": "libros",                    "en": "books",                      "ca": "llibres"},
    "log_pages_of":     {"es": "páginas",                   "en": "pages",                      "ca": "pàgines"},
    "log_pags":         {"es": "págs",                     "en": "pgs",                        "ca": "pàgs"},
    "log_done_count":   {"es": "completados",              "en": "done",                       "ca": "completats"},

    # ── Status screen ──────────────────────────────────────────────────────────────
    "status_outdir_lbl": {"es": "Directorio de salida:",            "en": "Output directory:",          "ca": "Directori de sortida:"},
    "status_indir_lbl":  {"es": "\nDirectorio de entrada (opcional, para ver pendientes):", "en": "\nInput directory (optional, to see pending):", "ca": "\nDirectori d'entrada (opcional, per veure pendents):"},

    # ── Serve screen ───────────────────────────────────────────────────────────────
    "serve_hint_start": {"es": "Iniciar API en otra terminal:", "en": "Start API in another terminal:", "ca": "Inicia l'API en un altre terminal:"},
    "serve_log_start":  {"es": "▶ Iniciando API en",           "en": "▶ Starting API on",             "ca": "▶ Iniciant API a"},
    "serve_log_swagger": {"es": "   Swagger:",                 "en": "   Swagger:",                   "ca": "   Swagger:"},
    "serve_log_warn":   {"es": "   (el servidor se ejecuta en la terminal donde lanzaste el TUI)", "en": "   (the server runs in the terminal where you launched the TUI)", "ca": "   (el servidor s'executa a la terminal on has llançat el TUI)"},
}


def t(key: str) -> str:
    """Retorna el string traducido al idioma activo."""
    entry = _T.get(key, {})
    return entry.get(_LANG, entry.get("es", key))
