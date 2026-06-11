# Geriafab Backend (FastAPI)

Instrucciones rápidas:

1. Crear virtualenv e instalar dependencias

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. Configurar variables de entorno (copiar `.env.example` → `.env`)

3. Ejecutar

```powershell
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

El backend expone `POST /api/gemini` que reenvía el JSON `{ "prompt": "..." }` a la URL definida en `GEMINI_API_URL` con el header `Authorization: Bearer <GEMINI_API_KEY>`.
