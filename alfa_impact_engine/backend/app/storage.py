"""Tenant-scoped durable repositories, SQLite locally and PostgreSQL by DSN."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from threading import RLock
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier(prefix):
    return prefix + ':' + uuid4().hex


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


SCHEMA = '''
CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY,password_hash TEXT NOT NULL,tenant TEXT NOT NULL,role TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,username TEXT NOT NULL,tenant TEXT NOT NULL,role TEXT NOT NULL,csrf TEXT NOT NULL,expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS companies(tenant TEXT NOT NULL,id TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(tenant,id));
CREATE TABLE IF NOT EXISTS payments(tenant TEXT NOT NULL,id TEXT NOT NULL,payer TEXT NOT NULL,beneficiary TEXT NOT NULL,amount TEXT NOT NULL,pay_count INTEGER NOT NULL,source_id TEXT NOT NULL,period TEXT,PRIMARY KEY(tenant,id));
CREATE TABLE IF NOT EXISTS documents(tenant TEXT NOT NULL,id TEXT NOT NULL,content_hash TEXT NOT NULL,title TEXT NOT NULL,kind TEXT NOT NULL,published_at TEXT,is_synthetic INTEGER NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(tenant,id),UNIQUE(tenant,content_hash));
CREATE TABLE IF NOT EXISTS chunks(tenant TEXT NOT NULL,id TEXT NOT NULL,document_id TEXT NOT NULL,page INTEGER NOT NULL,text TEXT NOT NULL,PRIMARY KEY(tenant,id));
CREATE TABLE IF NOT EXISTS news(tenant TEXT NOT NULL,id TEXT NOT NULL,content_hash TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(tenant,id),UNIQUE(tenant,content_hash));
CREATE TABLE IF NOT EXISTS runs(tenant TEXT NOT NULL,id TEXT NOT NULL,company_id TEXT NOT NULL,news_id TEXT NOT NULL,status TEXT NOT NULL,mode TEXT NOT NULL,relevance INTEGER NOT NULL,created_at TEXT NOT NULL,completed_at TEXT,payload TEXT NOT NULL,PRIMARY KEY(tenant,id));
CREATE TABLE IF NOT EXISTS steps(tenant TEXT NOT NULL,run_id TEXT NOT NULL,ordinal INTEGER NOT NULL,tool TEXT NOT NULL,status TEXT NOT NULL,duration_ms TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(tenant,run_id,ordinal));
CREATE TABLE IF NOT EXISTS records(tenant TEXT NOT NULL,kind TEXT NOT NULL,id TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(tenant,kind,id));
CREATE INDEX IF NOT EXISTS runs_feed ON runs(tenant,company_id,relevance,created_at);
CREATE INDEX IF NOT EXISTS chunks_document ON chunks(tenant,document_id,page);
CREATE INDEX IF NOT EXISTS payments_payer ON payments(tenant,payer);
CREATE INDEX IF NOT EXISTS payments_beneficiary ON payments(tenant,beneficiary);
'''


class Store:
    def __init__(self, target):
        self.lock = RLock()
        self.postgres = str(target).startswith(('postgresql://', 'postgres://'))
        if self.postgres:
            import psycopg
            from psycopg.rows import dict_row
            self.connection = psycopg.connect(target, row_factory=dict_row, connect_timeout=10)
        else:
            if str(target) != ':memory:':
                Path(target).parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(str(target), check_same_thread=False, timeout=15)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute('PRAGMA foreign_keys=ON')
            self.connection.execute('PRAGMA journal_mode=WAL')
        with self.transaction() as db:
            for statement in SCHEMA.split(';'):
                if statement.strip():
                    db.execute(statement)

    def sql(self, query):
        return query.replace('?', '%s') if self.postgres else query

    @contextmanager
    def transaction(self):
        with self.lock:
            cursor = self.connection.cursor()
            outer = self

            class Executor:
                def execute(self, query, params=()):
                    return cursor.execute(outer.sql(query), params)

                def fetchone(self):
                    row = cursor.fetchone()
                    return dict(row) if row is not None else None

                def fetchall(self):
                    return [dict(row) for row in cursor.fetchall()]

            try:
                yield Executor()
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
            finally:
                cursor.close()

    def one(self, query, params=()):
        with self.transaction() as db:
            db.execute(query, params)
            return db.fetchone()

    def all(self, query, params=()):
        with self.transaction() as db:
            db.execute(query, params)
            return db.fetchall()

    def execute(self, query, params=()):
        with self.transaction() as db:
            db.execute(query, params)

    def put_record(self, tenant, kind, key, payload):
        self.execute('INSERT INTO records(tenant,kind,id,payload,created_at) VALUES(?,?,?,?,?) '
                     'ON CONFLICT(tenant,kind,id) DO UPDATE SET payload=excluded.payload',
                     (tenant, kind, key, encode(payload), now()))

    def record(self, tenant, kind, key):
        row = self.one('SELECT payload FROM records WHERE tenant=? AND kind=? AND id=?', (tenant, kind, key))
        return json.loads(row['payload']) if row else None

    def records(self, tenant, kind, limit=200):
        return [json.loads(row['payload']) for row in self.all(
            'SELECT payload FROM records WHERE tenant=? AND kind=? ORDER BY created_at DESC LIMIT ?', (tenant, kind, limit))]

    def company(self, tenant, key):
        row = self.one('SELECT payload FROM companies WHERE tenant=? AND id=?', (tenant, key))
        return json.loads(row['payload']) if row else None

    def companies(self, tenant):
        return [json.loads(row['payload']) for row in self.all(
            'SELECT payload FROM companies WHERE tenant=? ORDER BY id LIMIT 10000', (tenant,))]

    def put_company(self, tenant, company):
        self.execute('INSERT INTO companies(tenant,id,payload,created_at) VALUES(?,?,?,?) '
                     'ON CONFLICT(tenant,id) DO UPDATE SET payload=excluded.payload',
                     (tenant, company['id'], encode(company), now()))

    def run(self, tenant, key):
        row = self.one('SELECT payload FROM runs WHERE tenant=? AND id=?', (tenant, key))
        return json.loads(row['payload']) if row else None

    def put_run(self, tenant, run):
        self.execute('INSERT INTO runs(tenant,id,company_id,news_id,status,mode,relevance,created_at,completed_at,payload) '
                     'VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(tenant,id) DO UPDATE SET '
                     'status=excluded.status,relevance=excluded.relevance,completed_at=excluded.completed_at,payload=excluded.payload',
                     (tenant, run['id'], run['company_id'], run['news_id'], run['status'], run['mode'],
                      run.get('ranking', {}).get('score', 0), run['created_at'], run.get('completed_at'), encode(run)))

    def close(self):
        with self.lock:
            self.connection.close()
