-- Esquema de referencia de GeriaFab.
-- El backend (main.py -> init_database) crea y migra estas tablas automaticamente
-- al arrancar. Este archivo documenta el esquema y sirve para crearlo a mano:
--   psql -U geriafab_usuario -d geriafab_bd -f database/schema.sql

CREATE TABLE IF NOT EXISTS usuarios (
    id BIGSERIAL PRIMARY KEY,
    nombre VARCHAR(160) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    proveedor VARCHAR(30) NOT NULL DEFAULT 'email',
    creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sesiones_usuario (
    id BIGSERIAL PRIMARY KEY,
    usuario_id BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    token VARCHAR(160) NOT NULL UNIQUE,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ultimo_uso_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expira_en TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '7 days')
);

CREATE INDEX IF NOT EXISTS idx_sesiones_usuario_token
    ON sesiones_usuario (token);

-- Perfil raiz: un adulto mayor por fila, varios por apoderado (usuario).
CREATE TABLE IF NOT EXISTS adultos_mayores (
    id BIGSERIAL PRIMARY KEY,
    usuario_id BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    nombre VARCHAR(180) NOT NULL DEFAULT '',
    creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_adultos_mayores_usuario
    ON adultos_mayores (usuario_id);

-- Una tabla por apartado del formulario (relacion 1:1 con el perfil).
CREATE TABLE IF NOT EXISTS ficha_datos (
    id BIGSERIAL PRIMARY KEY,
    adulto_mayor_id BIGINT NOT NULL UNIQUE REFERENCES adultos_mayores(id) ON DELETE CASCADE,
    nombre VARCHAR(180) NOT NULL DEFAULT '',
    sobrenombre VARCHAR(180) NOT NULL DEFAULT '',
    nivel_movilidad VARCHAR(120) NOT NULL DEFAULT '',
    estado_positividad VARCHAR(20) NOT NULL DEFAULT '',
    estado_animo_general VARCHAR(180) NOT NULL DEFAULT '',
    habitacion_principal VARCHAR(180) NOT NULL DEFAULT '',
    particularidad TEXT NOT NULL DEFAULT '',
    detalles_movilidad TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS ficha_salud (
    id BIGSERIAL PRIMARY KEY,
    adulto_mayor_id BIGINT NOT NULL UNIQUE REFERENCES adultos_mayores(id) ON DELETE CASCADE,
    tiene_enfermedad_preexistente BOOLEAN NOT NULL DEFAULT FALSE,
    enfermedad_preexistente TEXT NOT NULL DEFAULT '',
    requiere_medicacion BOOLEAN NOT NULL DEFAULT FALSE,
    hora_levantarse TIME,
    hora_acostarse TIME
);

CREATE TABLE IF NOT EXISTS ficha_preferencias (
    id BIGSERIAL PRIMARY KEY,
    adulto_mayor_id BIGINT NOT NULL UNIQUE REFERENCES adultos_mayores(id) ON DELETE CASCADE,
    color_agrado VARCHAR(120) NOT NULL DEFAULT '',
    tema_gusto VARCHAR(180) NOT NULL DEFAULT '',
    actividades_diarias TEXT NOT NULL DEFAULT '',
    actividades_semanales TEXT NOT NULL DEFAULT '',
    detonantes_felicidad TEXT NOT NULL DEFAULT '',
    detonantes_relajacion TEXT NOT NULL DEFAULT '',
    detonantes_tristeza TEXT NOT NULL DEFAULT '',
    detonantes_molestia TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS ficha_notas (
    id BIGSERIAL PRIMARY KEY,
    adulto_mayor_id BIGINT NOT NULL UNIQUE REFERENCES adultos_mayores(id) ON DELETE CASCADE,
    notas_cuidador TEXT NOT NULL DEFAULT '',
    notas_adulto_mayor TEXT NOT NULL DEFAULT ''
);

-- Apartado Emergencia (1:N).
CREATE TABLE IF NOT EXISTS contactos_emergencia (
    id BIGSERIAL PRIMARY KEY,
    adulto_mayor_id BIGINT NOT NULL REFERENCES adultos_mayores(id) ON DELETE CASCADE,
    nombre VARCHAR(180) NOT NULL DEFAULT '',
    parentesco VARCHAR(180) NOT NULL DEFAULT '',
    telefono VARCHAR(80) NOT NULL DEFAULT '',
    orden INTEGER NOT NULL DEFAULT 0,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_contactos_emergencia_adulto
    ON contactos_emergencia (adulto_mayor_id, orden, id);

-- Medicamentos del apartado Salud (1:N).
CREATE TABLE IF NOT EXISTS medicamentos_adulto_mayor (
    id BIGSERIAL PRIMARY KEY,
    adulto_mayor_id BIGINT NOT NULL REFERENCES adultos_mayores(id) ON DELETE CASCADE,
    nombre VARCHAR(180) NOT NULL DEFAULT '',
    horario VARCHAR(180) NOT NULL DEFAULT '',
    color_forma VARCHAR(180) NOT NULL DEFAULT '',
    orden INTEGER NOT NULL DEFAULT 0,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_medicamentos_adulto_mayor
    ON medicamentos_adulto_mayor (adulto_mayor_id, orden, id);

-- Historial de conversacion, un hilo independiente por adulto mayor.
CREATE TABLE IF NOT EXISTS mensajes_conversacion (
    id BIGSERIAL PRIMARY KEY,
    adulto_mayor_id BIGINT REFERENCES adultos_mayores(id) ON DELETE CASCADE,
    sesion_id VARCHAR(120) NOT NULL DEFAULT 'default',
    rol VARCHAR(20) NOT NULL CHECK (rol IN ('user', 'model', 'system')),
    contenido TEXT NOT NULL,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mensajes_conversacion_adulto
    ON mensajes_conversacion (adulto_mayor_id, creado_en);
