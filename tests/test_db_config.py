"""PostgresStore connection settings and schema files, without a database."""
import re

import pytest

from app import db


@pytest.fixture(autouse=True)
def no_connect(monkeypatch):
    monkeypatch.setattr(db.PostgresStore, "init_db", lambda self: None)


def test_railway_private_url_uses_plain_tcp():
    s = db.PostgresStore("postgresql://postgres:p%40ss@postgres.railway.internal:5432/railway")
    p = s.params
    assert (p["host"], p["port"], p["database"], p["user"], p["password"]) == (
        "postgres.railway.internal", 5432, "railway", "postgres", "p@ss")
    assert p["ssl_context"] is None
    assert s.has_vector is False


def test_sslmode_require_enables_tls():
    s = db.PostgresStore("postgresql://u:pw@ep-x.neon.tech/app?sslmode=require")
    assert s.params["ssl_context"] is not None and s.params["port"] == 5432


def test_schema_files_split_vector_parts():
    core = db.PostgresStore._statements(db.INIT_SQL)
    vector = db.PostgresStore._statements(db.VECTOR_SQL)
    assert not any(re.search(r"\bvector\b", s, re.IGNORECASE) for s in core)  # tsvector is fine
    assert not any(s.startswith("--") for s in core + vector)
    assert any("VECTOR(" in s for s in vector) and "{EMBED_DIM}" not in " ".join(vector)
