import os
import sys

from dotenv import load_dotenv
import psycopg


EXPECTED_TABLES = {
    "usuarios",
    "sesiones_usuario",
    "mensajes_conversacion",
    "adultos_mayores",
    "ficha_datos",
    "ficha_salud",
    "ficha_preferencias",
    "ficha_notas",
    "medicamentos_adulto_mayor",
    "contactos_emergencia",
}


def main() -> int:
    load_dotenv()
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        print("ERROR: DATABASE_URL no esta configurado en .env")
        return 1

    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                ping = cur.fetchone()[0]

                cur.execute("SELECT current_database(), current_user")
                database_name, database_user = cur.fetchone()

                cur.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name = ANY(%s)
                    ORDER BY table_name
                    """,
                    (list(EXPECTED_TABLES),),
                )
                found_tables = {row[0] for row in cur.fetchall()}

        print("OK: conexion a PostgreSQL funcionando")
        print(f"SELECT 1: {ping}")
        print(f"Base de datos: {database_name}")
        print(f"Usuario: {database_user}")
        print(f"Tablas encontradas: {', '.join(sorted(found_tables)) or 'ninguna'}")

        missing_tables = EXPECTED_TABLES - found_tables
        if missing_tables:
            print(f"ERROR: faltan tablas: {', '.join(sorted(missing_tables))}")
            print("Inicia el backend (main.py) una vez: init_database() crea el esquema automaticamente.")
            return 1

        return 0
    except Exception as exc:
        print("ERROR: no se pudo conectar a PostgreSQL")
        print(safe_text(str(exc)))
        return 1


def safe_text(value: str) -> str:
    return value.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
        sys.stdout.encoding or "utf-8"
    )


if __name__ == "__main__":
    sys.exit(main())
