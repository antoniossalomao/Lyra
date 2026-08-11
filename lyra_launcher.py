"""
lyra_launcher.py — Orquestrador único da Lyra
Inicia: Qdrant → SurrealDB → Ollama → Cérebro (FastAPI:8000) → Mic → Frontend

Correções 2026-05-07:
  - Auto-download do Qdrant (v1.17.1) se binário ausente
  - Detecta e para serviço Windows do SurrealDB (NSSM) para evitar
    conflito de porta com FastAPI :8000
  - Remove LOCK stale do SurrealDB antes de iniciar
  - Melhor detecção de conflito de portas
"""

import os
import sys

# Evita UnicodeEncodeError ao imprimir ✓/✗/⚠/→ em consoles não-UTF-8
# (acontece quando a saída é redirecionada/capturada e o Python cai para a ANSI codepage)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import time
import signal
import subprocess
import threading
import socket
import ctypes
import zipfile
import shutil
from urllib.request import urlretrieve
from urllib.error import URLError

# ── Configuração ──────────────────────────────────────────────────────────────
BASE        = os.path.dirname(os.path.abspath(__file__))
PYTHON      = sys.executable
CORE        = os.path.join(BASE, "Lyra_Core")
OLLAMA_DIR  = os.path.join(BASE, "Lyra_Ollama")
FRONTEND    = os.path.join(CORE, "Front_end_Lyra")
MEMORIA     = os.path.join(CORE, "Memoria_Lyra")
DB_CORTEX   = os.path.join(MEMORIA, "db_cortex")
QDRANT_DATA = os.path.join(BASE, "qdrant_data")
BIN_DIR     = os.path.join(BASE, "bin")

# ── Caminhos dos binários ─────────────────────────────────────────────────────
QDRANT_BIN  = os.environ.get("QDRANT_BIN",  os.path.join(BIN_DIR, "qdrant.exe"))
SURREAL_BIN = os.environ.get("SURREAL_BIN", "surreal")
OLLAMA_BIN  = os.environ.get("OLLAMA_BIN",  "ollama")

# ── Portas ────────────────────────────────────────────────────────────────────
SURREAL_PORT = 8090      # SurrealDB — NÃO usar 8000 (FastAPI)
QDRANT_PORT  = 6333
CEREBRO_PORT = 8000      # FastAPI (cerebro_maestro.py)

# ── Qdrant auto-download ─────────────────────────────────────────────────────
QDRANT_VERSION  = "v1.17.1"
QDRANT_ZIP_URL  = f"https://github.com/qdrant/qdrant/releases/download/{QDRANT_VERSION}/qdrant-x86_64-pc-windows-msvc.zip"

LOG_DIR = os.path.join(BASE, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(BIN_DIR, exist_ok=True)

# ── Processos ativos ──────────────────────────────────────────────────────────
_procs: list[subprocess.Popen] = []


def _log_file(name: str):
    return open(os.path.join(LOG_DIR, f"{name}.log"), "w", encoding="utf-8")


def _pipe(proc: subprocess.Popen, label: str):
    """Thread que imprime stdout/stderr com prefixo."""
    def _read(stream, prefix):
        if stream is None:
            return
        for line in stream:
            print(f"[{prefix}] {line.rstrip()}", flush=True)
    threading.Thread(target=_read, args=(proc.stdout, label), daemon=True).start()
    threading.Thread(target=_read, args=(proc.stderr, label + " ERR"), daemon=True).start()


def _wait_port(port: int, label: str, timeout: int = 30) -> bool:
    print(f"[LAUNCHER] Aguardando {label} em :{port}...", flush=True)
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                print(f"[LAUNCHER] {label} pronto ✓", flush=True)
                return True
        except OSError:
            time.sleep(0.5)
    print(f"[LAUNCHER] TIMEOUT aguardando {label}", flush=True)
    return False


def _port_in_use(port: int) -> bool:
    """Verifica se uma porta está em uso."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def _get_pid_on_port(port: int) -> int | None:
    """Retorna o PID do processo ouvindo na porta, ou None."""
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.strip().split()
                if parts:
                    try:
                        return int(parts[-1])
                    except ValueError:
                        pass
    except Exception:
        pass
    return None


def _start(cmd: list[str], label: str, cwd: str = None, env: dict = None) -> subprocess.Popen | None:
    combined_env = os.environ.copy()
    if env:
        combined_env.update(env)
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd or BASE,
            env=combined_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        _pipe(proc, label)
        _procs.append(proc)
        print(f"[LAUNCHER] {label} PID={proc.pid}", flush=True)
        return proc
    except FileNotFoundError:
        print(f"[LAUNCHER] ERRO: binário não encontrado → {cmd[0]}", flush=True)
        return None


def _shutdown(sig=None, frame=None):
    print("\n[LAUNCHER] Encerrando todos os serviços...", flush=True)
    for p in reversed(_procs):
        try:
            p.terminate()
            p.wait(timeout=5)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    print("[LAUNCHER] Finalizado.", flush=True)
    sys.exit(0)


# ── Helpers de pré-requisitos ─────────────────────────────────────────────────

def _is_admin() -> bool:
    """Verifica se o processo atual tem privilégios de administrador."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def _stop_surreal_service() -> bool:
    """
    Para o serviço Windows 'SurrealDB' (instalado via NSSM) que roda
    na porta 8000 default — conflitando com FastAPI.
    Retorna True se o serviço foi parado ou não existia.
    """
    # Verificar se o serviço existe
    try:
        result = subprocess.run(
            ["sc", "query", "SurrealDB"],
            capture_output=True, text=True, timeout=10
        )
        if "FAILED" in result.stdout or result.returncode != 0:
            # Serviço não existe — ok
            return True
        if "STOPPED" in result.stdout:
            print("[LAUNCHER] Serviço SurrealDB já parado ✓", flush=True)
            return True
    except Exception:
        return True  # Não tem sc ou serviço não existe

    print("[LAUNCHER] Serviço Windows 'SurrealDB' detectado na porta 8000 (conflita com FastAPI)", flush=True)
    print("[LAUNCHER] Tentando parar o serviço...", flush=True)

    # Tentar parar sem admin (pode funcionar dependendo das permissões)
    try:
        result = subprocess.run(
            ["sc", "stop", "SurrealDB"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0 or "STOP_PENDING" in result.stdout:
            print("[LAUNCHER] Serviço SurrealDB parando...", flush=True)
            # Esperar o serviço parar
            for _ in range(20):
                time.sleep(0.5)
                try:
                    chk = subprocess.run(
                        ["sc", "query", "SurrealDB"],
                        capture_output=True, text=True, timeout=5
                    )
                    if "STOPPED" in chk.stdout:
                        print("[LAUNCHER] Serviço SurrealDB parado ✓", flush=True)
                        # Desabilitar auto-start
                        subprocess.run(
                            ["sc", "config", "SurrealDB", "start=", "disabled"],
                            capture_output=True, timeout=5
                        )
                        return True
                except Exception:
                    pass
            # Timeout esperando parar
            print("[LAUNCHER] Timeout esperando serviço parar", flush=True)
            return False
    except Exception:
        pass

    # Se não conseguiu, pedir elevação
    if not _is_admin():
        print("[LAUNCHER] ⚠ Precisa de ADMIN para parar o serviço SurrealDB.", flush=True)
        print("[LAUNCHER] Solicitando elevação (UAC)...", flush=True)
        try:
            # Rodar sc stop via elevação
            result = subprocess.run(
                ["powershell", "-Command",
                 "Start-Process sc -ArgumentList 'stop SurrealDB' -Verb RunAs -Wait -WindowStyle Hidden;"
                 "Start-Process sc -ArgumentList 'config SurrealDB start= disabled' -Verb RunAs -Wait -WindowStyle Hidden"],
                capture_output=True, text=True, timeout=30
            )
            # Esperar a porta liberar
            for _ in range(20):
                if not _port_in_use(8000):
                    print("[LAUNCHER] Serviço SurrealDB parado ✓", flush=True)
                    return True
                time.sleep(0.5)
        except Exception as e:
            print(f"[LAUNCHER] Falha ao elevar: {e}", flush=True)

    # Último recurso: instruções manuais
    print("=" * 60, flush=True)
    print("  ⚠ NÃO FOI POSSÍVEL PARAR O SERVIÇO SurrealDB", flush=True)
    print("  Execute manualmente em um terminal ADMIN:", flush=True)
    print("    sc stop SurrealDB", flush=True)
    print("    sc config SurrealDB start= disabled", flush=True)
    print("=" * 60, flush=True)
    return False


def _cleanup_surreal_lock():
    """Remove LOCK stale do SurrealDB se nenhum processo surreal está rodando."""
    lock_file = os.path.join(DB_CORTEX, "LOCK")
    if not os.path.exists(lock_file):
        return

    # Verificar se algum surreal está rodando
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq surreal.exe", "/NH"],
            capture_output=True, text=True, timeout=5
        )
        if "surreal.exe" not in result.stdout:
            # Nenhum surreal rodando — remover LOCK stale
            try:
                os.remove(lock_file)
                print("[LAUNCHER] LOCK stale removido do SurrealDB ✓", flush=True)
            except PermissionError:
                print("[LAUNCHER] AVISO: Não foi possível remover LOCK (em uso)", flush=True)
    except Exception:
        pass


def _ensure_qdrant() -> bool:
    """
    Verifica se qdrant.exe existe. Se não, baixa automaticamente do GitHub.
    Retorna True se o binário está disponível.
    """
    if os.path.isfile(QDRANT_BIN):
        print(f"[LAUNCHER] Qdrant encontrado: {QDRANT_BIN} ✓", flush=True)
        return True

    print(f"[LAUNCHER] Qdrant não encontrado em '{QDRANT_BIN}'", flush=True)
    print(f"[LAUNCHER] Baixando Qdrant {QDRANT_VERSION} do GitHub...", flush=True)

    zip_path = os.path.join(BIN_DIR, "qdrant.zip")
    try:
        # Download com progresso simples
        def _progress(block, block_size, total):
            done = block * block_size
            if total > 0:
                pct = min(100, done * 100 // total)
                mb_done  = done / (1024 * 1024)
                mb_total = total / (1024 * 1024)
                print(f"\r[LAUNCHER] Download: {mb_done:.1f}/{mb_total:.1f} MB ({pct}%)", end="", flush=True)

        urlretrieve(QDRANT_ZIP_URL, zip_path, reporthook=_progress)
        print(flush=True)  # newline após progresso
        print("[LAUNCHER] Download completo. Extraindo...", flush=True)

        # Extrair
        with zipfile.ZipFile(zip_path, "r") as zf:
            # Procurar qdrant.exe dentro do zip
            qdrant_found = False
            for name in zf.namelist():
                if name.endswith("qdrant.exe"):
                    # Extrair direto para bin/qdrant.exe
                    with zf.open(name) as src, open(QDRANT_BIN, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    qdrant_found = True
                    break

            if not qdrant_found:
                # Extrair tudo e procurar
                zf.extractall(BIN_DIR)
                # Procurar qdrant.exe nos arquivos extraídos
                for root, dirs, files in os.walk(BIN_DIR):
                    for f in files:
                        if f == "qdrant.exe":
                            found = os.path.join(root, f)
                            if found != QDRANT_BIN:
                                shutil.move(found, QDRANT_BIN)
                            qdrant_found = True
                            break
                    if qdrant_found:
                        break

        # Limpar zip
        try:
            os.remove(zip_path)
        except Exception:
            pass

        if os.path.isfile(QDRANT_BIN):
            print(f"[LAUNCHER] Qdrant {QDRANT_VERSION} instalado em {QDRANT_BIN} ✓", flush=True)
            return True
        else:
            print("[LAUNCHER] ERRO: qdrant.exe não encontrado no ZIP", flush=True)
            return False

    except URLError as e:
        print(f"[LAUNCHER] ERRO ao baixar Qdrant: {e}", flush=True)
        print(f"[LAUNCHER] Baixe manualmente: {QDRANT_ZIP_URL}", flush=True)
        print(f"[LAUNCHER] Coloque qdrant.exe em: {BIN_DIR}", flush=True)
        # Limpar zip parcial
        try:
            os.remove(zip_path)
        except Exception:
            pass
        return False
    except Exception as e:
        print(f"[LAUNCHER] ERRO inesperado: {e}", flush=True)
        try:
            os.remove(zip_path)
        except Exception:
            pass
        return False


# ── Inicialização sequencial ──────────────────────────────────────────────────
def main():
    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    print("=" * 55, flush=True)
    print("  LYRA — IGNIÇÃO DO SISTEMA", flush=True)
    print("=" * 55, flush=True)

    # ── Pré-voo: Resolver conflitos ──────────────────────────────────────────

    # 0a. Parar serviço Windows do SurrealDB (porta 8000 conflita com FastAPI)
    if _port_in_use(CEREBRO_PORT):
        pid = _get_pid_on_port(CEREBRO_PORT)
        print(f"[LAUNCHER] ⚠ Porta {CEREBRO_PORT} ocupada (PID={pid})", flush=True)

        # Verificar se é o serviço SurrealDB
        svc_stopped = _stop_surreal_service()
        if not svc_stopped:
            # Verificar se a porta liberou mesmo assim
            time.sleep(2)
            if _port_in_use(CEREBRO_PORT):
                print(f"[LAUNCHER] ERRO FATAL: porta {CEREBRO_PORT} ainda ocupada.", flush=True)
                print(f"[LAUNCHER] FastAPI não conseguirá iniciar.", flush=True)
                print(f"[LAUNCHER] Resolva o conflito e tente novamente.", flush=True)
                sys.exit(1)

    # 0b. Limpar LOCK stale do SurrealDB
    _cleanup_surreal_lock()

    # 0c. Garantir Qdrant disponível
    qdrant_available = _ensure_qdrant()

    # ── 1. Qdrant ────────────────────────────────────────────────────────────
    qdrant_ok = False
    try:
        with socket.create_connection(("127.0.0.1", QDRANT_PORT), timeout=1):
            print("[LAUNCHER] Qdrant já rodando ✓", flush=True)
            qdrant_ok = True
    except OSError:
        if not qdrant_available:
            print("[LAUNCHER] ⚠ Qdrant não disponível — continuando sem ele", flush=True)
            print("[LAUNCHER]   (RAG não funcionará até Qdrant iniciar)", flush=True)
        else:
            # Qdrant v1.17+ usa variáveis de ambiente para configuração
            qdrant_env = {
                "QDRANT__STORAGE__STORAGE_PATH": QDRANT_DATA,
                "QDRANT__SERVICE__HTTP_PORT": str(QDRANT_PORT),
                # Sem HOST explícito o Qdrant sobe em 0.0.0.0 (exposto na LAN)
                "QDRANT__SERVICE__HOST": "127.0.0.1",
            }
            p = _start(
                [QDRANT_BIN],
                "QDRANT",
                cwd=BIN_DIR,
                env=qdrant_env,
            )
            if p:
                qdrant_ok = _wait_port(QDRANT_PORT, "Qdrant", timeout=30)

    # ── 2. SurrealDB ─────────────────────────────────────────────────────────
    # IMPORTANTE: porta 8090 (FastAPI usa 8000 — não conflitar)
    # Datastore: surrealkv:// apontando para db_cortex
    surreal_ok = False
    try:
        with socket.create_connection(("127.0.0.1", SURREAL_PORT), timeout=1):
            print("[LAUNCHER] SurrealDB já rodando ✓", flush=True)
            surreal_ok = True
    except OSError:
        p = _start(
            [
                SURREAL_BIN, "start",
                "--log", "warn",
                "--username", "root",
                "--password", "root",
                "--bind", f"127.0.0.1:{SURREAL_PORT}",
                f"surrealkv://{DB_CORTEX}",
            ],
            "SURREAL"
        )
        if p:
            surreal_ok = _wait_port(SURREAL_PORT, "SurrealDB", timeout=30)

    # ── 3. Ollama ─────────────────────────────────────────────────────────────
    ollama_ok = False
    try:
        with socket.create_connection(("127.0.0.1", 11434), timeout=1):
            print("[LAUNCHER] Ollama já rodando ✓", flush=True)
            ollama_ok = True
    except OSError:
        p = _start([OLLAMA_BIN, "serve"], "OLLAMA")
        if p:
            ollama_ok = _wait_port(11434, "Ollama", timeout=60)

    # ── 4. Cérebro Maestro (FastAPI :8000) ────────────────────────────────────
    _start(
        [PYTHON, "cerebro_maestro.py"],
        "CEREBRO",
        cwd=OLLAMA_DIR,
    )
    _wait_port(CEREBRO_PORT, "Cérebro", timeout=60)

    # ── 5. Mic Engine (thread separada — não bloqueia) ────────────────────────
    threading.Thread(
        target=lambda: subprocess.run(
            [PYTHON, "mic_engine.py"],
            cwd=CORE,
        ),
        daemon=True,
        name="mic_engine",
    ).start()
    print("[LAUNCHER] Mic Engine iniciado", flush=True)
    time.sleep(1)

    # ── Resumo da ignição ─────────────────────────────────────────────────────
    print("\n" + "=" * 55, flush=True)
    print("  LYRA — STATUS DA IGNIÇÃO", flush=True)
    print("-" * 55, flush=True)
    print(f"  Qdrant    :{QDRANT_PORT}  → {'✓ ONLINE' if qdrant_ok else '✗ OFFLINE'}", flush=True)
    print(f"  SurrealDB :{SURREAL_PORT}  → {'✓ ONLINE' if surreal_ok else '✗ OFFLINE'}", flush=True)
    print(f"  Ollama    :11434 → {'✓ ONLINE' if ollama_ok else '✗ OFFLINE'}", flush=True)
    print(f"  FastAPI   :{CEREBRO_PORT}  → aguardando...", flush=True)
    print("=" * 55, flush=True)
    print()

    # ── 6. Frontend — BLOQUEIA até a janela fechar ────────────────────────────
    print("[LAUNCHER] Abrindo frontend...", flush=True)
    try:
        frontend_proc = subprocess.run(
            [PYTHON, "lyra_app.py"],
            cwd=FRONTEND,
        )
    except KeyboardInterrupt:
        pass

    # Frontend fechou → encerrar tudo
    _shutdown()


if __name__ == "__main__":
    main()
