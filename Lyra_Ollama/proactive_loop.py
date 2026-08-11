"""proactive_loop.py — background maintenance coroutine for cerebro_maestro.

Extracted from the monolithic loop_proativo() (156 lines) so each sub-task is
individually testable. Runs as an asyncio task created in the FastAPI startup
hook, waking every 60 s.
"""

import asyncio
import json
from typing import Awaitable, Callable

import lyra_tools
import lyra_seguranca
import lyra_agentes as _agentes


class ProactiveLoop:
    """Periodic maintenance: reminders, schedules, bg-process/swarm completion
    notices, telemetry snapshots, Shadow Thoughts, DB reconciliation, VRAM
    watching and service self-healing.

    Cerebro-specific side effects (telemetry files, cognitive-load state, GPU
    watcher) are injected as callables so this class has no reverse import.

    Args:
        log: diagnostics callable.
        snapshot_telemetry: sync fn appending a telemetry-history snapshot.
        update_cognitive_load: sync fn reclassifying the cognitive load tier.
        check_vram: async fn that unloads models when another app hogs VRAM.
    """

    def __init__(self, log: Callable,
                 snapshot_telemetry: Callable,
                 update_cognitive_load: Callable,
                 check_vram: Callable[[], Awaitable[None]]):
        self._log = log
        self._snapshot_telemetry = snapshot_telemetry
        self._update_cognitive_load = update_cognitive_load
        self._check_vram = check_vram
        self._iterations = 0

    async def run(self) -> None:
        """Entry point — loops forever until the task is cancelled."""
        await asyncio.sleep(10)  # dá tempo do _init() terminar
        while True:
            try:
                self._iterations += 1
                # loop roda a cada 60s — snapshot/carga a cada ~5min
                if self._iterations % 5 == 0:
                    self._snapshot_telemetry()
                    self._update_cognitive_load()
                if self._iterations % 180 == 0:   # Shadow Thoughts a cada ~3h
                    self._schedule_shadow_thoughts()
                if self._iterations % 60 == 0:    # reconciliação a cada ~1h
                    self._schedule_reconciliation()

                await self._check_vram()
                self._check_reminders()
                self._check_numbers()
                self._check_schedules()
                self._check_bg_processes()
                await self._check_swarms()
                if self._iterations % 5 == 0:
                    await self._self_healing()
            except Exception as e:
                self._log(f"[LOOP PROATIVO] erro: {e}")
            await asyncio.sleep(60)

    # ── Sub-tasks ────────────────────────────────────────────────────────────

    def _schedule_shadow_thoughts(self) -> None:
        """Ciclo de sono (NREM/REM/DEEP) em background — não bloqueia o loop."""
        try:
            import lyra_shadow_thoughts as _st
            asyncio.create_task(_st.ciclo_completo(["nrem", "rem", "deep"]))
            self._log("[LOOP PROATIVO] Shadow Thoughts agendado (ciclo a cada 3h).")
        except Exception as e:
            self._log(f"[LOOP PROATIVO] Shadow Thoughts erro: {e}")

    def _schedule_reconciliation(self) -> None:
        """Reconciliação SurrealDB↔Qdrant: registrar_evento grava nos dois
        bancos sem atomicidade — restart no meio deixa órfão sem vetor
        (gap real medido: 14 órfãos em 01/07/2026)."""
        try:
            async def _bg():
                import reconciliar_episodios as _rec
                r = await _rec.reconciliar(dry_run=False, auto_fix=True, silencioso=True)
                if r["orfaos_encontrados"] > 0:
                    self._log(f"[LOOP PROATIVO] Reconciliação SurrealDB↔Qdrant: "
                              f"{r['reconciliados']}/{r['orfaos_encontrados']} órfãos corrigidos "
                              f"(de {r['eventos_verificados']} eventos verificados).")
            asyncio.create_task(_bg())
        except Exception as e:
            self._log(f"[LOOP PROATIVO] Reconciliação erro: {e}")

    def _check_reminders(self) -> None:
        """Dispara notificação pra lembretes vencidos e os conclui."""
        pendentes = lyra_tools.gerenciar_lembretes(acao="pendentes")
        for l in pendentes.get("lembretes", []):
            lyra_tools.notificar_usuario(
                titulo=f"Lembrete: {l.get('titulo', '')}",
                mensagem=l.get("nota") or "Sem nota adicional.",
                urgencia="alta",
            )
            rid = l.get("id")
            if rid:
                lyra_tools.gerenciar_lembretes(acao="concluir", lembrete_id=str(rid))

    def _check_numbers(self) -> None:
        """Sistema de Números: notifica observações acima do limiar de score."""
        numeros = lyra_tools.listar_numeros(somente_pendentes=True, limite_score=0.7)
        for n in numeros.get("numeros", []):
            lyra_tools.notificar_usuario(
                titulo=f"Número: {n.get('alvo', '')}",
                mensagem=f"{n.get('motivo', '')} (score {n.get('score')})",
                urgencia="alta",
            )
            nid = n.get("id")
            if nid:
                lyra_tools._marcar_numero_notificado(str(nid))

    def _check_schedules(self) -> None:
        """Executa agendamentos vencidos (cron interno) e notifica o resultado."""
        disparados = lyra_tools._processar_agendamentos_devidos()
        for d in disparados:
            ag = d["agendamento"]
            msg = f"Agendamento '{ag.get('titulo', '')}' disparou."
            if d["resultado_ferramenta"] is not None:
                msg += f" Resultado: {json.dumps(d['resultado_ferramenta'], ensure_ascii=False)[:200]}"
            lyra_tools.notificar_usuario(titulo="Agendamento", mensagem=msg, urgencia="normal")

    def _check_bg_processes(self) -> None:
        """Notifica processos em background que terminaram."""
        concluidos = lyra_tools._checar_processos_bg_concluidos()
        for p in concluidos:
            lyra_tools.notificar_usuario(
                titulo=f"Processo concluído: {p.get('nome', '')}",
                mensagem=p.get("log_tail", "")[:200] or "Sem saída no log.",
                urgencia="normal",
            )

    async def _check_swarms(self) -> None:
        """Detecta enxames recém-concluídos e notifica (marca com resumo='')."""
        try:
            # SurrealDB: campo null usa IS NONE, não = NONE
            enxames = await _agentes._sq(
                "SELECT id, objetivo, status FROM enxame "
                "WHERE status != 'rodando' AND resumo_final IS NONE;")
            for enx in enxames:
                eid = str(enx.get("id", "")).split(":")[-1].strip("`").strip()
                if not eid:
                    continue
                lyra_tools.notificar_usuario(
                    titulo="Enxame concluído",
                    mensagem=f"{enx.get('objetivo', '')[:120]} — chame consolidar_enxame('{eid}')",
                    urgencia="normal",
                )
                # resumo_final = '' ≠ NONE → não notifica de novo
                await _agentes._sx(f"UPDATE enxame:`{eid}` SET resumo_final = '';")
        except Exception as e:
            self._log(f"[LOOP PROATIVO] enxame check erro: {e}")

    async def _self_healing(self) -> None:
        """Reinicia serviços críticos que caíram (via start_*.bat canônicos)."""
        try:
            # to_thread é obrigatório: checar_servicos usa requests SÍNCRONO e
            # inclui o próprio :8000 — direto no event loop, ele se bloqueava
            # e "detectava" FastAPI offline em falso (achado real 03/08/2026).
            status = await asyncio.to_thread(lyra_seguranca.checar_servicos)
            for nome_svc, info in status.get("servicos", {}).items():
                # FastAPI somos nós — se este código roda, o processo está vivo.
                if nome_svc == "FastAPI":
                    continue
                if not info.get("ok"):
                    self._log(f"[SELF-HEALING] {nome_svc} offline — tentando reiniciar...")
                    resultado = await asyncio.to_thread(
                        lyra_seguranca.tentar_reiniciar_servico, nome_svc)
                    if resultado.get("ok"):
                        self._log(f"[SELF-HEALING] {nome_svc} reiniciado com sucesso.")
                        lyra_tools.notificar_usuario(
                            titulo=f"Lyra Self-Healing: {nome_svc}",
                            mensagem=f"{nome_svc} havia caído e foi reiniciado automaticamente.",
                            urgencia="normal",
                        )
                    else:
                        self._log(f"[SELF-HEALING] {nome_svc} falhou ao reiniciar: "
                                  f"{resultado.get('erro')}")
                        lyra_tools.notificar_usuario(
                            titulo=f"⚠ Serviço offline: {nome_svc}",
                            mensagem=f"{nome_svc} está offline e não conseguiu reiniciar automaticamente.",
                            urgencia="alta",
                        )
        except Exception as e:
            self._log(f"[SELF-HEALING] erro na verificação: {e}")
