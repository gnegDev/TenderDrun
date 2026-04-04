"""
Загрузка данных из CSV-файлов в PostgreSQL.

Использование:
    python scripts/load_data.py --ste data/СТЕ_*.csv --contracts data/Контракты_*.csv

Переменная окружения DATABASE_URL переопределяет дефолтный адрес.
"""
import os
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import SQLModel, create_engine

# Добавляем backend в путь поиска модулей
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from models import Contract, SteItem  # noqa: E402

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/hackathon",
)

CHUNK_SIZE = 5_000

# Формат файла: разделитель ;, без строки заголовков, кавычки " для полей с ; внутри
CSV_OPTS = dict(
    sep=";",
    header=None,
    encoding="utf-8-sig",
    quotechar='"',
    on_bad_lines="skip",
    low_memory=False,
    dtype=str,
)

STE_COLS = ["ste_id", "name", "category", "attributes"]
# Для контрактов имена колонок уточняются после просмотра первой строки
CONTRACT_COLS_DEFAULT = [
    "purchase_name", "contract_id", "ste_id", "contract_date", "contract_sum",
    "inn", "customer_name", "customer_region",
    "supplier_inn", "supplier_name", "supplier_region",
]


def load_ste(path: str, engine) -> None:
    print(f"Загрузка СТЕ из {path}...")
    total = 0
    for chunk in pd.read_csv(path, chunksize=CHUNK_SIZE, names=STE_COLS, **CSV_OPTS):
        chunk = chunk.where(pd.notna(chunk), None)
        rows = []
        for _, row in chunk.iterrows():
            ste_id = row.get("ste_id")
            name = row.get("name")
            if not ste_id or not name:
                continue
            rows.append({
                "ste_id": str(ste_id),
                "name": str(name),
                "category": str(row["category"]) if row.get("category") else None,
                "attributes": str(row["attributes"]) if row.get("attributes") else None,
            })

        if rows:
            stmt = pg_insert(SteItem).values(rows)
            stmt = stmt.on_conflict_do_nothing(index_elements=["ste_id"])
            with engine.begin() as conn:
                conn.execute(stmt)

        total += len(rows)
        print(f"  загружено {total} записей...", end="\r")

    print(f"\nСТЕ: итого {total} записей.")


def load_contracts(path: str, engine) -> None:
    print(f"Загрузка контрактов из {path}...")

    # Определяем имена колонок по ширине первой строки
    first = pd.read_csv(path, nrows=1, header=None, sep=";",
                        encoding="utf-8-sig", quotechar='"', dtype=str)
    ncols = len(first.columns)
    col_names = CONTRACT_COLS_DEFAULT[:ncols] + [f"col_{i}" for i in range(ncols - len(CONTRACT_COLS_DEFAULT))]

    total = 0
    for chunk in pd.read_csv(path, chunksize=CHUNK_SIZE, names=col_names, **CSV_OPTS):
        chunk = chunk.where(pd.notna(chunk), None)
        rows = []
        for _, row in chunk.iterrows():
            contract_id = row.get("contract_id")
            ste_id = row.get("ste_id")
            inn = row.get("inn")
            if not contract_id or not ste_id or not inn:
                continue

            contract_sum_raw = row.get("contract_sum")
            try:
                contract_sum = float(str(contract_sum_raw).replace(",", ".")) if contract_sum_raw else None
            except ValueError:
                contract_sum = None

            contract_date_raw = row.get("contract_date")
            contract_date = pd.to_datetime(contract_date_raw, errors="coerce")
            contract_date = contract_date.to_pydatetime() if contract_date_raw and not pd.isna(contract_date) else None

            rows.append({
                "contract_id": str(contract_id),
                "ste_id": str(ste_id),
                "inn": str(inn),
                "customer_name": row.get("customer_name"),
                "supplier_inn": row.get("supplier_inn"),
                "supplier_name": row.get("supplier_name"),
                "purchase_name": row.get("purchase_name"),
                "contract_date": contract_date,
                "contract_sum": contract_sum,
            })

        if rows:
            with engine.begin() as conn:
                conn.execute(Contract.__table__.insert(), rows)

        total += len(rows)
        print(f"  загружено {total} записей...", end="\r")

    print(f"\nКонтракты: итого {total} записей.")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Загрузка данных в БД")
    parser.add_argument("--ste", help="Путь к CSV-файлу СТЕ")
    parser.add_argument("--contracts", help="Путь к CSV-файлу контрактов")
    args = parser.parse_args()

    if not args.ste and not args.contracts:
        parser.print_help()
        sys.exit(1)

    engine = create_engine(DATABASE_URL, echo=False)
    SQLModel.metadata.create_all(engine)

    if args.ste:
        load_ste(args.ste, engine)
    if args.contracts:
        load_contracts(args.contracts, engine)

    print("Готово.")


if __name__ == "__main__":
    main()
