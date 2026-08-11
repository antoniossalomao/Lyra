"""tools/fs.py — File and filesystem tools: read/write files, list directories, organize folders by type/date/size."""

import os
import shutil
import pathlib
import time
from datetime import datetime

def ler_arquivo(path: str) -> dict:
    """Lê conteúdo de um arquivo de texto."""
    try:
        p = pathlib.Path(path)
        if not p.exists():
            return {"erro": f"Arquivo não encontrado: {path}"}
        if p.stat().st_size > 10 * 1024 * 1024:
            return {"erro": "Arquivo >10 MB. Use listar_arquivos para navegar."}
        conteudo = p.read_text(encoding="utf-8", errors="replace")
        return {"path": str(p), "tamanho_bytes": p.stat().st_size, "conteudo": conteudo}
    except Exception as e:
        return {"erro": str(e)}

def escrever_arquivo(path: str, conteudo: str, modo: str = "w") -> dict:
    """Escreve/cria arquivo de texto. modo: 'w'=sobrescrever, 'a'=append."""
    try:
        p = pathlib.Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, modo, encoding="utf-8") as f:
            f.write(conteudo)
        return {"ok": True, "path": str(p), "bytes_escritos": len(conteudo.encode())}
    except Exception as e:
        return {"erro": str(e)}

def listar_arquivos(path: str, extensao: str = "") -> dict:
    """Lista arquivos e pastas. extensao filtra por tipo, ex: '.py', '.pdf'."""
    try:
        p = pathlib.Path(path)
        if not p.exists():
            return {"erro": f"Caminho não encontrado: {path}"}
        items = []
        for item in sorted(p.iterdir()):
            if extensao and item.suffix.lower() != extensao.lower():
                continue
            items.append({
                "nome":       item.name,
                "tipo":       "dir" if item.is_dir() else "arquivo",
                "tamanho":    item.stat().st_size if item.is_file() else None,
                "modificado": datetime.fromtimestamp(
                    item.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
            })
        return {"path": str(p), "total": len(items), "items": items}
    except Exception as e:
        return {"erro": str(e)}

def organizar_pasta(path: str, criterio: str = "tipo") -> dict:
    """
    Organiza arquivos em subpastas.
    criterio: 'tipo' (por extensão), 'data' (por mês/ano), 'tamanho' (small/med/large)
    """
    TIPO_MAP = {
        ".pdf": "Documentos",  ".doc": "Documentos",   ".docx": "Documentos",
        ".xls": "Planilhas",   ".xlsx": "Planilhas",
        ".ppt": "Apresentacoes", ".pptx": "Apresentacoes",
        ".jpg": "Imagens",     ".jpeg": "Imagens",      ".png": "Imagens",
        ".gif": "Imagens",     ".bmp": "Imagens",       ".webp": "Imagens",
        ".mp4": "Videos",      ".mkv": "Videos",        ".avi": "Videos",
        ".mov": "Videos",
        ".mp3": "Audio",       ".wav": "Audio",         ".flac": "Audio",
        ".py":  "Codigo",      ".js":  "Codigo",        ".ts":  "Codigo",
        ".rs":  "Codigo",      ".go":  "Codigo",        ".java": "Codigo",
        ".cpp": "Codigo",      ".c":   "Codigo",
        ".zip": "Arquivados",  ".rar": "Arquivados",    ".7z":  "Arquivados",
        ".txt": "Texto",       ".md":  "Texto",
        ".csv": "Dados",       ".json": "Dados",        ".xml": "Dados",
    }
    try:
        p = pathlib.Path(path)
        if not p.exists():
            return {"erro": f"Caminho não existe: {path}"}
        if criterio not in ("tipo", "data", "tamanho"):
            return {"erro": f"Critério inválido: {criterio}. Use: tipo, data, tamanho"}

        movidos = []
        for arquivo in list(p.iterdir()):
            if not arquivo.is_file():
                continue

            if criterio == "tipo":
                pasta_dest = TIPO_MAP.get(arquivo.suffix.lower(), "Outros")
            elif criterio == "data":
                dt = datetime.fromtimestamp(arquivo.stat().st_mtime)
                pasta_dest = dt.strftime("%Y-%m")
            else:  # tamanho
                s = arquivo.stat().st_size
                if s < 1024 * 1024:
                    pasta_dest = "Pequenos_menos1MB"
                elif s < 100 * 1024 * 1024:
                    pasta_dest = "Medios_1a100MB"
                else:
                    pasta_dest = "Grandes_mais100MB"

            destino_dir = p / pasta_dest
            destino_dir.mkdir(exist_ok=True)
            destino = destino_dir / arquivo.name

            if destino.exists():
                destino = destino_dir / f"{arquivo.stem}_{int(time.time())}{arquivo.suffix}"

            shutil.move(str(arquivo), str(destino))
            movidos.append({"de": arquivo.name,
                            "para": f"{pasta_dest}/{destino.name}"})

        return {"ok": True, "criterio": criterio,
                "movidos": len(movidos), "detalhes": movidos}
    except Exception as e:
        return {"erro": str(e)}


SCHEMA = [
        {
            "type": "function",
            "function": {
                "name": "ler_arquivo",
                "description": "Lê texto de um arquivo.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "escrever_arquivo",
                "description": "Salva texto em um arquivo.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path":     {"type": "string"},
                        "conteudo": {"type": "string"},
                        "modo":     {"type": "string"},
                    },
                    "required": ["path", "conteudo"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "listar_arquivos",
                "description": "Lista arquivos em um diretório.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path":     {"type": "string"},
                        "extensao": {"type": "string"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "organizar_pasta",
                "description": "Organiza arquivos por extensão.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path":     {"type": "string"},
                        "criterio": {"type": "string"},
                    },
                    "required": ["path"],
                },
            },
        },
]


MAP = {
    "ler_arquivo": ler_arquivo,
    "escrever_arquivo": escrever_arquivo,
    "listar_arquivos": listar_arquivos,
    "organizar_pasta": organizar_pasta,
}
