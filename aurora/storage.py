"""Persistência das regras do condomínio; os arquivos em dados/ são somente leitura."""
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "dados"
DB = Path(os.getenv("AURORA_DB", ROOT / ".runtime" / "condominio.sqlite3"))


@contextmanager
def connection():
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 30000")
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def initialize():
    with connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS apartamentos (numero TEXT PRIMARY KEY, morador TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS areas (id TEXT PRIMARY KEY, nome TEXT NOT NULL, taxa REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS reservas (
            codigo TEXT PRIMARY KEY, apartamento TEXT NOT NULL REFERENCES apartamentos(numero),
            area TEXT NOT NULL REFERENCES areas(id), data TEXT NOT NULL, ativa INTEGER NOT NULL DEFAULT 1
        );
        CREATE UNIQUE INDEX IF NOT EXISTS reserva_ativa_unica ON reservas(area, data) WHERE ativa = 1;
        CREATE TABLE IF NOT EXISTS visitantes (
            id INTEGER PRIMARY KEY, apartamento TEXT NOT NULL REFERENCES apartamentos(numero),
            nome TEXT NOT NULL, data TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessoes (id TEXT PRIMARY KEY, apartamento TEXT NOT NULL REFERENCES apartamentos(numero));
        CREATE TABLE IF NOT EXISTS efeitos (id TEXT PRIMARY KEY, resultado TEXT NOT NULL);
        """)
        if not db.execute("SELECT 1 FROM apartamentos LIMIT 1").fetchone():
            for row in _read("apartamentos.json"):
                db.execute("INSERT INTO apartamentos VALUES (?, ?)", (row['numero'], row['morador']))
            for row in _read("areas.json"):
                db.execute("INSERT INTO areas VALUES (?, ?, ?)", (row['id'], row['nome'], row['taxa']))
            _restore(db)


def _read(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _restore(db):
    for row in _read("reservas.json"):
        db.execute("INSERT INTO reservas (codigo, apartamento, area, data) VALUES (?, ?, ?, ?)",
                   (row['codigo'], row['apartamento'], row['area'], row['data']))
    for row in _read("visitantes.json"):
        db.execute("INSERT INTO visitantes (apartamento, nome, data) VALUES (?, ?, ?)",
                   (row['apartamento'], row['nome'], row['data']))


def restore():
    initialize()
    with connection() as db:
        db.execute("DELETE FROM reservas")
        db.execute("DELETE FROM visitantes")
        db.execute("DELETE FROM efeitos")
        db.execute("DELETE FROM sessoes")
        _restore(db)


def create_session(session_id, apartamento):
    with connection() as db:
        db.execute("INSERT INTO sessoes VALUES (?, ?)", (session_id, apartamento))


def apartment_for(session_id):
    with connection() as db:
        row = db.execute("SELECT apartamento FROM sessoes WHERE id = ?", (session_id,)).fetchone()
        return row['apartamento'] if row else None


def areas():
    with connection() as db:
        return [dict(row) for row in db.execute("SELECT id, nome, taxa FROM areas ORDER BY id")]


def _date(value):
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError("Data deve estar no formato AAAA-MM-DD")
    return value


def list_reservations(apartment):
    with connection() as db:
        return [dict(row) for row in db.execute("SELECT codigo, area, data FROM reservas WHERE apartamento = ? AND ativa = 1 ORDER BY data, codigo", (apartment,))]


def list_visitors(apartment):
    with connection() as db:
        return [dict(row) for row in db.execute("SELECT nome, data FROM visitantes WHERE apartamento = ? ORDER BY data, id", (apartment,))]


def availability(area, day):
    _date(day)
    with connection() as db:
        if not db.execute("SELECT 1 FROM areas WHERE id = ?", (area,)).fetchone():
            return {"status": "area_invalida"}
        occupied = db.execute("SELECT 1 FROM reservas WHERE area = ? AND data = ? AND ativa = 1", (area, day)).fetchone()
        return {"status": "ocupada" if occupied else "livre"}


def cancel(apartment, area, day):
    _date(day)
    with connection() as db:
        cur = db.execute("UPDATE reservas SET ativa = 0 WHERE apartamento = ? AND area = ? AND data = ? AND ativa = 1", (apartment, area, day))
        return {"status": "cancelada" if cur.rowcount else "nao_encontrada"}


def _effect(db, effect_id):
    if effect_id:
        row = db.execute("SELECT resultado FROM efeitos WHERE id = ?", (effect_id,)).fetchone()
        if row:
            return json.loads(row['resultado'])
    return None


def _save_effect(db, effect_id, result):
    if effect_id:
        db.execute("INSERT INTO efeitos VALUES (?, ?)", (effect_id, json.dumps(result)))
    return result


def reserve(apartment, area, day, effect_id=None):
    _date(day)
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        previous = _effect(db, effect_id)
        if previous is not None:
            return previous
        if not db.execute("SELECT 1 FROM areas WHERE id = ?", (area,)).fetchone():
            return _save_effect(db, effect_id, {"status": "area_invalida"})
        if db.execute("SELECT 1 FROM reservas WHERE area = ? AND data = ? AND ativa = 1", (area, day)).fetchone():
            return _save_effect(db, effect_id, {"status": "ocupada"})
        while True:
            code = "RSV-" + uuid.uuid4().hex.upper()
            try:
                db.execute("INSERT INTO reservas (codigo, apartamento, area, data) VALUES (?, ?, ?, ?)", (code, apartment, area, day))
                break
            except sqlite3.IntegrityError:
                if db.execute("SELECT 1 FROM reservas WHERE codigo = ?", (code,)).fetchone():
                    continue
                raise
        return _save_effect(db, effect_id, {"status": "reservada", "codigo": code, "area": area, "data": day})


def authorize_visitor(apartment, name, day, effect_id):
    _date(day)
    name = name.strip()
    if not name:
        raise ValueError("Nome é obrigatório")
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        previous = _effect(db, effect_id)
        if previous is not None:
            return previous
        db.execute("INSERT INTO visitantes (apartamento, nome, data) VALUES (?, ?, ?)", (apartment, name, day))
        return _save_effect(db, effect_id, {"status": "autorizado", "nome": name, "data": day})


if __name__ == '__main__':
    sessions_db = Path(os.getenv('AURORA_SESSION_DB', ROOT / '.runtime' / 'sessoes.sqlite3'))
    if sessions_db.resolve() == DB.resolve():
        raise SystemExit('Os bancos de sessões e do condomínio precisam ser arquivos diferentes.')
    restore()
    for path in (sessions_db, Path(str(sessions_db) + '-wal'), Path(str(sessions_db) + '-shm')):
        path.unlink(missing_ok=True)
    print('Reservas e visitantes restaurados; sessões apagadas.')
