import os
from typing import Generator

from sqlmodel import Session, SQLModel, create_engine

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@db:5432/hackathon",
)

engine = create_engine(DATABASE_URL, echo=False)


def get_db() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


def init_db() -> None:
    # models must be imported before this call so metadata is populated
    SQLModel.metadata.create_all(engine)
