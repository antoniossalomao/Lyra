"""tools/os_tools.py — OS-level tools: run PowerShell commands, open apps, control windows and media playback."""

import os
import subprocess

def executar_comando(cmd: str, timeout: int = 30) -> dict:
    """Executa comando PowerShell. Retorna stdout, stderr e código de saída."""
    try:
        # PowerShell 5.1 formata a saída na codepage OEM do console (ex: 850
        # neste Windows), não em UTF-8 — decodificar como utf-8 corrompia
        # silenciosamente qualquer acento em "�" (achado real 02/07/2026,
        # confirmado: "ção" virava "�o"). Força a própria sessão do PowerShell
        # a emitir UTF-8 antes de rodar o comando do usuário — evita depender
        # da codepage OEM de cada máquina.
        cmd_utf8 = ("$OutputEncoding = [Console]::OutputEncoding = "
                    "[System.Text.Encoding]::UTF8; " + cmd)
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd_utf8],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        return {
            "stdout": r.stdout.strip(),
            "stderr": r.stderr.strip(),
            "codigo": r.returncode,
            "ok":     r.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {"erro": f"Timeout após {timeout}s", "ok": False}
    except Exception as e:
        return {"erro": str(e), "ok": False}

def abrir_app(nome: str) -> dict:
    """Abre aplicativo pelo nome ou caminho completo."""
    try:
        if os.path.exists(nome):
            os.startfile(nome)
            return {"ok": True, "aberto": nome}
        # Escapa aspas simples (dobra '') — nome com apóstrofo (comum em
        # caminho/título de app) quebrava a string do PowerShell sem aviso.
        nome_escapado = nome.replace("'", "''")
        # Mesma correção de encoding de executar_comando — sem isso, o
        # stderr de erro do PowerShell (ex: "arquivo não encontrado") sai
        # com acentos corrompidos em "�".
        cmd_ps = ("$OutputEncoding = [Console]::OutputEncoding = "
                  "[System.Text.Encoding]::UTF8; "
                  f"Start-Process '{nome_escapado}'")
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd_ps],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        return {"ok": r.returncode == 0, "aberto": nome,
                "erro": r.stderr.strip() if r.returncode != 0 else None}
    except Exception as e:
        return {"erro": str(e), "ok": False}

def controlar_midia(acao: str) -> dict:
    """
    Controla volume/reprodução de mídia do Windows via SendKeys (mesma técnica
    já usada no despachante de voz em Lyra_Core/commands.py, agora exposta
    também pro chat de texto). acao: 'volume_alto' | 'volume_baixo' | 'pausar' | 'continuar'.
    """
    mapa = {"volume_alto": ("175", 10), "volume_baixo": ("174", 10),
            "pausar": ("179", 1), "continuar": ("179", 1)}
    if acao not in mapa:
        return {"erro": f"Ação inválida: {acao}. Use: volume_alto, volume_baixo, pausar, continuar.", "ok": False}
    tecla, repeticoes = mapa[acao]
    try:
        ps = (f"$obj = New-Object -ComObject WScript.Shell; "
              f"for ($i=0; $i -lt {repeticoes}; $i++) {{ $obj.SendKeys([char]{tecla}) }}")
        subprocess.run(["powershell", "-NoProfile", "-command", ps],
                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
        return {"ok": True, "acao": acao}
    except Exception as e:
        return {"erro": str(e), "ok": False}

def controlar_janela(app_nome: str, acao: str, elemento: str = "", valor: str = "") -> dict:
    """
    Controla janelas e elementos de UI de aplicativos Windows.
    app_nome: título parcial da janela ou nome do executável (ex: 'Notepad', 'chrome.exe').
    acao: 'focar' | 'minimizar' | 'maximizar' | 'fechar' | 'clicar' | 'escrever' |
          'listar_elementos' | 'capturar_texto'.
    elemento: nome/texto do botão, campo ou controle alvo (necessário para clicar/escrever).
    valor: texto a digitar (necessário para 'escrever').
    """
    try:
        from pywinauto import Application, Desktop
        from pywinauto.findwindows import ElementNotFoundError

        # Localiza janela pelo título parcial
        try:
            janela = Desktop(backend="uia").windows(title_re=f".*{app_nome}.*")
            if not janela:
                janela = Desktop(backend="win32").windows(title_re=f".*{app_nome}.*")
            if not janela:
                return {"erro": f"Nenhuma janela encontrada com título contendo '{app_nome}'."}
            win = janela[0]
        except Exception as e:
            return {"erro": f"Erro ao localizar janela: {e}"}

        if acao == "focar":
            win.set_focus()
            return {"ok": True, "acao": "focar", "janela": win.window_text()}

        elif acao == "minimizar":
            win.minimize()
            return {"ok": True, "acao": "minimizar"}

        elif acao == "maximizar":
            win.maximize()
            return {"ok": True, "acao": "maximizar"}

        elif acao == "fechar":
            win.close()
            return {"ok": True, "acao": "fechar"}

        elif acao == "listar_elementos":
            win.set_focus()
            controles = []
            for ctrl in win.descendants():
                try:
                    controles.append({
                        "tipo":  ctrl.friendly_class_name(),
                        "texto": ctrl.window_text()[:80],
                    })
                except Exception:
                    pass
            return {"ok": True, "elementos": controles[:50]}

        elif acao == "capturar_texto":
            win.set_focus()
            return {"ok": True, "texto": win.window_text()}

        elif acao == "clicar":
            if not elemento:
                return {"erro": "'elemento' é obrigatório para ação 'clicar'."}
            win.set_focus()
            ctrl = win.child_window(title=elemento, found_index=0)
            ctrl.click_input()
            return {"ok": True, "acao": "clicar", "elemento": elemento}

        elif acao == "escrever":
            if not elemento:
                return {"erro": "'elemento' é obrigatório para ação 'escrever'."}
            win.set_focus()
            ctrl = win.child_window(title=elemento, found_index=0)
            ctrl.set_edit_text(valor)
            return {"ok": True, "acao": "escrever", "elemento": elemento, "valor": valor}

        else:
            return {"erro": f"Ação desconhecida: '{acao}'. Use: focar, minimizar, maximizar, fechar, clicar, escrever, listar_elementos, capturar_texto."}

    except Exception as e:
        return {"erro": str(e), "ok": False}


SCHEMA = [
        {
            "type": "function",
            "function": {
                "name": "executar_comando",
                "description": "Executa comando PowerShell.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cmd":     {"type": "string"},
                        "timeout": {"type": "integer"},
                    },
                    "required": ["cmd"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "abrir_app",
                "description": "Abre um programa ou URL.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "nome": {"type": "string"},
                    },
                    "required": ["nome"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "controlar_midia",
                "description": "Controla volume/play-pausa de mídia no Windows.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "acao": {"type": "string", "enum": ["volume_alto", "volume_baixo", "pausar", "continuar"]},
                    },
                    "required": ["acao"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "controlar_janela",
                "description": (
                    "Controla janelas e elementos de UI de aplicativos Windows abertos. "
                    "Pode focar, minimizar, maximizar, fechar, clicar em botões, escrever em campos, "
                    "listar elementos clicáveis e capturar texto de uma janela. "
                    "Use quando o usuário pedir para interagir com um app já aberto (preencher formulário, clicar em botão, etc)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "app_nome":  {"type": "string", "description": "Título parcial da janela (ex: 'Notepad', 'Chrome', 'Formulário')."},
                        "acao":      {"type": "string", "description": "Ação: focar | minimizar | maximizar | fechar | clicar | escrever | listar_elementos | capturar_texto."},
                        "elemento":  {"type": "string", "description": "Nome/texto do controle alvo (necessário para clicar/escrever)."},
                        "valor":     {"type": "string", "description": "Texto a digitar (necessário para 'escrever')."},
                    },
                    "required": ["app_nome", "acao"],
                },
            },
        },
]


MAP = {
    "executar_comando": executar_comando,
    "abrir_app": abrir_app,
    "controlar_midia": controlar_midia,
    "controlar_janela": controlar_janela,
}
