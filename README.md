# libros2pdf

Genera PDFs con OCR a partir de imágenes de libros parroquiales históricos.

## Características

- **Multi-motor OCR**: Tesseract (local), Claude, OpenAI, OpenRouter, Ollama
- **Interfaz TUI** interactiva con progreso en tiempo real
- **API REST** para integración con otras herramientas
- **Reanudable**: guarda el estado tras cada página
- **Paralelismo** configurable (workers) para APIs de visión
- **Verificación de integridad** del PDF final
- **Prompt personalizable** para el modelo de visión

## Instalación

```bash
pip install pillow pikepdf rich textual
# Para APIs de visión:
pip install openai anthropic
# Para PDF con capa de texto (búsqueda):
pip install pymupdf
```

Tesseract (opcional, OCR local):
```bash
brew install tesseract tesseract-lang  # macOS
```

## Uso

### TUI (interfaz interactiva)
```bash
python3 -m libros2pdf tui
python3 -m libros2pdf          # también abre la TUI
```

### CLI
```bash
# Con Tesseract (local, gratis)
python3 -m libros2pdf ./bautismos ./PDFs

# Con OpenRouter (recomendado para manuscritos)
python3 -m libros2pdf ./bautismos ./PDFs \
  --engine openrouter \
  --model google/gemini-2.5-flash-lite \
  --api-key sk-or-v1-...

# Con Claude
python3 -m libros2pdf ./bautismos ./PDFs \
  --engine claude \
  --model claude-haiku-4-5-20251001

# Con Ollama (local, sin coste)
python3 -m libros2pdf ./bautismos ./PDFs \
  --engine ollama \
  --model llava:13b

# Opciones adicionales
  --workers 5          # páginas en paralelo (visión)
  --no-ocr             # PDF solo imagen, sin capa de texto
  --force              # ignorar estado guardado
  --delete-originals   # borrar imágenes tras verificar PDF
  --prompt "..."       # prompt personalizado para el modelo
```

### API REST
```bash
python3 -m libros2pdf serve
# Abre http://127.0.0.1:8000/docs
```

## Estructura de directorios

El programa espera que el directorio de entrada contenga **subcarpetas**, una por libro:

```
bautismos/
  LIBRO 01. 1850-1860/
    IMG_0001.JPG
    IMG_0002.JPG
    ...
  LIBRO 02. 1861-1870/
    ...
```

Cada subcarpeta genera un PDF. También acepta un directorio con imágenes directamente (un único PDF).

## Configuración

```
config/
  settings.json    ← ajustes (ver settings.json.example)
  prompt.txt       ← prompt OCR personalizable
```

Copia `config/settings.json.example` a `config/settings.json` y edítalo. La API key también se puede pasar como variable de entorno:

```bash
export OPENROUTER_API_KEY=sk-or-v1-...
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
```

## Motores OCR

| Motor | Tipo | Calidad manuscrito | Coste |
|---|---|---|---|
| `tesseract` | Local | ★★ | Gratis |
| `ollama` | Local | ★★★ | Gratis |
| `openrouter` | Cloud | ★★★★★ | ~$0.001/pág |
| `claude` | Cloud | ★★★★★ | ~$0.001/pág |
| `openai` | Cloud | ★★★★ | ~$0.001/pág |

Para manuscritos históricos en español/latín se recomienda **OpenRouter** con `google/gemini-2.5-flash-lite` (calidad alta, coste muy bajo).
