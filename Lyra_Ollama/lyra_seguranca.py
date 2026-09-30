"""
lyra_seguranca.py — Módulo central de segurança da Lyra
- Audit log imutável (append-only no SurrealDB)
- Rate limiter por ferramenta
- Gestão de chaves via Windows Credential Manager (keyring)
"""

import json
import time
import threading
import hashlib
import os
import re
from collections import defaultdict, deque
from datetime import datetime

import requests

from surreal_client import surreal

# Ferramentas perigosas e seus limites (chamadas por janela de tempo)
_RATE_LIMITS: dict[str, tuple[int, int]] = {
    # ferramenta: (max_chamadas, janela_segundos)
    "executar_comando":      (20, 300),   # 20 cmd por 5min
    "iniciar_processo_bg":   (5,  300),   # 5 por 5min
    "escrever_arquivo":      (30, 60),    # 30 por minuto
    "organizar_pasta":       (3,  300),   # 3 por 5min
    "criar_ferramenta":      (5,  600),   # 5 por 10min
    "consultar_especialista":(3,  600),   # 3 por 10min
    "navegar_web":           (10, 300),   # 10 por 5min
}

# ── Rate Limiter (in-memory, thread-safe) ─────────────────────────────────────

_janelas: dict[str, deque] = defaultdict(deque)
_lock_rate = threading.Lock()


def checar_rate_limit(nome_tool: str) -> tuple[bool, str]:
    """
    Retorna (permitido, mensagem).
    Chamado antes de executar qualquer tool listada em _RATE_LIMITS.
    """
    if nome_tool not in _RATE_LIMITS:
        return True, ""

    max_calls, janela_s = _RATE_LIMITS[nome_tool]
    agora = time.monotonic()

    with _lock_rate:
        fila = _janelas[nome_tool]
        # Remove timestamps fora da janela
        while fila and agora - fila[0] > janela_s:
            fila.popleft()

        if len(fila) >= max_calls:
            espera = int(janela_s - (agora - fila[0]))
            return False, (
                f"Rate limit: '{nome_tool}' atingiu {max_calls} chamadas "
                f"em {janela_s}s. Aguarde ~{espera}s."
            )

        fila.append(agora)
        return True, ""


def resetar_rate_limit(nome_tool: str) -> None:
    """Uso administrativo — limpa a janela de uma tool específica."""
    with _lock_rate:
        _janelas.pop(nome_tool, None)


# ── Câmara de Eco Heurística (avaliação de risco pré-execução) ──────────────
# Item do roadmap (LYRA_TECNICO.md §3.4), implementado 02/07/2026. V1 é heurística
# por padrões (regex/substring), sem chamada de LLM — mesmo estilo já usado em
# criar_ferramenta() (varredura de padrões de risco) e no roteador de intenção
# (_TOOL_KEYWORDS_RE). NÃO expor essas funções em TOOLS_MAP/TOOLS_SCHEMA — é
# infraestrutura de segurança transparente, mesmo padrão de aprovar_ferramenta_ext.

_DIRS_TRABALHO_SEGUROS = [
    r"c:\lyra_project",
    os.path.expanduser("~\\documents").lower(),
    os.path.expanduser("~\\downloads").lower(),
    os.path.expanduser("~\\desktop").lower(),
]
_DIRS_SISTEMA = [r"c:\windows", r"c:\program files"]
_EXTENSOES_SENSIVEIS = {".exe", ".dll", ".ps1", ".bat", ".cmd", ".msi", ".sys", ".reg", ".vbs"}


def _risco_comando(cmd: str) -> str | None:
    """Padrões de comando perigoso (PowerShell). Retorna motivo ou None (baixo risco)."""
    c = cmd.lower()

    if "rm -rf" in c or ("remove-item" in c and "-recurse" in c and "-force" in c) \
            or "del /s /q" in c or "rd /s /q" in c:
        return "Deleção em massa/recursiva detectada."
    if re.search(r"\bformat\s+[a-z]:", c) or "diskpart" in c:
        return "Formatação/particionamento de disco detectado."
    if "reg delete" in c or ("remove-item" in c and ("hklm:" in c or "hkcu:" in c)):
        return "Remoção de chave de registro do Windows detectada."
    if re.search(r"\bshutdown\b", c) or "stop-computer" in c or "restart-computer" in c \
            or ("net user" in c and "/delete" in c):
        return "Desligamento/reinício do sistema ou remoção de usuário detectado."
    if ("stop-process" in c and "-force" in c) or ("taskkill" in c and "/f" in c):
        return "Encerramento forçado de processo detectado."
    if ("iex" in c or "invoke-expression" in c) and \
            ("invoke-webrequest" in c or "iwr" in c or "curl" in c or "wget" in c):
        return "Padrão de download+execução de código detectado (iex/Invoke-Expression + download)."
    if any(d in c for d in _DIRS_SISTEMA) and \
            any(v in c for v in ["remove-item", " del ", " rd ", "format"]):
        return "Comando destrutivo mirando diretório de sistema (Windows/Program Files)."
    return None


def _risco_escrever_arquivo(path: str, modo: str) -> str | None:
    """Sobrescrita comum de arquivo de trabalho (.py/.md/.json/.txt) NÃO é risco —
    só extensão sensível ou fora dos diretórios de trabalho conhecidos."""
    caminho_abs = os.path.abspath(path).lower()
    _, ext = os.path.splitext(caminho_abs)

    if any(caminho_abs.startswith(d) for d in _DIRS_SISTEMA):
        return "Escrita em diretório de sistema (Windows/Program Files)."
    if ext in _EXTENSOES_SENSIVEIS:
        return f"Escrita de arquivo com extensão sensível ({ext})."
    if not any(caminho_abs.startswith(d) for d in _DIRS_TRABALHO_SEGUROS):
        return "Escrita fora dos diretórios de trabalho conhecidos (Lyra_Project/Documents/Downloads/Desktop)."
    return None


def _risco_organizar_pasta(path: str) -> str | None:
    caminho_abs = os.path.abspath(path).lower()
    if re.match(r"^[a-z]:\\?$", caminho_abs):
        return "Alvo é a raiz de um drive inteiro."
    if any(d in caminho_abs for d in _DIRS_SISTEMA) or caminho_abs.rstrip("\\") == r"c:\users":
        return "Alvo é um diretório crítico do sistema."
    return None


def avaliar_risco_acao(nome_tool: str, args: dict) -> dict:
    """Avalia heuristicamente se uma chamada de ferramenta é de alto risco
    ANTES de executar. Retorna {"risco": "alto"|"baixo", "motivo": str|None}."""
    motivo = None
    try:
        if nome_tool in ("executar_comando", "iniciar_processo_bg"):
            cmd = args.get("cmd") or args.get("comando") or ""
            motivo = _risco_comando(cmd)
        elif nome_tool == "escrever_arquivo":
            motivo = _risco_escrever_arquivo(args.get("path", ""), args.get("modo", "w"))
        elif nome_tool == "organizar_pasta":
            motivo = _risco_organizar_pasta(args.get("path", ""))
    except Exception:
        motivo = None  # nunca deixa a avaliação de risco quebrar a execução normal

    return {"risco": "alto" if motivo else "baixo", "motivo": motivo}


def hash_acao(nome_tool: str, args: dict) -> str:
    """Hash determinístico de (nome_tool, args) — usado para ligar uma
    confirmação explícita do usuário à ação exata que foi bloqueada."""
    payload = json.dumps({"nome": nome_tool, "args": args}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ── Audit Log (SurrealDB append-only) ────────────────────────────────────────

_audit_lock = threading.Lock()
_audit_buffer: list[dict] = []
_AUDIT_FLUSH_INTERVAL_S = 5
_audit_thread_started = False


def _flush_audit_buffer() -> None:
    """Worker thread: descarrega o buffer de audit para o SurrealDB a cada 5s."""
    global _audit_buffer
    while True:
        time.sleep(_AUDIT_FLUSH_INTERVAL_S)
        with _audit_lock:
            if not _audit_buffer:
                continue
            batch = _audit_buffer[:]
            _audit_buffer = []

        for entrada in batch:
            try:
                query = f"CREATE audit_log CONTENT {json.dumps(entrada, ensure_ascii=False)}"
                surreal.query_sync(query, timeout=5)
            except Exception:
                pass  # nunca deixar o audit travar a aplicação


def _garantir_thread_audit() -> None:
    global _audit_thread_started
    if not _audit_thread_started:
        t = threading.Thread(target=_flush_audit_buffer, daemon=True, name="lyra-audit-flush")
        t.start()
        _audit_thread_started = True


def registrar_audit(
    tool: str,
    args: dict,
    resultado: str,
    solicitante: str = "llm",
    bloqueado: bool = False,
    motivo_bloqueio: str = "",
) -> None:
    """
    Registra uma chamada de tool no audit log imutável.
    Não bloqueia — usa buffer + thread de flush.
    """
    _garantir_thread_audit()
    entrada = {
        "timestamp":       datetime.now().isoformat(),
        "tool":            tool,
        "args_resumo":     json.dumps(args, ensure_ascii=False)[:500],
        "resultado_resumo": resultado[:500] if resultado else "",
        "solicitante":     solicitante,
        "bloqueado":       bloqueado,
        "motivo_bloqueio": motivo_bloqueio,
    }
    with _audit_lock:
        _audit_buffer.append(entrada)


# ── Leitura do audit log ──────────────────────────────────────────────────────

def consultar_audit(limite: int = 50, tool_filtro: str = "", apenas_bloqueados: bool = False) -> dict:
    """
    Consulta o audit log no SurrealDB.
    Exposto via lyra_tools para o LLM (e para o usuário) poder consultar.
    """
    try:
        where_clauses = []
        if tool_filtro:
            # Tool names are always [a-z0-9_] — reject anything else instead of
            # interpolating a raw string into SurrealQL (injection vector).
            if not re.fullmatch(r"[a-zA-Z0-9_]+", tool_filtro):
                return {"ok": False, "erro": f"tool_filtro inválido: {tool_filtro!r}"}
            where_clauses.append(f"tool = '{tool_filtro}'")
        if apenas_bloqueados:
            where_clauses.append("bloqueado = true")

        where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        query = f"SELECT * FROM audit_log {where} ORDER BY timestamp DESC LIMIT {limite}"

        registros = surreal.query_sync(query, timeout=10)
        if not isinstance(registros, list):
            registros = []
        return {"ok": True, "total": len(registros), "registros": registros}
    except Exception as e:
        return {"ok": False, "erro": str(e)}


# ── Windows Credential Manager (keyring) ─────────────────────────────────────

_KEYRING_SERVICE = "Lyra"
_CHAVES_CONHECIDAS = ["GROQ_API_KEY", "GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "ANTHROPIC_API_KEY"]


def migrar_chaves_para_keyring() -> dict:
    """
    Lê as API keys do .env atual e as move para o Windows Credential Manager
    (keyring). Depois sobrescreve o .env deixando só comentários e variáveis
    vazias — as chaves reais ficam no Credential Manager, protegidas pelo
    login do Windows.

    Uso único (ou pra re-migrar se adicionar chave nova). Após isso,
    carregar_chaves_do_keyring() no startup do cerebro_maestro injeta as
    chaves no os.environ sem precisar do .env.
    """
    try:
        import keyring
        import os
        import pathlib

        env_path = pathlib.Path(__file__).parent / ".env"
        if not env_path.exists():
            return {"ok": False, "erro": ".env não encontrado"}

        linhas = env_path.read_text(encoding="utf-8").splitlines()
        migradas = []
        nao_migradas = []  # chaves fora de _CHAVES_CONHECIDAS: preservadas em texto no .env, não perdidas

        for linha in linhas:
            linha_stripped = linha.strip()
            if not linha_stripped or linha_stripped.startswith("#"):
                continue
            if "=" not in linha_stripped:
                continue
            chave, _, valor = linha_stripped.partition("=")
            chave = chave.strip()
            valor = valor.strip()
            if not valor:
                continue

            # Só migra pro keyring o que também é restaurado por
            # carregar_chaves_do_keyring() (_CHAVES_CONHECIDAS). Bug real
            # corrigido 02/07/2026: antes migrava QUALQUER chave do .env
            # (inclusive TELEGRAM_ALLOWED_USERS) mas só restaurava as 4
            # conhecidas — qualquer chave fora dessa lista era apagada do
            # .env e nunca mais recuperada (achado: silenciosamente abria o
            # bot do Telegram pra qualquer usuário, já que ALLOWED_USERS
            # virava vazio). Agora chaves desconhecidas ficam de fora do
            # keyring e são preservadas como estavam no .env reescrito.
            if chave in _CHAVES_CONHECIDAS:
                keyring.set_password(_KEYRING_SERVICE, chave, valor)
                migradas.append(chave)
            else:
                nao_migradas.append((chave, valor))

        # Sobrescreve .env deixando só comentários (sem valores reais) pras
        # chaves migradas + as não-migradas preservadas com seus valores originais.
        novo_env = (
            "# Chaves conhecidas migradas para o Windows Credential Manager.\n"
            "# Use lyra_seguranca.carregar_chaves_do_keyring() no startup.\n"
            "# Para rever/editar: Painel de Controle > Gerenciador de Credenciais.\n\n"
        )
        for chave in _CHAVES_CONHECIDAS:
            novo_env += f"{chave}=\n"
        if nao_migradas:
            novo_env += "\n# Chaves não migradas (fora de _CHAVES_CONHECIDAS) — preservadas como estavam:\n"
            for chave, valor in nao_migradas:
                novo_env += f"{chave}={valor}\n"
        env_path.write_text(novo_env, encoding="utf-8")

        return {
            "ok": True,
            "migradas": migradas,
            "nao_migradas": [c for c, _ in nao_migradas],
            "aviso": "Chaves conhecidas removidas do .env e salvas no Credential Manager. "
                     "Chaves fora de _CHAVES_CONHECIDAS foram preservadas em texto no .env. "
                     "Reinicie o cerebro_maestro.",
        }
    except ImportError:
        return {"ok": False, "erro": "keyring não instalado. Execute: pip install keyring"}
    except Exception as e:
        return {"ok": False, "erro": str(e)}


def carregar_chaves_do_keyring() -> dict:
    """
    Carrega as API keys do Windows Credential Manager e injeta em os.environ.
    Chamar no startup do cerebro_maestro ANTES de qualquer import que precise
    das chaves.
    """
    import os
    try:
        import keyring
    except ImportError:
        return {"ok": False, "erro": "keyring não instalado"}

    carregadas = []
    for chave in _CHAVES_CONHECIDAS:
        valor = keyring.get_password(_KEYRING_SERVICE, chave)
        if valor:
            os.environ[chave] = valor
            carregadas.append(chave)

    return {"ok": True, "carregadas": carregadas}


def listar_chaves_keyring() -> dict:
    """Lista quais chaves existem no Credential Manager (sem mostrar os valores)."""
    try:
        import keyring
        existentes = []
        for chave in _CHAVES_CONHECIDAS:
            val = keyring.get_password(_KEYRING_SERVICE, chave)
            existentes.append({"chave": chave, "configurada": bool(val)})
        return {"ok": True, "chaves": existentes}
    except ImportError:
        return {"ok": False, "erro": "keyring não instalado"}
    except Exception as e:
        return {"ok": False, "erro": str(e)}


# ── Health check de serviços ──────────────────────────────────────────────────

_SERVICOS = {
    "SurrealDB":     ("http", "127.0.0.1", 8090, "/health"),
    "Qdrant":        ("http", "127.0.0.1", 6333, "/healthz"),
    "embed_service": ("http", "127.0.0.1", 8001, "/health"),
    "Ollama":        ("http", "127.0.0.1", 11434, "/api/version"),
    "FastAPI":       ("http", "127.0.0.1", 8000, "/health"),
}

_RESTART_CMDS = {
    # Achado real 04/08/2026 (não teórico — reproduziu ao vivo durante um
    # teste de restart manual): os três comandos abaixo duplicavam a lógica
    # dos scripts de boot canônicos (start_*.bat) com flags DIFERENTES e
    # incompletas — SurrealDB usava engine "rocksdb:" (dado real em disco é
    # "surrealkv://", confirmado pelos arquivos .sst/vlog/wal) e bind 0.0.0.0;
    # Qdrant não setava QDRANT__STORAGE__STORAGE_PATH nem QDRANT__SERVICE__HOST
    # — rodando assim, ele sobe em "C:\Lyra_Project\storage" (path default,
    # relativo ao WorkingDirectory), uma coleção NOVA E VAZIA, sem os 3M+
    # vetores reais em qdrant_data/. O self-healing reportaria "reiniciado
    # com sucesso" enquanto a Lyra ficava efetivamente amnésica — pior que o
    # serviço só ter caído. Fix: os três agora chamam os mesmos start_*.bat
    # usados no boot normal — uma fonte de verdade só, sem duplicação que
    # pode divergir de novo no futuro.
    # Start-Process (não "cmd /c" direto) é obrigatório aqui: os start_*.bat
    # rodam o servidor em primeiro plano (última linha bloqueia redirecionando
    # pro log) — tentar_reiniciar_servico() usa subprocess.run(timeout=15),
    # que mataria o processo no timeout se ele não fosse desacoplado com
    # Start-Process. Com Start-Process, o .bat vira um processo independente
    # e o powershell retorna na hora.
    "SurrealDB": (
        r'Start-Process -WindowStyle Hidden -FilePath "C:\Lyra_Project\bin\startup\start_surreal.bat"'
    ),
    "Qdrant": (
        r'Start-Process -WindowStyle Hidden -FilePath "C:\Lyra_Project\bin\startup\start_qdrant.bat"'
    ),
    "embed_service": (
        r'Start-Process -WindowStyle Hidden -FilePath "C:\Lyra_Project\bin\startup\start_embed.bat"'
    ),
    # Ollama entrou em 04/08/2026 (noite): foi achado FORA DO AR em auditoria
    # (andar local da cascata morto + draft do spec-decoding falhando) e o
    # self-healing não cobria. Mesmo padrão dos demais: só chama o .bat de boot.
    "Ollama": (
        r'Start-Process -WindowStyle Hidden -FilePath "C:\Lyra_Project\bin\startup\start_ollama.bat"'
    ),
}


def checar_servicos() -> dict:
    """Verifica status de todos os serviços críticos via HTTP."""
    resultado = {}
    for nome, (proto, host, porta, path) in _SERVICOS.items():
        try:
            r = requests.get(f"{proto}://{host}:{porta}{path}", timeout=3)
            resultado[nome] = {"ok": r.status_code < 500, "status_http": r.status_code}
        except Exception as e:
            resultado[nome] = {"ok": False, "erro": str(e)[:80]}
    return {"ok": True, "servicos": resultado}


def tentar_reiniciar_servico(nome: str) -> dict:
    """
    Tenta reiniciar um serviço que caiu. Apenas serviços com cmd definido
    em _RESTART_CMDS são reiniciáveis automaticamente.
    """
    import subprocess
    if nome not in _RESTART_CMDS:
        return {"ok": False, "erro": f"Reinício automático não configurado para '{nome}'."}
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _RESTART_CMDS[nome]],
            timeout=15,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        # 3s fixo reportava falha em falso pro Qdrant: com 3M+ vetores ele
        # demora 5-8s pra carregar do disco (achado 04/08/2026, teste ao vivo
        # — o restart funcionava certinho mas o check corria cedo demais e
        # dizia "não conseguiu reiniciar"). Poll de até 20s em vez de sleep fixo.
        status = {}
        for _ in range(10):
            time.sleep(2)
            status = checar_servicos()["servicos"].get(nome, {})
            if status.get("ok"):
                break
        return {"ok": status.get("ok", False), "servico": nome, "status_apos": status}
    except Exception as e:
        return {"ok": False, "erro": str(e)}
