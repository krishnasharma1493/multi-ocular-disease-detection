from sqlalchemy.engine import Engine


def ensure_screening_columns(engine: Engine) -> None:
    """Add columns that older SQLite databases lack (there are no migrations); existing rows become 'unknown'."""
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as conn:
        rows = conn.exec_driver_sql("PRAGMA table_info(screening)").fetchall()
        columns = {row[1] for row in rows}
        if rows and "image_source" not in columns:
            conn.exec_driver_sql("ALTER TABLE screening ADD COLUMN image_source VARCHAR NOT NULL DEFAULT 'unknown'")
