"""
utils/auth.py — hash de senha, JWT e a dependency `get_current_user`.

Implementa o subset mínimo decidido em LYRA_NUCLEO.md §5.2
(inspirado no Open WebUI): 1 tabela `users`, JWT em cookie httpOnly, sem
LDAP/OAuth/SCIM/revogação via Redis. Cada classe tem uma responsabilidade só
— hash, token, leitura da tabela, dependency FastAPI — pra qualquer
programador entender o fluxo de auth sem precisar ler tudo de uma vez.

Hashing usa PBKDF2-SHA256 (hashlib da stdlib) em vez de bcrypt/argon2: o
projeto não tinha bcrypt instalado e app é single-user local, não precisa da
resistência extra de um KDF de memória — 260k iterações de PBKDF2 já é o
recomendado atual da OWASP pra PBKDF2-SHA256.
"""
import datetime
import hashlib
import hmac
import json
import os

import jwt
from fastapi import Cookie, HTTPException, status

from config import AUTH_COOKIE_NAME

_PBKDF2_ITERATIONS = 260_000
_JWT_ALGORITHM = "HS256"


class PasswordHasher:
    """Hash e verificação de senha via PBKDF2-SHA256 com salt aleatório por senha."""

    @staticmethod
    def hash(senha: str) -> str:
        salt = os.urandom(16)
        digest = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
        return f"{salt.hex()}${digest.hex()}"

    @staticmethod
    def verify(senha: str, hash_armazenado: str) -> bool:
        try:
            salt_hex, digest_hex = hash_armazenado.split("$", 1)
            salt = bytes.fromhex(salt_hex)
            digest_esperado = bytes.fromhex(digest_hex)
        except (ValueError, AttributeError):
            return False
        digest_calculado = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
        return hmac.compare_digest(digest_calculado, digest_esperado)


class JWTManager:
    """Emite e valida o token que vira o valor do cookie httpOnly de sessão."""

    def __init__(self, secret: str, expire_days: int = 30):
        self._secret = secret
        self._expire_days = expire_days

    def create_token(self, username: str) -> str:
        agora = datetime.datetime.now(datetime.timezone.utc)
        payload = {"sub": username, "iat": agora,
                   "exp": agora + datetime.timedelta(days=self._expire_days)}
        return jwt.encode(payload, self._secret, algorithm=_JWT_ALGORITHM)

    def decode_token(self, token: str) -> str | None:
        """Retorna o username do token, ou None se inválido/expirado."""
        try:
            payload = jwt.decode(token, self._secret, algorithms=[_JWT_ALGORITHM])
            return payload.get("sub")
        except jwt.PyJWTError:
            return None


class UserRepository:
    """Acesso à tabela `users` no SurrealDB — única tabela nova da Fase 2."""

    def __init__(self, surreal):
        self._surreal = surreal

    async def count(self) -> int:
        # Bug real de primeiro boot: SurrealDB (modo estrito desta instância)
        # devolve status ERR com `result` = string de erro quando a tabela
        # `users` nunca foi criada (nenhum CREATE ainda) — SurrealClient.result()
        # não distingue OK de ERR, só desembrulha `result`, então aqui vira uma
        # string em vez da lista esperada. Achado testando /auth/status de
        # verdade contra o backend real, não em teste isolado. "Tabela não
        # existe" == "nenhum usuário ainda" == count 0, semanticamente correto.
        dados = await self._surreal.query_result("SELECT count() FROM users GROUP ALL;")
        if not dados or not isinstance(dados[0], dict):
            return 0
        return dados[0].get("count", 0)

    async def get_by_username(self, username: str) -> dict | None:
        dados = await self._surreal.query_result(
            f"SELECT * FROM users WHERE username = {json.dumps(username)} LIMIT 1;")
        if not dados or not isinstance(dados[0], dict):
            return None
        return dados[0]

    async def create(self, username: str, password_hash: str, role: str = "admin") -> dict:
        criado_em = datetime.datetime.now(datetime.timezone.utc).isoformat()
        campos = (f"username = {json.dumps(username)}, "
                  f"password_hash = {json.dumps(password_hash)}, "
                  f"role = {json.dumps(role)}, "
                  f"created_at = {json.dumps(criado_em)}")
        dados = await self._surreal.query_result(f"CREATE users SET {campos};")
        return dados[0] if dados else {}


class CurrentUserDependency:
    """Usado como `Depends(dep)` em qualquer rota que precisa estar logada.
    Lê o cookie httpOnly (nome fixo — só existe 1 dependency de auth no app,
    não há caso real de precisar de dois nomes de cookie diferentes),
    valida o JWT, devolve o username — ou levanta 401."""

    def __init__(self, jwt_manager: JWTManager):
        self._jwt = jwt_manager

    def __call__(self, session_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME)):
        if session_token is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Não autenticado.")
        username = self._jwt.decode_token(session_token)
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessão inválida ou expirada.")
        return username
