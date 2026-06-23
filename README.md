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

## Fallos funcionales y mitigaciones

Esta seccion resume problemas esperados del asistente de voz, autenticacion, perfil, IA y conexion con el frontend. Sirve como checklist para pruebas y soporte.

### Voz y escucha

| Fallo posible | Que puede ver el usuario | Mitigacion actual o recomendada |
| --- | --- | --- |
| El microfono no tiene permisos en el navegador | El asistente no escucha o no aparece transcripcion | Pedir permiso de microfono, usar HTTPS en produccion y mostrar un aviso si el navegador bloquea el microfono. |
| El audio llega vacio | El asistente responde algo fuera de contexto o no responde | El backend filtra entradas vacias con `is_voice_noise()` y evita enviarlas a Gemini. |
| Ruido de fondo o muletillas | Se transcribe `eh`, `mmm`, `este`, `sin audio`, etc. | `DEFAULT_VOICE_NOISE_PATTERNS` descarta frases de ruido comunes antes de llamar a Gemini. |
| Texto repetido por mala transcripcion | El prompt llega como palabras repetidas | `normalize_voice_text()` compacta espacios, signos repetidos y palabras repetidas tres o mas veces. |
| El usuario interrumpe mientras el asistente habla | Puede mezclarse audio anterior con una nueva pregunta | En el frontend conviene detener la reproduccion actual antes de iniciar nueva escucha y cancelar la peticion anterior si sigue pendiente. |
| El reconocimiento corta la frase | La respuesta parece incompleta o equivocada | En el frontend conviene esperar un pequeno silencio antes de enviar, y permitir reintentar la pregunta. |
| El asistente saluda en cada respuesta | Conversacion poco natural | El prompt indica no saludar si la conversacion ya empezo y `strip_repeated_greeting()` elimina saludos iniciales repetidos. |
| El historial arrastra contexto viejo | Respuestas con informacion anterior que ya no aplica | El historial se limita con `MAX_HISTORY_MESSAGES` y `HISTORY_TTL_SECONDS`; ajustar esos valores si la memoria es muy larga o muy corta. |

### Interrupciones y latencia

| Fallo posible | Que puede ver el usuario | Mitigacion actual o recomendada |
| --- | --- | --- |
| Gemini demora demasiado | El usuario espera sin respuesta | El backend usa timeouts configurables: `GEMINI_CONNECT_TIMEOUT`, `GEMINI_READ_TIMEOUT`, `GEMINI_WRITE_TIMEOUT` y `GEMINI_POOL_TIMEOUT`. |
| El usuario presiona varias veces hablar/enviar | Respuestas duplicadas o fuera de orden | En el frontend conviene bloquear el boton mientras hay una solicitud activa o cancelar la anterior. |
| La IA devuelve error | Mensaje con `Gemini respondio con error ...` | Revisar API key, cuota, modelo y endpoint. El backend devuelve `error_id` para ubicar el error en logs. |
| Se pierde la conexion durante una respuesta | El usuario no recibe audio o texto | Mostrar estado de carga, permitir reintento y consultar `/api/health` para saber si backend, DB y Gemini estan configurados. |

### Login, registro y sesiones

| Fallo posible | Que puede ver el usuario | Mitigacion actual o recomendada |
| --- | --- | --- |
| Correo duplicado en registro | `El correo ya esta registrado` | El backend responde `409`; el frontend debe mostrar "Ya existe una cuenta con este correo" y ofrecer iniciar sesion. |
| Contrasena muy corta | `La contrasena debe tener al menos 6 caracteres` | El backend responde `400`; validar tambien en el formulario antes de enviar. |
| Campos vacios | `Completa nombre, correo y contrasena` o `Ingresa correo y contrasena` | Validar campos requeridos en frontend y mantener mensajes claros. |
| Credenciales incorrectas | `Correo o contrasena incorrectos` | El backend responde `401`; no especificar si fallo correo o contrasena para no filtrar usuarios existentes. |
| Sesion vencida o token invalido | `Sesion invalida o expirada` | El backend responde `401`; borrar token local y volver al login. |
| Google Login sin configurar | `Google Login no esta configurado` | Definir `GOOGLE_CLIENT_ID` en `.env` y en el proveedor de despliegue. |
| Credencial de Google invalida | `Credencial de Google invalida` o correo no verificado | Verificar que el frontend use el mismo Client ID y que el correo de Google este verificado. |
| Abrir `/api/auth/register` en el navegador | `Method Not Allowed` | Es normal: esa ruta acepta `POST`, no `GET`. Probar desde formulario, Postman o `Invoke-RestMethod`. |

### Perfil del adulto mayor

| Fallo posible | Que puede ver el usuario | Mitigacion actual o recomendada |
| --- | --- | --- |
| El perfil no esta guardado | El asistente responde sin datos personales | Si no hay perfil, `/api/profile` devuelve `profile: null`; el frontend debe pedir completar el formulario. |
| Datos incompletos del perfil | Respuestas menos personalizadas | `build_profile_context()` solo incluye campos con contenido; permitir guardar borradores y sugerir completar datos clave. |
| Horarios invalidos | Error al guardar o datos inconsistentes | Validar formato `HH:MM` en frontend antes de enviar `wakeTime` y `sleepTime`. |
| Medicamentos o contactos duplicados | El asistente puede repetir informacion | El backend reemplaza listas al guardar; el frontend debe permitir editar y eliminar items antes de guardar. |
| Perfil asociado a otro usuario | El usuario no ve sus datos | Las consultas usan el token de sesion; si cambia de cuenta, cerrar sesion y volver a entrar. |

### Base de datos

| Fallo posible | Que puede ver el usuario | Mitigacion actual o recomendada |
| --- | --- | --- |
| PostgreSQL apagado | Login, registro, historial y perfil fallan | Encender PostgreSQL y revisar `/api/health`; `database_available` debe ser `true`. |
| `DATABASE_URL` incorrecto | `Base de datos no disponible` o errores de conexion | Revisar usuario, clave, host, puerto y nombre exacto de la base. Evitar espacios al final como `geriafab_bd `. |
| Tablas faltantes | Errores al registrar, iniciar sesion o guardar perfil | Ejecutar `database/schema.sql` y reiniciar el backend; `init_database()` tambien crea tablas necesarias al iniciar. |
| Historial no se guarda | El asistente pierde contexto | Si PostgreSQL falla, el backend usa historial en memoria temporal. Revisar logs `PostgreSQL history disabled/read/write failed`. |
| Reinicio del servidor con DB caida | Se pierde historial en memoria | Restaurar conexion a PostgreSQL para persistir historial y sesiones. |

### Frontend y CORS

| Fallo posible | Que puede ver el usuario | Mitigacion actual o recomendada |
| --- | --- | --- |
| Frontend apunta a backend equivocado | `404` en `/api/auth/register` o `/api/auth/login` | En local usar `http://localhost:8000`. En produccion redeployar el backend correcto y configurar la URL base del frontend. |
| Error CORS | El navegador bloquea la peticion | Agregar el dominio del frontend a `CORS_ALLOWED_ORIGINS` o a `DEFAULT_CORS_ALLOWED_ORIGINS`. |
| Backend local apagado | `Failed to fetch`, `ERR_CONNECTION_REFUSED` | Iniciar Uvicorn en el puerto esperado: `python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000`. |
| Puerto cambiado | El frontend llama a un puerto sin servicio | Alinear la URL del frontend con el puerto real del backend. |
| Backend desplegado desactualizado | Local funciona, produccion da `404` | Confirmar `/api/health` en produccion y hacer redeploy del backend actual. |

### Seguridad y privacidad

| Riesgo | Impacto | Mitigacion actual o recomendada |
| --- | --- | --- |
| Exponer `.env` o API keys | Uso no autorizado de Gemini o base de datos | No subir `.env` al repositorio; usar variables de entorno del proveedor de despliegue. |
| Token guardado de forma insegura en frontend | Robo de sesion | Guardar el token con cuidado, limpiar al cerrar sesion y usar HTTPS en produccion. |
| Datos sensibles del adulto mayor | Riesgo de privacidad | Enviar a Gemini solo el contexto necesario y no mostrar datos internos en la respuesta. |
| Mensajes de error demasiado tecnicos | Confusion o exposicion de detalles | El backend devuelve mensajes controlados y `error_id`; los detalles deben revisarse en logs internos. |

### Checklist rapido de diagnostico

1. Abrir `http://localhost:8000/api/health`.
2. Confirmar `database_available: true`.
3. Confirmar `gemini_key_configured: true`.
4. Confirmar que el frontend use la URL correcta del backend.
5. Probar registro/login con `POST`, no abriendo la ruta directamente en el navegador.
6. Revisar consola del navegador para distinguir `404`, `401`, `409`, CORS y errores de red.
7. Revisar logs de Uvicorn si aparece un `error_id`.

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
