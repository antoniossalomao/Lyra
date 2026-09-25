"""
routers/auth.py — setup inicial da conta admin, login e logout.

Implementa o "Cenário A" decidido em PLANEJAMENTO_LYRA2.0.md seção 4/5:
proteção de acesso por senha, single-user (1 conta admin), sem multi-tenant/
OAuth/LDAP. JWT em cookie httpOnly (não localStorage — evita XSS roubar o
token). Primeira tela do frontend consulta GET /auth/status: se
`setup_necessario` for true, mostra "criar conta admin" em vez de login.
"""
from fastapi import APIRouter, HTTPException, Response, status

from config import AUTH_COOKIE_NAME, AUTH_COOKIE_MAX_AGE_S
from models.auth import UserSetup, UserLogin
from utils.auth import PasswordHasher, UserRepository, JWTManager


class AuthRouter:
    def __init__(self, *, user_repo: UserRepository, jwt_manager: JWTManager):
        self._users = user_repo
        self._jwt = jwt_manager

        self.router = APIRouter(prefix="/auth", tags=["auth"])
        self.router.add_api_route("/status", self.auth_status, methods=["GET"])
        self.router.add_api_route("/setup", self.setup, methods=["POST"])
        self.router.add_api_route("/login", self.login, methods=["POST"])
        self.router.add_api_route("/logout", self.logout, methods=["POST"])

    async def auth_status(self):
        """Diz ao frontend se deve mostrar a tela de 'criar conta admin'
        (primeiro boot, nenhum usuário ainda) ou a tela de login normal."""
        total = await self._users.count()
        return {"setup_necessario": total == 0}

    async def setup(self, req: UserSetup, response: Response):
        """Cria a conta admin — só funciona se ainda não existir nenhum
        usuário, pra ninguém recriar/assumir a conta admin depois do primeiro
        boot (mesma proteção contra corrida do Open WebUI, ver plano §3.1)."""
        total = await self._users.count()
        if total > 0:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="Já existe uma conta configurada — use /auth/login.")
        if len(req.senha) < 8:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Senha precisa ter pelo menos 8 caracteres.")
        password_hash = PasswordHasher.hash(req.senha)
        await self._users.create(req.username, password_hash, role="admin")
        self._set_cookie(response, req.username)
        return {"ok": True, "username": req.username}

    async def login(self, req: UserLogin, response: Response):
        user = await self._users.get_by_username(req.username)
        if not user or not PasswordHasher.verify(req.senha, user.get("password_hash", "")):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário ou senha inválidos.")
        self._set_cookie(response, req.username)
        return {"ok": True, "username": req.username}

    async def logout(self, response: Response):
        response.delete_cookie(AUTH_COOKIE_NAME)
        return {"ok": True}

    def _set_cookie(self, response: Response, username: str):
        token = self._jwt.create_token(username)
        response.set_cookie(key=AUTH_COOKIE_NAME, value=token, httponly=True,
                            samesite="lax", max_age=AUTH_COOKIE_MAX_AGE_S)
