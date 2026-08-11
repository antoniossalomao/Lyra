"""tools/specialist.py — Delegation tools: consult a local/cloud specialist model, and safe dynamic tool creation (auto-extension)."""

import ast
import json
import pathlib
import re
import subprocess
import shutil
import urllib.request
import urllib.error
from datetime import datetime

from .notifications import notificar_usuario

# __file__ está em tools/ — sobe um nível pra manter o mesmo diretório em
# disco que o lyra_tools.py monolítico usava (lyra_tools_ext/ já existente).
_TOOLS_EXT_DIR = pathlib.Path(__file__).parent.parent / "lyra_tools_ext"
_TOOLS_EXT_DIR.mkdir(exist_ok=True)

_TOOLS_EXT_INDEX = _TOOLS_EXT_DIR / "_index.json"

# Padrões heurísticos de risco — varredura estática no código antes de liberar
# uma ferramenta auto-criada. Não é à prova de bypass (regex não entende
# semântica), mas pega os casos óbvios de blast-radius alto sem incomodar o
# usuário pra ferramentas inofensivas (ex: somar dois números).
_PADROES_RISCO = [
    (r"shutil\.rmtree|os\.remove\(|os\.unlink\(|send2trash", "exclusão de arquivos/pastas"),
    (r"subprocess\.|os\.system\(|os\.popen\(", "execução de comandos do sistema"),
    (r"\beval\(|\bexec\(|compile\(", "execução de código arbitrário"),
    (r"winreg\.|regedit|reg\.exe", "edição do registro do Windows"),
    (r"shutdown|taskkill|Stop-Process|Stop-Computer", "controle de processos/encerramento do sistema"),
    (r"requests\.(post|put|patch)\(|urlopen\(.*http", "envio de dados pela rede"),
    (r"smtplib|socket\.(socket|connect)", "comunicação de rede de baixo nível"),
    (r"password|senha|api[_-]?key|secret|credential|token", "possível acesso a credenciais"),
    (r"ctypes\.|win32api|win32con", "acesso de baixo nível ao sistema operacional"),
    (r"\.ssh\b|\.aws\b|\.env\b", "acesso a arquivos sensíveis de configuração"),
]

def _escanear_riscos(codigo: str) -> list[str]:
    riscos = []
    for padrao, descricao in _PADROES_RISCO:
        if re.search(padrao, codigo, re.IGNORECASE):
            riscos.append(descricao)
    return riscos

def criar_ferramenta(nome: str, descricao: str, codigo: str) -> dict:
    """
    Cria nova ferramenta Python gerada pelo agente (auto-extensão).
    Valida sintaxe e escaneia por padrões de risco antes de salvar — se achar
    algo suspeito, a ferramenta fica 'pendente_aprovacao' e não pode ser
    chamada até o usuário aprovar manualmente (aprovar_ferramenta_ext, fora
    do schema de function-calling — a própria Lyra não pode se autoaprovar).
    """
    try:
        nome_safe = re.sub(r"[^a-z0-9_]", "_", nome.lower())
        arquivo   = _TOOLS_EXT_DIR / f"{nome_safe}.py"

        # Valida sintaxe (sem subprocess — evita problemas de escaping e de
        # depender de "python" estar no PATH)
        import ast
        try:
            ast.parse(codigo)
        except SyntaxError as e:
            return {"ok": False, "erro": f"Código inválido: {e}"}

        riscos = _escanear_riscos(codigo)

        header = (
            f'"""\n{descricao}\n'
            f'Gerado por lyra_agent em {datetime.now().isoformat()}\n"""\n\n'
        )
        arquivo.write_text(header + codigo, encoding="utf-8")

        index: dict = {}
        if _TOOLS_EXT_INDEX.exists():
            index = json.loads(_TOOLS_EXT_INDEX.read_text(encoding="utf-8"))
        index[nome_safe] = {
            "descricao":          descricao,
            "arquivo":            str(arquivo),
            "criado":             datetime.now().isoformat(),
            "riscos_detectados":  riscos,
            "pendente_aprovacao": bool(riscos),
        }
        _TOOLS_EXT_INDEX.write_text(
            json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

        if riscos:
            return {
                "ok": True, "nome": nome_safe, "path": str(arquivo),
                "status": "PENDENTE_APROVACAO",
                "aviso": (f"Ferramenta salva mas BLOQUEADA até o usuário aprovar manualmente. "
                          f"Padrões de risco detectados: {', '.join(riscos)}."),
            }

        return {"ok": True, "nome": nome_safe, "path": str(arquivo)}
    except Exception as e:
        return {"erro": str(e), "ok": False}

def listar_ferramentas_ext() -> dict:
    """Lista ferramentas criadas dinamicamente pelo agente."""
    try:
        if not _TOOLS_EXT_INDEX.exists():
            return {"ferramentas": [], "total": 0}
        index = json.loads(_TOOLS_EXT_INDEX.read_text(encoding="utf-8"))
        return {"ferramentas": list(index.values()), "total": len(index)}
    except Exception as e:
        return {"erro": str(e)}

def aprovar_ferramenta_ext(nome: str) -> dict:
    """
    Aprova manualmente uma ferramenta auto-criada que ficou pendente por ter
    disparado algum padrão de risco. DELIBERADAMENTE NÃO está em TOOLS_SCHEMA/
    TOOLS_MAP — a Lyra não tem acesso a essa função via function-calling, só o
    usuário (ou alguém chamando este módulo diretamente) pode liberar.
    """
    try:
        if not _TOOLS_EXT_INDEX.exists():
            return {"ok": False, "erro": "Nenhuma ferramenta extra registrada."}
        index = json.loads(_TOOLS_EXT_INDEX.read_text(encoding="utf-8"))
        nome_safe = re.sub(r"[^a-z0-9_]", "_", nome.lower())
        if nome_safe not in index:
            return {"ok": False, "erro": f"Ferramenta não encontrada: {nome_safe}"}
        index[nome_safe]["pendente_aprovacao"] = False
        index[nome_safe]["aprovado_em"] = datetime.now().isoformat()
        _TOOLS_EXT_INDEX.write_text(
            json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "nome": nome_safe, "status": "APROVADA"}
    except Exception as e:
        return {"ok": False, "erro": str(e)}

def consultar_especialista(problema: str, nivel: str, aprovado: bool = False) -> dict:
    """Delega uma tarefa complexa para um modelo especialista (Local ou Nuvem)."""
    if nivel == "cloud" and not aprovado:
        return {
            "status": "BLOQUEADO",
            "mensagem": "AVISO DE SEGURANÇA: O uso de nuvem (Claude/OpenAI) quebra a Diretiva Nº 2 e requer aprovação explícita. Pergunte ao usuário se ele aprova o envio do problema para a nuvem. Se ele disser sim, chame esta ferramenta novamente com aprovado=True."
        }

    if nivel == "cloud":
        # Exceção consciente à Diretiva Nº 2 (decidida com Antônio em 24/06/2026):
        # delega pra Claude Code (Sonnet) via CLI headless, com agente completo
        # (acesso a arquivo/shell no projeto), avisando o usuário antes de chamar.
        notificar_usuario(
            titulo="Lyra → Claude Code",
            mensagem=f"Delegando para o Claude (Sonnet): {problema[:120]}",
            urgencia="normal",
        )
        try:
            import shutil
            import subprocess
            claude_path = shutil.which("claude")
            if not claude_path:
                return {"erro": "CLI 'claude' não encontrado no PATH.", "ok": False}

            resultado = subprocess.run(
                [claude_path, "-p", problema, "--model", "sonnet",
                 "--allow-dangerously-skip-permissions"],
                cwd=r"C:\Lyra_Project",
                capture_output=True,
                text=True,
                timeout=600,
            )
            if resultado.returncode != 0:
                return {"erro": resultado.stderr.strip() or "Claude Code retornou erro.",
                        "status": "FALHA"}
            return {
                "status": "SUCESSO",
                "especialista": "Claude (Sonnet, agente completo via Claude Code)",
                "resposta_do_especialista": resultado.stdout.strip(),
            }
        except subprocess.TimeoutExpired:
            return {"erro": "Claude Code excedeu o tempo limite (10min).", "ok": False}
        except Exception as e:
            return {"erro": str(e), "ok": False}

    # Delegar para Especialista Local (Qwen Coder)
    try:
        from ollama import Client
        c = Client(host='http://127.0.0.1:11434')
        res = c.chat(
            model='qwen2.5-coder:7b',
            messages=[
                {"role": "system", "content": "Você é um Especialista Sênior em Engenharia de Software. Resolva o problema a seguir escrevendo o código mais otimizado, seguro e robusto possível."},
                {"role": "user", "content": problema}
            ]
        )
        return {
            "status": "SUCESSO",
            "especialista": "qwen2.5-coder:7b (Local)",
            "resposta_do_especialista": res['message']['content']
        }
    except Exception as e:
        return {"erro": str(e)}

def _enxame_req(method: str, path: str, payload: dict | None = None) -> dict:
    """Chama o endpoint de enxame no cerebro_maestro (:8000) de forma síncrona."""
    import urllib.request
    import urllib.error
    url = f"http://127.0.0.1:8000{path}"
    try:
        data = json.dumps(payload).encode() if payload else None
        req  = urllib.request.Request(
            url, data=data, method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"erro": f"HTTP {e.code}: {e.read().decode()[:300]}"}
    except Exception as e:
        return {"erro": f"Falha ao chamar cerebro: {e}"}


def criar_enxame(objetivo: str, subtarefas: list, max_paralelo: int = 3) -> dict:
    """Cria um enxame de sub-agentes paralelos via HTTP no cerebro_maestro (:8000)."""
    return _enxame_req("POST", "/enxame",
                       {"objetivo": objetivo, "subtarefas": subtarefas, "max_paralelo": max_paralelo})


def status_enxame(enxame_id: str) -> dict:
    """Consulta o progresso de um enxame via HTTP no cerebro_maestro (:8000)."""
    return _enxame_req("GET", f"/enxame/{enxame_id}")


def consolidar_enxame(enxame_id: str) -> dict:
    """Consolida os resultados de um enxame via HTTP no cerebro_maestro (:8000)."""
    return _enxame_req("POST", f"/enxame/{enxame_id}/consolidar")


SCHEMA = [
        {
            "type": "function",
            "function": {
                "name": "criar_enxame",
                "description": (
                    "Cria um enxame de sub-agentes paralelos para executar múltiplas sub-tarefas independentes ao mesmo tempo. "
                    "Use quando o usuário pedir algo que pode ser dividido em partes paralelas (ex: resumir 3 PDFs, pesquisar X em 4 fontes). "
                    "Retorna imediatamente — as sub-tarefas rodam em background. Use status_enxame para acompanhar."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "objetivo":     {"type": "string", "description": "Descrição do objetivo geral do enxame."},
                        "subtarefas":   {"type": "array", "items": {"type": "string"},
                                         "description": "Lista de sub-tarefas independentes (max 20). Cada item deve ser auto-suficiente."},
                        "max_paralelo": {"type": "integer", "default": 3,
                                         "description": "Máx de sub-tarefas simultâneas (1-6). Padrão 3."},
                    },
                    "required": ["objetivo", "subtarefas"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "status_enxame",
                "description": "Retorna o progresso de um enxame: quantas sub-tarefas estão pendentes, rodando, concluídas ou com erro.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "enxame_id": {"type": "string", "description": "ID do enxame retornado por criar_enxame."},
                    },
                    "required": ["enxame_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "consolidar_enxame",
                "description": "Consolida os resultados de todas as sub-tarefas de um enxame num único texto coeso via LLM. Só funciona quando o enxame estiver concluído.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "enxame_id": {"type": "string", "description": "ID do enxame a consolidar."},
                    },
                    "required": ["enxame_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "criar_ferramenta",
                "description": "Gera código Python de nova tool.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "nome":      {"type": "string"},
                        "descricao": {"type": "string"},
                        "codigo":    {"type": "string"},
                    },
                    "required": ["nome", "descricao", "codigo"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "listar_ferramentas_ext",
                "description": "Lista todas as ferramentas criadas dinamicamente pelo agente.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "consultar_especialista",
                "description": "Delega um problema complexo (código, tarefa difícil, pesquisa profunda) para um Agente Especialista local ou na nuvem.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "problema": {"type": "string", "description": "Descrição detalhada da tarefa/desafio."},
                        "nivel":    {"type": "string", "enum": ["local", "cloud"], "description": "local = Qwen Coder (sem rede); cloud = Claude (Sonnet) via Claude Code, com agente completo (lê/edita arquivos e roda comandos no projeto) — quebra a Diretiva Nº 2, exige aprovado=True."},
                        "aprovado": {"type": "boolean", "description": "Use True apenas se o usuário tiver explicitamente autorizado o uso da nuvem (ou se o usuário já pediu nessa mesma mensagem para usar o Claude)."}
                    },
                    "required": ["problema", "nivel"]
                }
            }
        },
]


MAP = {
    "criar_ferramenta": criar_ferramenta,
    "listar_ferramentas_ext": listar_ferramentas_ext,
    "consultar_especialista": consultar_especialista,
    "criar_enxame": criar_enxame,
    "status_enxame": status_enxame,
    "consolidar_enxame": consolidar_enxame,
}
