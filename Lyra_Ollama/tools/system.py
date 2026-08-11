"""tools/system.py — System health tools: CPU/RAM/GPU telemetry and Lyra service status checks."""

def checar_saude_sistema() -> dict:
    """Retorna telemetria básica do sistema (CPU, RAM, GPU)."""
    try:
        import psutil
        import GPUtil
        
        cpu_pct = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory()
        
        gpu_info = []
        gpus = GPUtil.getGPUs()
        for g in gpus:
            gpu_info.append({
                "nome": g.name,
                "carga_pct": round(g.load * 100, 1),
                "mem_livre_mb": g.memoryFree,
                "mem_usada_mb": g.memoryUsed,
                "mem_total_mb": g.memoryTotal,
                "temp_c": g.temperature
            })
            
        return {
            "ok": True,
            "cpu_percentual": cpu_pct,
            "ram_livre_gb": round(ram.available / (1024**3), 1),
            "ram_total_gb": round(ram.total / (1024**3), 1),
            "ram_percentual": ram.percent,
            "gpus": gpu_info
        }
    except Exception as e:
        return {"erro": str(e), "ok": False}

def checar_servicos_lyra() -> dict:
    """
    Verifica se todos os serviços críticos da Lyra estão online:
    SurrealDB, Qdrant, embed_service, Ollama e FastAPI.
    Retorna status de cada um.
    """
    try:
        import lyra_seguranca
        return lyra_seguranca.checar_servicos()
    except Exception as e:
        return {"ok": False, "erro": str(e)}


SCHEMA = [
        {
            "type": "function",
            "function": {
                "name": "checar_saude_sistema",
                "description": "Uso de CPU/RAM/GPU.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "checar_servicos_lyra",
                "description": "Verifica se os serviços críticos da Lyra estão online (SurrealDB, Qdrant, embed_service, Ollama, FastAPI). Use quando o usuário perguntar sobre o status do sistema ou quando algo não estiver funcionando.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
]


MAP = {
    "checar_saude_sistema": checar_saude_sistema,
    "checar_servicos_lyra": checar_servicos_lyra,
}
