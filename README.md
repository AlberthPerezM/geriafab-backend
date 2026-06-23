# Geriafab Backend (FastAPI)

Backend hecho con FastAPI que expone el endpoint `POST /api/gemini`, guarda historial en PostgreSQL y persiste usuarios, sesiones y datos del adulto mayor para GeriaBot.

## Requisitos previos

- Python 3.11 o superior
- PostgreSQL instalado y en ejecucion
- Una API key de Gemini

## Comandos para ejecutar

### 1. Entrar a la carpeta del proyecto

```powershell
cd C:\Users\Alberth\Desktop\Geriafab\geriafab-backend
```

### 2. Crear y activar el entorno virtual

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Si el entorno virtual ya existe, solo ejecuta:

```powershell
.\.venv\Scripts\Activate.ps1
```

### 3. Instalar dependencias

```powershell
pip install -r requirements.txt
```

### 4. Copiar variables de entorno

```powershell
copy .env.example .env
```

Despues de copiarlo, revisa el archivo `.env` y coloca tus claves reales:

```env
GEMINI_API_KEY=tu-api-key-real
DATABASE_URL=postgresql://geriafab_usuario:geriafab_clave@localhost:5432/geriafab_bd
```

### 5. Crear base de datos PostgreSQL

```powershell
psql -U postgres -f database/create_database.sql
```

### 6. Crear tablas

```powershell
psql -U geriafab_usuario -d geriafab_bd -f database/schema.sql
```

### 7. Ejecutar el backend

```powershell
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Tambien puedes ejecutarlo con:

```powershell
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 8. Probar que el backend esta funcionando

Abre esta URL en el navegador:

```text
http://localhost:8000
```

Tambien puedes probar el endpoint de Gemini con PowerShell:

```powershell
Invoke-RestMethod -Uri http://localhost:8000/api/gemini -Method Post -ContentType "application/json" -Body '{"prompt":"Hola"}'
```

## Resumen rapido

```powershell
cd C:\Users\Alberth\Desktop\Geriafab\geriafab-backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
psql -U postgres -f database/create_database.sql
psql -U geriafab_usuario -d geriafab_bd -f database/schema.sql
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## Errores comunes

- Si PowerShell bloquea la activacion del entorno virtual, ejecuta PowerShell como administrador y usa:

```powershell
Set-ExecutionPolicy RemoteSigned
```

- Si `psql` no se reconoce como comando, agrega PostgreSQL al `PATH` o ejecuta los scripts desde pgAdmin.
- Si falla la conexion a la base de datos, revisa que PostgreSQL este encendido y que `DATABASE_URL` coincida con el usuario, clave y base de datos.

## Datos de PostgreSQL

- Base de datos: `geriafab_bd`
- Usuario: `geriafab_usuario`
- Clave: `geriafab_clave`
- Tabla de historial: `mensajes_conversacion`
- Tabla de prompts: `archivos_prompt`
- Tabla de usuarios: `usuarios`
- Tabla de sesiones: `sesiones_usuario`
- Tabla de datos del adulto mayor: `perfiles_adulto_mayor`

## Endpoints principales

- `POST /api/auth/register`: crea usuario cuidador y devuelve token.
- `POST /api/auth/login`: inicia sesion y devuelve token.
- `POST /api/auth/google`: valida una credencial de Google y devuelve token.
- `POST /api/auth/logout`: revoca la sesion actual.
- `GET /api/auth/me`: devuelve el usuario autenticado.
- `GET /api/profile`: devuelve los datos del adulto mayor del usuario autenticado.
- `POST /api/profile`: guarda los datos del adulto mayor.
- `POST /api/gemini`: recibe `{ "prompt": "...", "profile": { ... } }`. Si llega un token, tambien puede cargar el perfil desde PostgreSQL y usarlo como contexto privado para GeriaBot.
