import os
import sqlalchemy as db
from sqlalchemy import text

class DatabaseService:
    def __init__(self):
        url_object = db.URL.create(
            drivername="postgresql+psycopg2",
            username=os.environ.get("FLOWVISION_DB_USERNAME", "postgres"),
            password=os.environ.get("FLOWVISION_DB_PASSWORD", "postgres"),
            host=os.environ.get("FLOWVISION_DB_HOST", "localhost"),
            port=int(os.environ.get("FLOWVISION_DB_PORT", 5432)),
            database=os.environ.get("FLOWVISION_DB_NAME", "flowvision"),
        )
        self.engine = db.create_engine(url_object, pool_pre_ping=True)

    def upsert(self, sql, params):
        # engine.begin() commits on success, rolls back on error and always releases the connection
        with self.engine.begin() as conn:
            conn.execute(statement=text(sql), parameters=params)
