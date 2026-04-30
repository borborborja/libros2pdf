# libros2pdf

> Convierte imágenes escaneadas de libros históricos en PDFs con capa de texto OCR.

**libros2pdf** procesa directorios de imágenes escaneadas (JPG, PNG, TIF) y genera archivos PDF con una capa OCR invisible, haciéndolos completamente buscables y con capacidad de copiar y pegar. Diseñado para registros parroquiales históricos, admite cinco motores OCR: desde el gratuito Tesseract local hasta modelos de visión en la nube como Gemini, Claude y GPT-4o.

[English documentation →](README.md)

---

## Características

- **Cinco motores OCR**: Tesseract (local, gratis), Ollama (local), OpenRouter, Claude, OpenAI
- **Imágenes → PDF+OCR**: un PDF por subcarpeta, ordenado automáticamente
- **PDF existente → PDF+OCR**: añade capa de texto a cualquier PDF ya escaneado
- **Tres formatos de salida**: PDF estándar, PDF/A-2b archivístico, comprimido (~50% menos)
- **TUI interactiva**: barras de progreso en tiempo real, log en vivo, seguimiento por libro
- **API REST**: jobs en segundo plano, Server-Sent Events, Swagger UI
- **Reanudable**: el estado se guarda tras cada página — reinicia y continúa donde lo dejaste
- **Paralelismo configurable**: workers concurrentes para APIs de visión
- **Prompt personalizable**: adapta las instrucciones de transcripción a tu tipo de documento
- **Verificación de integridad**: cada PDF de salida se verifica antes de marcarse como completado
- **i18n**: interfaz disponible en español, inglés y catalán

---

## Instalación

```bash
# Dependencias principales
pip install pillow pikepdf pymupdf rich textual

# Backends de visión en la nube (instala solo los que necesites)
pip install openai          # OpenAI y OpenRouter
pip install anthropic       # Claude

# Servidor API
pip install fastapi uvicorn
```

**Tesseract** (OCR local gratuito):

```bash
# macOS
brew install tesseract tesseract-lang

# Debian / Ubuntu
sudo apt install tesseract-ocr tesseract-ocr-spa tesseract-ocr-lat

# Windows — descarga el instalador de https://github.com/UB-Mannheim/tesseract/wiki
```

---

## Inicio rápido

```bash
# TUI interactiva (recomendada para el primer uso)
python3 -m libros2pdf

# CLI — imágenes a PDF con Tesseract
python3 -m libros2pdf ./escaneos ./salida

# CLI — imágenes a PDF con OpenRouter (mejor calidad para manuscritos)
python3 -m libros2pdf ./escaneos ./salida \
  --engine openrouter \
  --model google/gemini-2.5-flash-lite \
  --api-key sk-or-v1-...

# Añadir capa OCR a PDFs existentes
python3 -m libros2pdf ocr-pdf ./pdfs_existentes ./pdfs_salida \
  --engine openrouter \
  --model google/gemini-2.5-flash-lite \
  --api-key sk-or-v1-...

# Servidor API REST
python3 -m libros2pdf serve
# → http://127.0.0.1:8000/docs
```

---

## Estructura de directorios

libros2pdf espera **una subcarpeta por libro**. Cada subcarpeta genera un PDF:

```
escaneos/
├── BAUTISMOS 01. 1850-1860/
│   ├── IMG_0001.JPG
│   ├── IMG_0002.JPG
│   └── ...
├── BAUTISMOS 02. 1861-1870/
│   └── ...
└── BAUTISMOS 03. 1871-1880/
    └── ...
```

Ejecutar `python3 -m libros2pdf ./escaneos ./salida` produce:

```
salida/
├── BAUTISMOS 01. 1850-1860.pdf
├── BAUTISMOS 02. 1861-1870.pdf
├── BAUTISMOS 03. 1871-1880.pdf
└── estado.json         ← estado para reanudar
```

Si una carpeta contiene imágenes directamente (sin subcarpetas), se genera un único PDF.

Formatos de imagen admitidos: **JPG, JPEG, PNG, TIF, TIFF** (sin distinción de mayúsculas). Los archivos se ordenan con orden natural (`IMG_2` antes que `IMG_10`).

---

## Referencia de la CLI

### `process` — imágenes → PDF

```bash
python3 -m libros2pdf process <directorio_entrada> [directorio_salida] [opciones]
# forma corta (detectada automáticamente cuando el primer argumento es una ruta):
python3 -m libros2pdf <directorio_entrada> [directorio_salida] [opciones]
```

| Opción | Por defecto | Descripción |
|---|---|---|
| `--engine` | `tesseract` | Motor OCR: `tesseract`, `claude`, `openai`, `openrouter`, `ollama` |
| `--model` | *(según motor)* | Nombre del modelo (ej. `google/gemini-2.5-flash-lite`, `claude-sonnet-4-6`) |
| `--api-key` | variable de entorno | API key (o usa `OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`) |
| `--base-url` | *(según motor)* | URL base de la API (útil para OpenRouter, Ollama o cualquier endpoint compatible con OpenAI) |
| `--lang` | `spa+lat` | Códigos de idioma Tesseract separados por `+` (ej. `spa`, `spa+lat`, `spa+lat+equ`) |
| `--psm` | `6` | Modo de segmentación de página Tesseract: `3` = auto, `6` = bloque uniforme |
| `--dpi` | `250` | Resolución objetivo para rasterizar páginas |
| `--workers` | `3` | Páginas en paralelo para backends de visión (ignorado con Tesseract) |
| `--prompt` | *(incorporado)* | Prompt de transcripción personalizado para backends de visión |
| `--format` | `pdf` | Formato de salida: `pdf`, `pdf_a` (PDF/A-2b archivístico), `compressed` (~50% menos) |
| `--no-ocr` | `false` | Saltar OCR — genera PDF solo con imagen (mucho más rápido) |
| `--force` | `false` | Ignorar estado guardado y reprocesar todo |
| `--delete-originals` | `false` | Eliminar la carpeta de imágenes originales tras verificar el PDF (**irreversible**) |
| `--tessdata` | `$TESSDATA_PREFIX` | Ruta personalizada a los datos de idioma de Tesseract |
| `--no-rich` | `false` | Desactivar barras de progreso (útil para scripts o piping) |

### `ocr-pdf` — añadir OCR a PDFs existentes

```bash
python3 -m libros2pdf ocr-pdf <entrada> [directorio_salida] [opciones]
```

`<entrada>` puede ser un único archivo PDF o un directorio de PDFs.

| Opción | Por defecto | Descripción |
|---|---|---|
| `--engine` | `openrouter` | Motor OCR |
| `--model` | *(según motor)* | Nombre del modelo |
| `--api-key` | variable de entorno | API key |
| `--base-url` | *(según motor)* | URL base de la API |
| `--prompt` | *(incorporado)* | Prompt personalizado |
| `--format` | `pdf` | Formato de salida: `pdf`, `pdf_a`, `compressed` |
| `--workers` | `3` | Páginas en paralelo |
| `--dpi` | `250` | Resolución para rasterizar páginas del PDF |

### `tui` — interfaz interactiva de terminal

```bash
python3 -m libros2pdf tui
python3 -m libros2pdf        # por defecto si se ejecuta sin argumentos
```

### `serve` — servidor API REST

```bash
python3 -m libros2pdf serve [--host HOST] [--port PORT]
```

| Opción | Por defecto | Descripción |
|---|---|---|
| `--host` | `127.0.0.1` | Dirección de escucha (`0.0.0.0` para exponer en la red) |
| `--port` | `8000` | Puerto TCP |

### `status` — estado de procesamiento

```bash
python3 -m libros2pdf status [directorio_salida] [directorio_entrada]
```

---

## Motores OCR

| Motor | Tipo | Calidad manuscrito | Coste | Velocidad |
|---|---|---|---|---|
| `tesseract` | Local | ★★☆☆☆ | Gratis | Rápido (secuencial) |
| `ollama` | Local | ★★★☆☆ | Gratis | Medio |
| `openrouter` | Cloud | ★★★★★ | ~$0,001 / página | Rápido (paralelo) |
| `claude` | Cloud | ★★★★★ | ~$0,001 / página | Rápido (paralelo) |
| `openai` | Cloud | ★★★★☆ | ~$0,001 / página | Rápido (paralelo) |

**Recomendación para manuscritos históricos en español/latín**: OpenRouter con `google/gemini-2.5-flash-lite` — máxima precisión al mínimo coste.

### Ejemplos de modelos

```bash
# OpenRouter
--engine openrouter --model google/gemini-2.5-flash-lite
--engine openrouter --model anthropic/claude-haiku-4-5

# Claude directo
--engine claude --model claude-haiku-4-5-20251001
--engine claude --model claude-sonnet-4-6

# OpenAI
--engine openai --model gpt-4o-mini
--engine openai --model gpt-4o

# Ollama (local, sin coste)
--engine ollama --model llava:13b
--engine ollama --model llava:34b
```

---

## Formatos de salida

| Formato | Flag | Descripción |
|---|---|---|
| PDF estándar | `--format pdf` | Imagen + capa OCR invisible. Máxima fidelidad. |
| PDF/A-2b archivístico | `--format pdf_a` | Conforme a ISO 19005-2. Recomendado para preservación a largo plazo. |
| Comprimido | `--format compressed` | Imagen recomprimida vía WebP→JPEG (~50% de reducción de tamaño). |

---

## Prompt OCR personalizado

El prompt por defecto está ajustado para registros parroquiales históricos en español/latín. Puedes sobreescribirlo con `--prompt`:

```bash
python3 -m libros2pdf ./escaneos ./salida \
  --engine openrouter \
  --prompt "Transcribe cada palabra exactamente como aparece. Marca las ilegibles como [ilegible]."
```

En la TUI, edita el prompt en la sección *Opciones avanzadas* y guárdalo en `config/prompt.txt` para que persista entre sesiones.

Prompt por defecto:

```
Transcribe exactamente el texto visible en este documento histórico manuscrito.

- Copia el texto tal como aparece: respeta ortografía original, tildes y abreviaturas
- Si hay texto en latín, transcríbelo literalmente sin traducir
- Conserva la estructura: saltos de línea, párrafos y numeración de actas
- Marca palabras ilegibles como [ilegible] y palabras dudosas como [palabra?]
- Devuelve ÚNICAMENTE el texto transcrito, sin comentarios ni explicaciones
```

---

## Configuración

Los ajustes se guardan en `config/settings.json` (creado automáticamente al guardar por primera vez en la TUI):

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

El prompt OCR se almacena por separado en `config/prompt.txt`.

### Variables de entorno

```bash
export OPENROUTER_API_KEY=sk-or-v1-...
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
```

---

## Guía de la TUI

Lanza con `python3 -m libros2pdf`. Atajos de teclado:

| Tecla | Acción |
|---|---|
| Flechas / ratón | Navegar |
| Tab / Shift+Tab | Campo siguiente / anterior |
| Enter / Espacio | Activar botón o alternar |
| Escape | Volver atrás |
| q | Salir |

### Pantallas

| Pantalla | Descripción |
|---|---|
| Menú principal | Seleccionar flujo, cambiar idioma de la UI (ES / EN / CA) |
| Imágenes → PDF | Configurar motor, modelo, API key, formato, workers, prompt |
| PDF → PDF+OCR | Igual pero para PDFs existentes |
| Procesamiento | Barras de progreso por libro, ETA global, log, botón cancelar |
| Estado | Tabla de todos los libros con estado y tamaños de archivo |
| Servidor API | Iniciar el servidor REST desde la interfaz |

El botón **Probar conexión** valida tu API key y modelo antes de iniciar cualquier trabajo.

---

## API REST

Inicia el servidor:

```bash
python3 -m libros2pdf serve
# Swagger UI: http://127.0.0.1:8000/docs
```

### Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/process` | Iniciar job imágenes → PDF |
| `POST` | `/api/ocr-pdf` | Iniciar job PDF existente → PDF+OCR |
| `GET` | `/api/status` | Listar todos los jobs y su progreso |
| `GET` | `/api/books` | Listar libros de entrada y PDFs generados |
| `GET` | `/api/books/{nombre}/download` | Descargar un PDF generado |
| `GET` | `/api/events` | Stream Server-Sent Events (progreso en tiempo real) |
| `DELETE` | `/api/cancel` | Cancelar el job activo (`?job_id=...`) |
| `GET` | `/docs` | Swagger UI interactivo |

### Iniciar un job

```bash
# Imágenes → PDF
curl -X POST http://localhost:8000/api/process \
  -H "Content-Type: application/json" \
  -d '{
    "input_dir":  "/ruta/a/escaneos",
    "output_dir": "/ruta/a/salida",
    "engine":     "openrouter",
    "model":      "google/gemini-2.5-flash-lite",
    "api_key":    "sk-or-v1-...",
    "pdf_format": "pdf",
    "workers":    5
  }'

# PDFs existentes → añadir OCR
curl -X POST http://localhost:8000/api/ocr-pdf \
  -H "Content-Type: application/json" \
  -d '{
    "input_dir":  "/ruta/a/pdfs",
    "engine":     "openrouter",
    "model":      "google/gemini-2.5-flash-lite",
    "api_key":    "sk-or-v1-...",
    "pdf_format": "compressed"
  }'
```

### Eventos en tiempo real (SSE)

```bash
curl -N http://localhost:8000/api/events
```

Tipos de eventos:

| Tipo | Campos clave | Descripción |
|---|---|---|
| `BOOK_START` | `book`, `total` | Inicio del procesamiento de un libro |
| `PAGE_OK` | `book`, `page`, `total`, `file` | Página OCR completada correctamente |
| `PAGE_FAIL` | `book`, `page`, `file` | Fallo en el OCR de una página |
| `MERGE_START` | `book` | Uniendo PDFs de páginas en el archivo final |
| `BOOK_DONE` | `book`, `pages`, `size_mb` | Libro completado |
| `VERIFY_OK` / `VERIFY_FAIL` | `book`, `file` | Resultado de la verificación de integridad |
| `ALL_DONE` | `result` | Todo el procesamiento completado |
| `LOG` | `message` | Mensaje informativo |
| `ping` | — | Keepalive (cada 10 s) |

### Campos de `ProcessRequest`

| Campo | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `input_dir` | string | **requerido** | Directorio con imágenes |
| `output_dir` | string | padre de entrada | Directorio de salida |
| `engine` | string | `tesseract` | Motor OCR |
| `model` | string | null | Nombre del modelo |
| `api_key` | string | null | API key |
| `base_url` | string | null | URL base de la API |
| `lang` | string | `spa+lat` | Idiomas Tesseract |
| `psm` | int | `6` | PSM de Tesseract |
| `dpi` | int | `250` | DPI objetivo |
| `workers` | int | `5` | Workers paralelos |
| `pdf_format` | string | `pdf` | `pdf`, `pdf_a` o `compressed` |
| `ocr_prompt` | string | null | Prompt personalizado |
| `skip_ocr` | bool | `false` | PDF solo imagen |
| `force` | bool | `false` | Ignorar estado guardado |
| `delete_originals` | bool | `false` | Eliminar imágenes originales tras el PDF |
| `tessdata` | string | null | TESSDATA_PREFIX personalizado |

### Campos de `OcrPdfRequest`

| Campo | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `input_dir` | string | **requerido** | Archivo PDF o directorio |
| `output_dir` | string | null | Directorio de salida |
| `engine` | string | `openrouter` | Motor OCR |
| `model` | string | null | Nombre del modelo |
| `api_key` | string | null | API key |
| `base_url` | string | null | URL base de la API |
| `ocr_prompt` | string | null | Prompt personalizado |
| `dpi` | int | `250` | DPI objetivo |
| `workers` | int | `3` | Workers paralelos |
| `pdf_format` | string | `pdf` | `pdf`, `pdf_a` o `compressed` |

---

## Licencia

MIT — ver [LICENSE](LICENSE).
