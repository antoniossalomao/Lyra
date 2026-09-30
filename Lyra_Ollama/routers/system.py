"""
routers/system.py — Endpoints de status/telemetria/saúde do sistema.

Extraído de cerebro_maestro.py na reorganização OOP (Lyra 2.0, ver
LYRA_NUCLEO.md §5.3). Comportamento idêntico ao original —
só move código de lugar, não muda lógica nenhuma.
"""
import asyncio
import time

import psutil
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

import config as cfg


class SystemRouter:
    """Agrupa os endpoints de status/saúde/telemetria do cérebro.

    Recebe as dependências (estado compartilhado do cerebro_maestro) via
    construtor em vez de importar globals de outro módulo — qualquer
    programador que ler esta classe vê exatamente do que ela depende.
    Getters (get_cerebro_ativo, get_tts_mudo, ...) existem porque o valor
    real muda em runtime em cerebro_maestro.py (reassign de global lá);
    passar o valor direto aqui congelaria no valor do momento da instanciação.
    """

    def __init__(self, *, rag, get_cerebro_ativo, get_tts_mudo, get_carga_cognitiva,
                 telemetria, ler_telemetria_historico, get_ultima_latencia_ms,
                 embed_service_ok, colecao, http_health_client,
                 dashboard_html_path, processo_rodando, get_voice_live_ativas):
        self._rag = rag
        self._get_cerebro_ativo = get_cerebro_ativo
        self._get_tts_mudo = get_tts_mudo
        self._get_carga_cognitiva = get_carga_cognitiva
        self._telemetria = telemetria
        self._ler_telemetria_historico = ler_telemetria_historico
        self._get_ultima_latencia_ms = get_ultima_latencia_ms
        self._embed_service_ok = embed_service_ok
        self._colecao = colecao
        self._http = http_health_client
        self._dashboard_html_path = dashboard_html_path
        self._processo_rodando = processo_rodando
        self._get_voice_live_ativas = get_voice_live_ativas

        self._gpu_cache: dict = {}
        self._gpu_cache_ts: float = 0.0

        self.router = APIRouter()
        self.router.add_api_route("/", self.raiz, methods=["GET"])
        self.router.add_api_route("/dashboard", self.dashboard, methods=["GET"])
        self.router.add_api_route("/status", self.status, methods=["GET"])
        self.router.add_api_route("/stats", self.stats, methods=["GET"])
        self.router.add_api_route("/stats/historico", self.stats_historico, methods=["GET"])
        self.router.add_api_route("/health", self.health, methods=["GET"])
        self.router.add_api_route("/metrics", self.metrics, methods=["GET"])
        self.router.add_api_route("/integracoes", self.integracoes, methods=["GET"])

    def raiz(self):
        """Ping simples — usado pelo frontend pra checar se o cérebro responde."""
        return {"servico": "Lyra cerebro_maestro", "ativo": self._get_cerebro_ativo(), "versao": "2.1"}

    def dashboard(self):
        """Dashboard de monitoramento standalone (http://localhost:8000/dashboard)."""
        try:
            with open(self._dashboard_html_path, "r", encoding="utf-8") as f:
                return HTMLResponse(f.read())
        except Exception as e:
            return HTMLResponse(f"<h1>Dashboard indisponível</h1><p>{e}</p>", status_code=500)

    def status(self):
        return {"cerebro_ativo": self._get_cerebro_ativo(),
                "qdrant": self._rag.active,
                "embedder": self._embed_service_ok(),
                "tts_mudo": self._get_tts_mudo(),
                "carga_cognitiva": self._get_carga_cognitiva()}

    def stats(self):
        """Telemetria da cascata: distribuição de uso, latência média e taxa de falha por andar."""
        tiers_out = {}
        for nome, t in self._telemetria["tiers"].items():
            usos = t.get("usos", 0)
            falhas = t.get("falhas", 0)
            lat_total = t.get("latencia_total_ms", 0)
            total_tentativas = usos + falhas
            tiers_out[nome] = {
                "usos": usos, "falhas": falhas,
                "latencia_media_ms": round(lat_total / usos) if usos else None,
                "taxa_sucesso": round(usos / total_tentativas * 100, 1) if total_tentativas else None,
            }
        total = self._telemetria.get("total_chats", 0)
        return {
            "total_chats": total,
            "iniciado_em": self._telemetria.get("iniciado_em"),
            "tiers": tiers_out,
            "distribuicao_pct": {
                nome: round(t["usos"] / total * 100, 1) if total else 0
                for nome, t in self._telemetria["tiers"].items()
            },
        }

    def stats_historico(self, limite: int = 200):
        """Série temporal de telemetria (snapshots a cada ~5min pelo loop proativo)."""
        return {"snapshots": self._ler_telemetria_historico(limite)}

    async def health(self):
        """Health check completo com latência real de todos os serviços."""
        async def _ping(url: str, timeout: float = 3.0):
            t0 = time.monotonic()
            try:
                await self._http.get(url, timeout=timeout)
                return True, round((time.monotonic() - t0) * 1000, 1)
            except Exception:
                return False, None

        async def _ping_post(url: str, data: str, headers: dict, auth, timeout=3.0):
            t0 = time.monotonic()
            try:
                await self._http.post(url, data=data, headers=headers, auth=auth, timeout=timeout)
                return True, round((time.monotonic() - t0) * 1000, 1)
            except Exception:
                return False, None

        qdrant_ok, qdrant_ms   = await _ping(f"{cfg.QDRANT_URL}/healthz")
        surreal_ok, surreal_ms = await _ping_post(cfg.SURREAL_URL, "RETURN 1", cfg.SURREAL_HEADERS, cfg.SURREAL_AUTH)
        ollama_ok, ollama_ms   = await _ping(f"{cfg.OLLAMA_URL}/api/tags")

        vram_info = {}
        try:
            proc = await asyncio.create_subprocess_exec(
                "nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            saida, _ = await asyncio.wait_for(proc.communicate(), timeout=3)
            partes = saida.decode().strip().split(",")
            if len(partes) == 3:
                vram_info = {"usada_mb": int(partes[0].strip()), "total_mb": int(partes[1].strip()),
                             "gpu_pct": int(partes[2].strip())}
        except Exception:
            pass

        qdrant_vetores = {}
        if self._rag.active:
            try:
                qdrant_vetores[self._colecao] = self._rag.qdrant_client.count(self._colecao).count
            except Exception:
                qdrant_vetores[self._colecao] = None

        return {
            "cerebro":  {"ok": self._get_cerebro_ativo(), "embedder": self._embed_service_ok(),
                        "bm25": self._rag.bm25_index is not None},
            "qdrant":   {"ok": qdrant_ok, "latencia_ms": qdrant_ms, "vetores": qdrant_vetores},
            "surreal":  {"ok": surreal_ok, "latencia_ms": surreal_ms},
            "ollama":   {"ok": ollama_ok, "latencia_ms": ollama_ms},
            "vram":     vram_info,
            "latencia_ultimo_chat_ms": self._get_ultima_latencia_ms(),
        }

    async def metrics(self):
        dados = {
            "latencia_ms": self._get_ultima_latencia_ms(),
            "cpu_pct":     psutil.cpu_percent(interval=None),
            "ram_pct":     psutil.virtual_memory().percent,
            "gpu_pct":     None,
            "vram_pct":    None,
        }
        # GPU via nvidia-smi com cache de 4s — evita 1 subprocesso por poll do frontend
        agora_t = time.monotonic()
        if agora_t - self._gpu_cache_ts > 4:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                )
                saida, _ = await asyncio.wait_for(proc.communicate(), timeout=2)
                parts = saida.decode().strip().split(",")
                if len(parts) == 3:
                    self._gpu_cache = {"gpu_pct": int(parts[0].strip()),
                                       "vram_pct": round(int(parts[1].strip()) / int(parts[2].strip()) * 100)}
                    self._gpu_cache_ts = agora_t
            except Exception:
                pass
        dados.update(self._gpu_cache)
        return dados

    async def integracoes(self):
        """Agrega o status das integrações num payload único pra view de
        integrações do frontend. Chaves casam com os ids dos cards no ui.js."""
        telegram_on = await asyncio.to_thread(self._processo_rodando, "lyra_telegram")
        mic_on      = await asyncio.to_thread(self._processo_rodando, "mic_engine")
        voice_live_ativas = self._get_voice_live_ativas()
        tts_mudo = self._get_tts_mudo()
        return {
            "telegram": {"online": telegram_on, "status": "bot rodando" if telegram_on else "processo parado"},
            "voz_live": {"online": voice_live_ativas > 0,
                        "status": f"{voice_live_ativas} sessão(ões) ativa(s)" if voice_live_ativas
                                  else "pronta — clique no botão de voz live"},
            "mic":      {"online": mic_on, "status": "escutando wake-word" if mic_on else "mic_engine.py parado"},
            "tts":      {"online": not tts_mudo, "status": "mudo" if tts_mudo else "respondendo por voz"},
            "enxame":   {"online": True, "status": "disponível via /enxame"},
            "upload":   {"online": True, "status": "imagem · áudio · vídeo"},
        }
