"""tools/git_tools.py — Read-only Git inspection tool (status/log/diff/branch) — no mutating commands exposed."""

import pathlib
import subprocess

_GIT_COMANDOS = {
    "status": lambda repo, limite: ["git", "-C", repo, "status", "--short", "--branch"],
    "log":    lambda repo, limite: ["git", "-C", repo, "log", f"-{limite}", "--oneline"],
    "diff":   lambda repo, limite: ["git", "-C", repo, "diff", "--stat"],
    "branch": lambda repo, limite: ["git", "-C", repo, "branch", "--show-current"],
}

def consultar_git(repo_path: str, comando: str = "status", limite: int = 10) -> dict:
    """
    Consulta somente-leitura de um repositório Git (status/log/diff/branch) —
    de propósito SEM commit/push/checkout/reset, pra Lyra conseguir ter noção
    do que mudou em algum projeto sem nenhum risco de alterar o repositório.
    """
    try:
        if comando not in _GIT_COMANDOS:
            return {"erro": f"comando inválido: {comando}. Use: {', '.join(_GIT_COMANDOS)}."}
        if not pathlib.Path(repo_path).exists():
            return {"erro": f"Caminho não encontrado: {repo_path}"}
        cmd = _GIT_COMANDOS[comando](repo_path, limite)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15,
                           encoding="utf-8", errors="replace")
        return {"ok": r.returncode == 0, "comando": comando,
                "stdout": r.stdout.strip(), "stderr": r.stderr.strip()}
    except Exception as e:
        return {"erro": str(e), "ok": False}


SCHEMA = [
        {
            "type": "function",
            "function": {
                "name": "consultar_git",
                "description": "Consulta somente-leitura de um repositório Git (status, log, diff, branch).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repo_path": {"type": "string"},
                        "comando":   {"type": "string", "enum": ["status", "log", "diff", "branch"]},
                        "limite":    {"type": "integer"},
                    },
                    "required": ["repo_path"],
                },
            },
        },
]


MAP = {
    "consultar_git": consultar_git,
}
