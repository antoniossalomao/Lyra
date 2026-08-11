"""
commands.py — Despachante de Comandos Locais da Lyra
"""

import ctypes
import ctypes.wintypes
import os
import subprocess
import sys
import time
import threading
from typing import Callable, Optional

# ── Importa TTS ───────────────────────────────────────────────────────────────
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from audio_manager import falar_sync as falar
except Exception as e:
    print(f"[CMD][WARN] TTS indisponível: {e}")
    def falar(texto: str):
        print(f"[LYRA] {texto}")

_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Minimizar janela por título (com retry) ───────────────────────────────────
def _minimizar_janela(titulo_parcial: str, tentativas: int = 4, intervalo: float = 1.0):
    """
    Tenta minimizar a janela N vezes, com intervalo entre tentativas.
    Cobre o caso de o Spotify reabrir a janela após processar a URI.
    """
    def _run():
        SW_MINIMIZE = 6
        user32 = ctypes.windll.user32
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

        for i in range(tentativas):
            time.sleep(intervalo)

            def _callback(hwnd, _):
                if user32.IsWindowVisible(hwnd):
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buf = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buf, length + 1)
                        if titulo_parcial.lower() in buf.value.lower():
                            user32.ShowWindow(hwnd, SW_MINIMIZE)
                            print(f"[CMD] Janela '{buf.value}' minimizada (tentativa {i+1})")
                return True

            user32.EnumWindows(EnumWindowsProc(_callback), 0)

    threading.Thread(target=_run, daemon=True).start()


# ── Frontend ──────────────────────────────────────────────────────────────────
def abrir_frontend():
    """Lança o frontend da Lyra em tela cheia."""
    frontend = os.path.join(_DIR, "Front_end_Lyra", "lyra_app.py")
    if not os.path.exists(frontend):
        print(f"[CMD][WARN] Frontend não encontrado: {frontend}")
        return
    try:
        subprocess.Popen([sys.executable, frontend])
        print("[CMD] Frontend iniciado.")
    except Exception as e:
        print(f"[CMD] Frontend erro: {e}")


# ── Spotify ───────────────────────────────────────────────────────────────────
def abrir_spotify_back_in_black():
    """Toca Back in Black e mantém o Spotify minimizado."""
    TRACK_URI = "spotify:track:08mG3Y1vljYA6bvDt4Wqkj"
    try:
        # os.startfile é a forma mais limpa de abrir URI no Windows
        os.startfile(TRACK_URI)
        print("[CMD] Spotify URI enviado.")
    except Exception as e:
        print(f"[CMD] Spotify erro: {e}")
        try:
            subprocess.Popen(["cmd", "/c", "start", "", TRACK_URI],
                             creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception as e2:
            print(f"[CMD] Spotify fallback erro: {e2}")

    # Minimiza 4x com 1s de intervalo — cobre o flash do Spotify ao trocar de faixa
    _minimizar_janela("Spotify", tentativas=4, intervalo=1.0)


# ── Sequência "Bom dia" ───────────────────────────────────────────────────────
def sequencia_bom_dia():
    """Spotify primeiro (minimizado), depois abre o frontend por cima."""
    abrir_spotify_back_in_black()
    time.sleep(3.5)   # tempo da musica comecar a tocar
    abrir_frontend()  # frontend abre por cima do Spotify


def volume_alto():
    subprocess.run(
        ["powershell", "-NoProfile", "-command",
         "$obj = New-Object -ComObject WScript.Shell; "
         "for ($i=0; $i -lt 10; $i++) { $obj.SendKeys([char]175) }"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def volume_baixo():
    subprocess.run(
        ["powershell", "-NoProfile", "-command",
         "$obj = New-Object -ComObject WScript.Shell; "
         "for ($i=0; $i -lt 10; $i++) { $obj.SendKeys([char]174) }"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def pausar_musica():
    subprocess.run(
        ["powershell", "-NoProfile", "-command",
         "$obj = New-Object -ComObject WScript.Shell; $obj.SendKeys([char]179)"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


# ── Tabela de comandos ────────────────────────────────────────────────────────

COMANDOS: dict[str, dict] = {
    "bom dia": {
        "resposta": "Bom dia, Antônio. Sistemas online. Iniciando sequência de ignição.",
        "acao": sequencia_bom_dia,
    },
    "boa tarde": {
        "resposta": "Boa tarde, Antônio. Córtex operacional.",
        "acao": abrir_frontend,
    },
    "boa noite": {
        "resposta": "Boa noite, Antônio. Iniciando modo noturno.",
        "acao": abrir_frontend,
    },
    "pausa": {
        "resposta": "Pausando.",
        "acao": pausar_musica,
    },
    "continua": {
        "resposta": "Continuando.",
        "acao": pausar_musica,
    },
    "volume alto": {
        "resposta": "Volume aumentado.",
        "acao": volume_alto,
    },
    "volume baixo": {
        "resposta": "Volume reduzido.",
        "acao": volume_baixo,
    },
}


# ── Despachante ───────────────────────────────────────────────────────────────

def despachar(texto: str) -> bool:
    texto_lower = texto.lower().strip()
    for gatilho, cmd in COMANDOS.items():
        if gatilho in texto_lower:
            print(f"[CMD] Gatilho: '{gatilho}'")
            resposta = cmd.get("resposta")
            if resposta:
                falar(resposta)
            acao: Optional[Callable] = cmd.get("acao")
            if acao:
                time.sleep(0.3)
                acao()
            return True
    return False


if __name__ == "__main__":
    print("Testando 'bom dia'...")
    despachar("bom dia lyra")
    time.sleep(8)  # aguarda minimizações
