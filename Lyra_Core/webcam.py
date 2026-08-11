"""
webcam.py — Motor de Visão da Lyra
====================================
Ring 0: 100% offline. Zero cloud. Zero telemetria.

Capacidades:
  1. Detecção de presença via Haar Cascade (rosto) — OpenCV puro, sem GPU obrigatória
  2. Estimativa de distância pelo tamanho do rosto (calibração simples)
  3. Broadcast de estado para a UI via WebSocket ws://localhost:8765
  4. Frame de análise opcional via LLaVA (Ollama local) quando presença detectada

Fluxo:
  - Captura contínua da webcam (thread separada)
  - Análise a cada N frames para não sobrecarregar
  - broadcast("presence", intensity) quando rosto detectado
  - broadcast("idle") quando nenhuma presença
  - Se LLAVA_ENABLED=True: envia frame base64 ao Ollama para descrição semântica

Instalação:
    pip install opencv-python websockets httpx numpy
    (LLaVA opcional: ollama pull llava:7b)
"""

import asyncio
import base64
import json
import queue
import threading
import time
from typing import Optional

import cv2
import httpx
import numpy as np
import websockets

# ── Configurações ─────────────────────────────────────────────────────────────
CAMERA_INDEX        = 0            # índice da webcam (0 = padrão)
CAPTURE_WIDTH       = 640
CAPTURE_HEIGHT      = 480
ANALYZE_EVERY_N     = 5            # analisa 1 a cada N frames (reduz CPU)

# Haar Cascade — embarcado no OpenCV, sem download
CASCADE_FACE        = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
CASCADE_PROFILE     = cv2.data.haarcascades + "haarcascade_profileface.xml"
CASCADE_BODY        = cv2.data.haarcascades + "haarcascade_fullbody.xml"

# Calibração de distância (píxeis → cm, ajuste conforme sua câmera)
# Fórmula: distancia = (FACE_WIDTH_REF * FOCAL_LENGTH) / largura_px_detectada
FOCAL_LENGTH        = 600          # estimativa para webcam padrão
FACE_WIDTH_REF_CM   = 14           # largura média de um rosto adulto em cm

# Presença: intensidade = tamanho do rosto normalizado (0.0–1.0)
INTENSITY_SCALE     = 3.0          # amplifica sinal para a UI da esfera

# LLaVA — análise semântica opcional
LLAVA_ENABLED       = False        # mude para True se tiver llava:7b no Ollama
LLAVA_MODEL         = "llava:7b"
LLAVA_URL           = "http://127.0.0.1:11434/api/generate"
LLAVA_INTERVAL_SEC  = 10.0         # mínimo de segundos entre análises semânticas

WS_URL              = "ws://127.0.0.1:8765"  # 127.0.0.1: evita delay ~2s do IPv6 do localhost

# ── Estado global ─────────────────────────────────────────────────────────────
_frame_queue: queue.Queue = queue.Queue(maxsize=2)  # descarta frames antigos
_ws_connection: Optional[websockets.WebSocketClientProtocol] = None
_loop: Optional[asyncio.AbstractEventLoop] = None


# ── WebSocket: broadcast para a UI ───────────────────────────────────────────
async def _ws_connect():
    """Mantém conexão persistente ao servidor WS da Lyra."""
    global _ws_connection
    while True:
        try:
            async with websockets.connect(WS_URL) as ws:
                _ws_connection = ws
                print(f"[CAM] WebSocket conectado em {WS_URL}")
                await ws.wait_closed()
        except Exception as e:
            print(f"[CAM] WS desconectado ({e}), reconectando em 3s...")
        finally:
            _ws_connection = None
        await asyncio.sleep(3)


def broadcast(state: str, intensity: float = 0.0):
    """Thread-safe: envia estado de presença para a UI."""
    global _ws_connection, _loop
    if _ws_connection is None or _loop is None:
        return
    payload = json.dumps({"state": state, "intensity": round(float(intensity), 4)})

    async def _send():
        try:
            await _ws_connection.send(payload)
        except Exception:
            pass

    asyncio.run_coroutine_threadsafe(_send(), _loop)


# ── Thread de captura da câmera ───────────────────────────────────────────────
def _capture_thread():
    """Captura frames continuamente e coloca na fila."""
    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        print(f"[CAM][ERRO] Câmera {CAMERA_INDEX} não encontrada.")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, 30)
    print(f"[CAM] Câmera {CAMERA_INDEX} iniciada ({CAPTURE_WIDTH}x{CAPTURE_HEIGHT})")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("[CAM][WARN] Frame perdido, tentando novamente...")
            time.sleep(0.1)
            continue

        # Descarta frame antigo se a fila estiver cheia (mantém baixa latência)
        if _frame_queue.full():
            try:
                _frame_queue.get_nowait()
            except queue.Empty:
                pass

        _frame_queue.put(frame)

    cap.release()


# ── Detector de faces ─────────────────────────────────────────────────────────
class DetectorPresenca:
    def __init__(self):
        self.cascade_face = cv2.CascadeClassifier(CASCADE_FACE)
        self.cascade_profile = cv2.CascadeClassifier(CASCADE_PROFILE)
        self.cascade_body = cv2.CascadeClassifier(CASCADE_BODY)

        if self.cascade_face.empty():
            raise RuntimeError(f"[CAM][ERRO] Cascade não encontrado: {CASCADE_FACE}")

        print("[CAM] Detectores Haar carregados (face, perfil, corpo).")

    def detectar(self, frame: np.ndarray) -> dict:
        """
        Retorna dict com:
          - detected: bool
          - faces: list de (x, y, w, h)
          - distancia_cm: float (estimativa da face mais próxima)
          - intensity: float 0.0–1.0
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)  # melhora contraste para ambientes escuros

        # Detecção frontal
        faces = self.cascade_face.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(60, 60),
            flags=cv2.CASCADE_SCALE_IMAGE,
        )

        # Fallback: perfil (pessoa de lado)
        if len(faces) == 0:
            faces = self.cascade_profile.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=4, minSize=(50, 50)
            )

        if len(faces) == 0:
            return {"detected": False, "faces": [], "distancia_cm": None, "intensity": 0.0}

        # Pega a face maior (mais próxima)
        faces_list = list(faces)
        maior = max(faces_list, key=lambda f: f[2] * f[3])  # w*h
        _, _, w, _ = maior

        # Estimativa de distância
        distancia = (FACE_WIDTH_REF_CM * FOCAL_LENGTH) / w if w > 0 else 999

        # Intensidade: face maior = pessoa mais próxima = esfera mais intensa
        intensity = min(1.0, (w / CAPTURE_WIDTH) * INTENSITY_SCALE)

        return {
            "detected": True,
            "faces": faces_list,
            "distancia_cm": round(distancia, 1),
            "intensity": round(intensity, 4),
        }


# ── Análise semântica com LLaVA (opcional) ───────────────────────────────────
async def analisar_com_llava(frame: np.ndarray) -> str:
    """Envia frame para LLaVA e retorna descrição da cena."""
    _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
    img_b64 = base64.b64encode(buffer).decode("utf-8")

    prompt = (
        "Descreva brevemente o que você vê nesta imagem de câmera de segurança. "
        "Foque em: número de pessoas, postura, o que estão fazendo. "
        "Responda em português em no máximo 2 frases."
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                LLAVA_URL,
                json={
                    "model": LLAVA_MODEL,
                    "prompt": prompt,
                    "images": [img_b64],
                    "stream": False,
                },
            )
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
    except Exception as e:
        return f"[LLaVA indisponível: {e}]"


# ── Loop principal assíncrono ─────────────────────────────────────────────────
async def _main_loop():
    global _loop
    _loop = asyncio.get_running_loop()

    # WebSocket em background
    asyncio.create_task(_ws_connect())

    # Thread de captura em background
    t = threading.Thread(target=_capture_thread, daemon=True)
    t.start()

    detector = DetectorPresenca()

    frame_count = 0
    ultima_analise_llava = 0.0
    estado_anterior = "idle"

    print("[CAM] Monitoramento de presença ativo.")
    broadcast("idle")

    while True:
        # Pega frame da fila (não-bloqueante no loop async)
        try:
            frame = await asyncio.to_thread(_frame_queue.get, True, 1.0)
        except queue.Empty:
            continue

        frame_count += 1
        if frame_count % ANALYZE_EVERY_N != 0:
            continue

        # Detecção de presença
        resultado = await asyncio.to_thread(detector.detectar, frame)

        if resultado["detected"]:
            intensity = resultado["intensity"]
            dist = resultado["distancia_cm"]

            if estado_anterior != "presence":
                print(f"[CAM] Presença detectada! Distância: ~{dist}cm | Intensidade: {intensity:.2f}")
                estado_anterior = "presence"

            broadcast("presence", intensity)

            # Análise semântica periódica (se habilitada)
            if LLAVA_ENABLED:
                agora = time.time()
                if agora - ultima_analise_llava >= LLAVA_INTERVAL_SEC:
                    ultima_analise_llava = agora
                    descricao = await analisar_com_llava(frame)
                    print(f"[CAM][LLaVA] {descricao}")

        else:
            if estado_anterior != "idle":
                print("[CAM] Nenhuma presença detectada.")
                estado_anterior = "idle"

            broadcast("idle")

        # Pequena pausa para não saturar o loop
        await asyncio.sleep(0.01)


# ── Ponto de entrada ──────────────────────────────────────────────────────────
def main():
    try:
        asyncio.run(_main_loop())
    except KeyboardInterrupt:
        print("\n[CAM] Encerrado pelo usuário.")
        broadcast("idle")


if __name__ == "__main__":
    main()
