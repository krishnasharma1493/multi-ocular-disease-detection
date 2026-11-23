from sqlalchemy.engine import Engine


def ensure_user_columns(engine: Engine) -> None:
    """Ensure missing columns on the user table are added on existing SQLite databases."""
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as conn:
        rows = conn.exec_driver_sql("PRAGMA table_info(user)").fetchall()
        columns = {row[1] for row in rows}
        if rows and "password_hash" not in columns:
            conn.exec_driver_sql("ALTER TABLE user ADD COLUMN password_hash VARCHAR")
