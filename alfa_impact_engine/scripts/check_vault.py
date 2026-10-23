"""Check local secret protection without printing any key or encrypted payload."""
from pathlib import Path
import secrets
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.provider_settings import Vault

if __name__ == '__main__':
    vault = Vault(Path(__file__).resolve().parents[1] / '.runtime')
    value = secrets.token_urlsafe(24)
    sealed = vault.seal(value)
    assert value != sealed and Vault(vault.directory).open(sealed) == value
    print('Local encryption and reopen: OK (no secrets printed)')
