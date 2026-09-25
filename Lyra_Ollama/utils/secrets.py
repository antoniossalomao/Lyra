"""
utils/secrets.py — SecretRef (PLANEJAMENTO_LYRA2.0.md seção 9 item 9,
inspirado no padrão do OpenClaw seção 3.5).

Problema que resolve: hoje `config.py`/`.env` guardam chave de API em texto
puro (`GROQ_API_KEY = os.environ.get(...)`) — funciona, mas não tem
indireção nenhuma. `SecretRef` é essa indireção: em vez de espalhar
`os.getenv("X")` pelo código, um dict `{source, id}` descreve ONDE buscar o
segredo, resolvido uma vez (no boot, tipicamente).

Não substitui nada existente ainda — é só a peça nova disponível pra quem
quiser migrar `config.py` pra usar isso depois (decisão separada, fora de
escopo aqui: mudar como GROQ_API_KEY/SURREAL_AUTH são carregados hoje exige
reiniciar o processo pra validar, não é seguro fazer sem testar ao vivo).
"""
import os
import subprocess
from pathlib import Path
from typing import Literal, TypedDict


class SecretRef(TypedDict, total=False):
    source: Literal["env", "file", "exec"]
    id: str  # nome da env var, path do arquivo, ou comando (lista de args)


class SecretResolutionError(Exception):
    """Levantado quando um SecretRef não consegue ser resolvido."""


def resolve_secret(ref: SecretRef) -> str:
    """Resolve um SecretRef pro valor real do segredo.

    - source='env':  ref['id'] é o nome da variável de ambiente.
    - source='file': ref['id'] é o path do arquivo; conteúdo é lido e
      stripado (formato comum de secret mount / arquivo `.token`).
    - source='exec': ref['id'] é um comando (string, split por espaço —
      SEM shell=True de propósito, pra não abrir injeção de comando via
      config). O segredo é o stdout, stripado. Uso esperado: comando de um
      gerenciador de senha local configurado pelo próprio usuário, nunca
      input vindo de uma requisição.

    Não faz cache — chamador decide se quer resolver 1x no boot e guardar
    em memória (é o padrão recomendado, mesmo do OpenClaw).
    """
    source = ref.get("source")
    valor_id = ref.get("id", "")

    if source == "env":
        valor = os.environ.get(valor_id)
        if valor is None:
            raise SecretResolutionError(f"Variável de ambiente '{valor_id}' não definida.")
        return valor

    if source == "file":
        caminho = Path(valor_id)
        if not caminho.is_file():
            raise SecretResolutionError(f"Arquivo de segredo não encontrado: {valor_id}")
        return caminho.read_text(encoding="utf-8").strip()

    if source == "exec":
        try:
            resultado = subprocess.run(
                valor_id.split(), capture_output=True, text=True, timeout=10, check=True)
        except Exception as e:
            raise SecretResolutionError(f"Comando de segredo falhou ('{valor_id}'): {e}") from e
        return resultado.stdout.strip()

    raise SecretResolutionError(f"source de SecretRef desconhecido: {source!r}")


def mask_secret(valor: str, visible: int = 4) -> str:
    """Sentinela pra log/config — mostra só os últimos N caracteres.
    Ex: 'gsk_abc123xyz' -> 'oc-sent-v1-***3xyz'. Nunca loga o segredo inteiro."""
    if len(valor) <= visible:
        return "oc-sent-v1-***"
    return f"oc-sent-v1-***{valor[-visible:]}"
