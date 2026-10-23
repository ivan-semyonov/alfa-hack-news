"""Local workspace identities, revocable sessions and CSRF protection."""
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
import secrets
from threading import RLock
import time

from .storage import now


def password_hash(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 250_000).hex()
    return 'pbkdf2_sha256$250000$' + salt + '$' + digest


def verify_password(password, encoded):
    try:
        _, rounds, salt, expected = encoded.split('$')
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(rounds)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


class Access:
    def __init__(self, store, demo=True):
        self.store, self.demo = store, demo
        self.lock = RLock()
        self.attempts = defaultdict(deque)
        self.fake_hash = password_hash(secrets.token_hex(20))
        if demo:
            self.store.execute('INSERT INTO users(username,password_hash,tenant,role,created_at) VALUES(?,?,?,?,?) '
                               'ON CONFLICT(username) DO NOTHING', ('demo', password_hash('demo'), 'demo', 'READER', now()))
        configured = os.getenv('APP_ADMIN_PASSWORD')
        if configured:
            if len(configured) < 12:
                raise ValueError('APP_ADMIN_PASSWORD must contain at least 12 characters')
            self.ensure_admin(configured)

    def ensure_admin(self, password):
        with self.lock:
            self.store.execute('INSERT INTO users(username,password_hash,tenant,role,created_at) VALUES(?,?,?,?,?) '
                               'ON CONFLICT(username) DO NOTHING', ('admin', password_hash(password), 'workspace', 'ADMIN', now()))

    def setup_needed(self):
        return self.store.one('SELECT username FROM users WHERE username=?', ('admin',)) is None

    def setup(self, password):
        if len(password) < 12:
            raise ValueError('Используйте пароль длиной не менее 12 символов.')
        with self.lock:
            if not self.setup_needed():
                raise ValueError('Рабочее пространство уже настроено.')
            self.ensure_admin(password)

    def login(self, username, password, client='local'):
        with self.lock:
            attempts = self.attempts[client]
            current = time.monotonic()
            while attempts and attempts[0] < current - 600:
                attempts.popleft()
            if len(attempts) >= 30:
                raise PermissionError('Слишком много попыток входа. Повторите через 10 минут.')
            attempts.append(current)
        row = self.store.one('SELECT * FROM users WHERE username=?', (username,))
        valid = verify_password(password, row['password_hash'] if row else self.fake_hash)
        if not row or not valid:
            raise PermissionError('Неверный логин или пароль.')
        if username == 'demo' and not self.demo:
            raise PermissionError('Демонстрационный доступ выключен.')
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        expires = (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat()
        self.store.execute('INSERT INTO sessions(token_hash,username,tenant,role,csrf,expires_at) VALUES(?,?,?,?,?,?)',
                           (hashlib.sha256(token.encode()).hexdigest(), username, row['tenant'], row['role'], csrf, expires))
        return token, {'username': username, 'tenant': row['tenant'], 'role': row['role'], 'csrf': csrf, 'expires_at': expires}

    def principal(self, token):
        if not token or len(token) > 200:
            return None
        key = hashlib.sha256(token.encode()).hexdigest()
        row = self.store.one('SELECT * FROM sessions WHERE token_hash=?', (key,))
        if not row or row['expires_at'] <= now():
            return None
        if row['username'] == 'demo' and not self.demo:
            return None
        return {name: row[name] for name in ('username', 'tenant', 'role', 'csrf', 'expires_at')}

    def logout(self, token):
        if token:
            self.store.execute('DELETE FROM sessions WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),))
