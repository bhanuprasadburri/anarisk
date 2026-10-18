"""Quick DB inventory: list tables and row counts in the dev 'nimbus' database."""
from sqlalchemy import create_engine, text

engine = create_engine(
    "postgresql+psycopg://nimbus:nimbus_dev_pw@127.0.0.1:5432/nimbus"
)
with engine.connect() as conn:
    tables = [
        r[0]
        for r in conn.execute(
            text("select tablename from pg_tables where schemaname='public' order by 1")
        )
    ]
    print(f"{len(tables)} tables")
    for t in tables:
        count = conn.execute(text(f"select count(*) from {t}")).scalar()
        print(f"  {t}: {count}")
