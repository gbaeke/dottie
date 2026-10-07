"""A user's secrets: encrypted at rest, written but never read back through the API, filled into a connection only
inside the app (the sandbox never sees them).

Values are encrypted with a key from SECRETS_KEY. The cipher class is the only thing that knows that: replacing it by a
key held in Azure Key Vault (wrapping a data key) changes this file and nothing else. A stored value starts with the
format version (`v1:`) so a later format can be told apart.
"""

import base64
import hashlib
import logging
import re
from collections.abc import Callable

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..models import Dottie, Secret

log = logging.getLogger(__name__)

NAME_PATTERN = r"[a-zA-Z][a-zA-Z0-9_-]{0,39}"
REF = re.compile(r"\{\{\s*secret:(" + NAME_PATTERN + r")\s*\}\}")
VERSION = "v1"


class SecretsNotConfigured(Exception):
    """SECRETS_KEY is not set, so nothing can be stored or read."""


class SecretCipher:
    def __init__(self, key: str):
        # any string works as the key: it is hashed into the 32 bytes the cipher wants
        self._fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))

    def encrypt(self, value: str) -> str:
        return f"{VERSION}:{self._fernet.encrypt(value.encode()).decode()}"

    def decrypt(self, stored: str) -> str:
        version, _, token = stored.partition(":")
        if version != VERSION:
            raise ValueError(f"Unknown secret format {version!r}")
        return self._fernet.decrypt(token.encode()).decode()


def refs(text: str) -> set[str]:
    """The secret names a template refers to: `Bearer {{secret:tavily}}` -> {"tavily"}."""
    return set(REF.findall(text))


def fill(text: str, values: dict[str, str]) -> str:
    return REF.sub(lambda m: values[m.group(1)], text)


def hint_of(value: str) -> str:
    """Enough to tell two keys apart, and nothing for a short value."""
    return value[-4:] if len(value) >= 16 else ""


class SecretStore:
    def __init__(self, sessions: sessionmaker[Session], cipher: SecretCipher | None):
        self.sessions, self.cipher = sessions, cipher

    @property
    def configured(self) -> bool:
        return self.cipher is not None

    def _cipher(self) -> SecretCipher:
        if self.cipher is None:
            raise SecretsNotConfigured("SECRETS_KEY is not set")
        return self.cipher

    def put(self, owner_id: str, name: str, value: str) -> None:
        encrypted = self._cipher().encrypt(value)
        with self.sessions() as s:
            row = s.scalar(select(Secret).where(Secret.owner_id == owner_id, Secret.name == name))
            if row is None:
                s.add(Secret(owner_id=owner_id, name=name, ciphertext=encrypted, hint=hint_of(value)))
            else:
                row.ciphertext, row.hint = encrypted, hint_of(value)
            s.commit()

    def get_many(self, owner_id: str, names: set[str]) -> dict[str, str]:
        """The values of these secrets (the ones that exist), decrypted. Only for filling in a connection."""
        if not names:
            return {}
        with self.sessions() as s:
            rows = s.scalars(select(Secret).where(Secret.owner_id == owner_id, Secret.name.in_(names))).all()
            try:
                return {r.name: self._cipher().decrypt(r.ciphertext) for r in rows}
            except InvalidToken as e:
                raise ValueError("A secret cannot be read: SECRETS_KEY has changed since it was stored.") from e

    def names(self, owner_id: str) -> set[str]:
        with self.sessions() as s:
            return set(s.scalars(select(Secret.name).where(Secret.owner_id == owner_id)))


def repair_inline_credentials(
    sessions: sessionmaker[Session], store: SecretStore, looks_secret: Callable[[str], bool]
) -> int:
    """MCP server URLs saved before secrets existed may carry a key in the query (`?tavilyApiKey=...`). Move each such
    value into the owner's secret store and leave a reference, so no credential stays in a URL. Safe to run on every
    start: once moved, there is nothing left to move. Returns how many credentials were moved."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    moved = 0
    with sessions() as s:
        for dottie in s.scalars(select(Dottie)):
            servers, changed = [dict(x) for x in dottie.mcp_servers], False
            for server in servers:
                parts = urlsplit(server.get("url", ""))
                keep, query = [], dict(server.get("query") or {})
                for param, value in parse_qsl(parts.query, keep_blank_values=True):
                    if looks_secret(param) and value and not refs(value):
                        secret = re.sub(r"[^a-zA-Z0-9_-]", "-", f"{server.get('name', 'mcp')}-{param}")[:40]
                        store.put(dottie.owner_id, secret, value)
                        query[param] = "{{secret:" + secret + "}}"
                        moved, changed = moved + 1, True
                    else:
                        keep.append((param, value))
                if changed:
                    server["url"] = urlunsplit(parts._replace(query=urlencode(keep)))
                    server["query"] = query
            if changed:
                dottie.mcp_servers = servers
        s.commit()
    if moved:
        log.info("moved %s credential(s) from MCP server URLs into the secret store", moved)
    return moved
