-- Ejecutar con un usuario administrador, por ejemplo:
-- psql -U postgres -f database/create_database.sql

DO
$$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_roles
        WHERE rolname = 'geriafab_usuario'
    ) THEN
        CREATE ROLE geriafab_usuario LOGIN PASSWORD 'geriafab_clave';
    END IF;
END
$$;

SELECT 'CREATE DATABASE geriafab_bd OWNER geriafab_usuario'
WHERE NOT EXISTS (
    SELECT 1
    FROM pg_database
    WHERE datname = 'geriafab_bd'
)\gexec

GRANT ALL PRIVILEGES ON DATABASE geriafab_bd TO geriafab_usuario;
