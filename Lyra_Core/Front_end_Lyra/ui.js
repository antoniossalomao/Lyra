/* ============================================================
   LYRA AI — ui.js | Shell de navegação: sidebar + views
   Carregado DEPOIS do script.js. Usa as globals dele
   (_chatOpen, _setChatBadge, abrirGrafo, _showToast...).
   ============================================================ */

const LyraUI = (() => {

    /* Views que são overlays próprios (chat e memória têm tratamento especial) */
    const VIEW_ELS = { config: 'view-config', integracoes: 'view-integracoes' };
    let _view = 'home';

    function showView(v) {
        if (v === 'memoria') {           // grafo já é um overlay fullscreen próprio
            abrirGrafo();
            return;
        }
        for (const id of Object.values(VIEW_ELS))
            document.getElementById(id)?.classList.remove('open');

        const chatAberto = (v === 'chat');
        _chatOpen = chatAberto;          // mantém a global do script.js coerente
        document.getElementById('chat-terminal')?.classList.toggle('open', chatAberto);
        if (chatAberto) {
            _setChatBadge(false);
            setTimeout(() => document.getElementById('lyra-input')?.focus(), 240);
        }
        if (VIEW_ELS[v]) document.getElementById(VIEW_ELS[v])?.classList.add('open');

        _view = v;
        document.body.dataset.view = v;
        _syncNav(v);
    }

    function _syncNav(v) {
        document.querySelectorAll('.sb-item').forEach(el =>
            el.classList.toggle('active', el.dataset.view === v));
    }

    /* Esc: fecha a view atual e volta pra home. Retorna true se consumiu. */
    function escapeView() {
        if (_view !== 'home') { showView('home'); return true; }
        return false;
    }

    function currentView() { return _view; }

    /* Toast com auto-hide (o _showToast do script.js é persistente,
       feito pro aviso de conexão perdida) */
    function _toast(msg) {
        _showToast(msg);
        setTimeout(_hideToast, 3200);
    }

    /* ── Dropdown de modelo customizado — espelha o <select id="sel-modelo">
       real (escondido via .sr-only), que é o que script.js/_enviarComando
       de fato lê. Clicar numa opção seta select.value e dispara 'change'
       pra reaproveitar o listener de persistência em localStorage já
       existente em _setupPanel() (script.js). */
    function _setupModeloSelect() {
        const select = document.getElementById('sel-modelo');
        const wrap   = document.getElementById('sb-select-modelo');
        const btn    = document.getElementById('sb-select-btn');
        const label  = document.getElementById('sb-select-label');
        const list   = document.getElementById('sb-select-list');
        if (!select || !wrap || !btn || !label || !list) return;

        const opts = [...list.querySelectorAll('.sb-select-opt')];

        const sync = () => {
            const opt = opts.find(o => o.dataset.value === select.value) || opts[0];
            label.textContent = opt.textContent;
            opts.forEach(o => o.classList.toggle('selected', o === opt));
        };
        sync();   // reflete o valor já restaurado do localStorage por script.js

        const close = () => wrap.classList.remove('open');
        btn.addEventListener('click', e => {
            e.stopPropagation();
            wrap.classList.toggle('open');
        });
        opts.forEach(o => o.addEventListener('click', () => {
            select.value = o.dataset.value;
            select.dispatchEvent(new Event('change'));
            sync();
            close();
        }));
        document.addEventListener('click', e => { if (!wrap.contains(e.target)) close(); });
        document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
    }

    /* ── Sessões de conversa (backend: /sessoes no cerebro_maestro) ── */

    async function novaConversa() {
        try {
            const res = await fetch('http://127.0.0.1:8000/sessoes', { method: 'POST' });
            const d   = await res.json();
            if (d.erro) { _toast(d.erro); return; }
            _limparChatDOM();
            showView('chat');
            _carregarSessoes();
        } catch (_) {
            _toast('Backend fora do ar — não deu pra criar sessão.');
            showView('chat');   // chat contínuo segue funcionando mesmo assim
        }
    }

    async function abrirSessao(sid, somenteLeitura) {
        try {
            let msgs;
            if (somenteLeitura) {
                const res = await fetch(`http://127.0.0.1:8000/historico?sessao=${encodeURIComponent(sid)}`);
                msgs = (await res.json()).mensagens || [];
            } else {
                const res = await fetch('http://127.0.0.1:8000/sessoes/ativar', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ sessao_id: sid }),
                });
                const d = await res.json();
                if (d.erro) { _toast(d.erro); return; }
                msgs = d.mensagens || [];
            }
            _limparChatDOM();
            _renderHistorico(msgs);
            showView('chat');
            _carregarSessoes();
            if (somenteLeitura) _toast('Sessão antiga — somente leitura.');
        } catch (e) {
            _toast('Falha ao abrir conversa: ' + e.message);
        }
    }

    function _limparChatDOM() {
        const c = document.getElementById('chat-messages');
        if (c) c.innerHTML = '';
        // reseta o estado de streaming do script.js pra próxima resposta
        // não tentar continuar numa bolha que não existe mais
        _currentLyraMsgEl  = null;
        _pendingNewLyraMsg = true;
    }

    /* Reconstrói as bolhas com o MESMO DOM do _showBubble (script.js),
       mas sem animação de digitação — é histórico, não streaming. */
    function _renderHistorico(msgs) {
        const container = document.getElementById('chat-messages');
        if (!container) return;
        for (const m of msgs.slice(-60)) {
            if (m.role === 'user') {
                const el = document.createElement('div');
                el.className = 'msg msg-user visible';
                const t = document.createElement('span');
                t.className = 'msg-text';
                t.textContent = m.content;
                el.appendChild(t);
                container.appendChild(el);
            } else {
                const row = document.createElement('div');
                row.className = 'msg-lyra-row';
                const avatar = document.createElement('div');
                avatar.className = 'chat-avatar';
                const col = document.createElement('div');
                col.className = 'msg-lyra-col';
                const bubble = document.createElement('div');
                bubble.className = 'msg msg-lyra visible';
                const t = document.createElement('span');
                t.className = 'msg-text';
                t.innerHTML = _renderMarkdown(m.content);
                bubble.appendChild(t);
                col.appendChild(bubble);
                if (m.timestamp) {
                    const time = document.createElement('div');
                    time.className = 'msg-time';
                    time.textContent = new Date(m.timestamp).toLocaleString('pt-BR',
                        { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
                    col.appendChild(time);
                }
                row.appendChild(avatar);
                row.appendChild(col);
                container.appendChild(row);
            }
        }
        _scrollChat(true);
    }

    async function _carregarSessoes() {
        const lista = document.getElementById('sb-convs-list');
        if (!lista) return;
        try {
            const res = await fetch('http://127.0.0.1:8000/sessoes');
            const d   = await res.json();
            const sessoes = d.sessoes || [];
            lista.innerHTML = '';
            if (!sessoes.length) {
                lista.innerHTML = '<div class="sb-convs-hint">nenhuma conversa ainda</div>';
                return;
            }
            for (const s of sessoes) {
                const btn = document.createElement('button');
                btn.className = 'sb-conv' + (s.ativa ? ' active' : '');
                const quando = s.criada
                    ? new Date(s.criada).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })
                    : '';
                btn.innerHTML =
                    `<span class="sb-conv-title"></span><span class="sb-conv-when">${quando}</span>`;
                btn.querySelector('.sb-conv-title').textContent = s.titulo;
                btn.dataset.tip = s.titulo;
                if (!s.ativa) btn.addEventListener('click', () => abrirSessao(s.sessao_id, !!s.somente_leitura));
                else btn.addEventListener('click', () => showView('chat'));
                lista.appendChild(btn);
            }
        } catch (_) {
            lista.innerHTML = '<div class="sb-convs-hint">backend offline</div>';
        }
    }

    /* ── Configurações: toggles ──────────────────────────────── */
    function _setupConfig() {
        // TTS — espelha o botão de mudo dos window-controls (mesma persistência)
        const tts = document.getElementById('cfg-tts');
        const syncTts = () => { if (tts) tts.checked = localStorage.getItem('lyra_tts_mudo') !== '1'; };
        syncTts();
        tts?.addEventListener('change', () => { toggleTtsMute(); syncTts(); });
        document.getElementById('btn-mute')?.addEventListener('click', () => setTimeout(syncTts, 60));

        // Grain de fundo — só estética, persiste local
        const grain   = document.getElementById('cfg-grain');
        const grainEl = document.getElementById('grain');
        const applyGrain = () => {
            const off = localStorage.getItem('lyra_grain_off') === '1';
            if (grainEl) grainEl.style.display = off ? 'none' : '';
            if (grain) grain.checked = !off;
        };
        applyGrain();
        grain?.addEventListener('change', () => {
            localStorage.setItem('lyra_grain_off', grain.checked ? '0' : '1');
            applyGrain();
        });
    }

    /* ── Integrações: cards (status real chega via /integracoes) ── */
    const INTEGRACOES = [
        { id: 'telegram', nome: 'Telegram',            desc: 'Ponte de mensagens remota — fale com a Lyra de qualquer lugar.' },
        { id: 'voz_live', nome: 'Voz live (Gemini)',   desc: 'Conversa de voz bidirecional em tempo real via /ws/voice.' },
        { id: 'mic',      nome: 'Mic wake-word',       desc: 'Escuta local contínua via mic_engine.py.' },
        { id: 'tts',      nome: 'Resposta por voz',    desc: 'Síntese de fala das respostas (TTS).' },
        { id: 'enxame',   nome: 'Enxame de agentes',   desc: 'Sub-agentes paralelos para tarefas grandes.' },
        { id: 'upload',   nome: 'Upload de mídia',     desc: 'Imagem, áudio e vídeo direto no chat.' },
    ];

    function _renderIntegracoes() {
        const grid = document.getElementById('integr-grid');
        if (!grid) return;
        grid.innerHTML = '';
        for (const it of INTEGRACOES) {
            const card = document.createElement('div');
            card.className = 'cfg-card integr-card';
            card.innerHTML =
                `<div class="integr-head">` +
                    `<span class="p-dot" id="integr-dot-${it.id}"></span>` +
                    `<span class="integr-nome">${it.nome}</span>` +
                `</div>` +
                `<div class="integr-desc">${it.desc}</div>` +
                `<div class="integr-status" id="integr-st-${it.id}">—</div>`;
            grid.appendChild(card);
        }
    }

    async function _pollIntegracoes() {
        try {
            const res = await fetch('http://127.0.0.1:8000/integracoes');
            if (!res.ok) return;
            const d = await res.json();
            for (const it of INTEGRACOES) {
                const info = d[it.id];
                if (!info) continue;
                const dot = document.getElementById(`integr-dot-${it.id}`);
                const st  = document.getElementById(`integr-st-${it.id}`);
                const col = info.online ? '#00FF99' : 'rgba(255,255,255,0.18)';
                if (dot) { dot.style.background = col; dot.style.boxShadow = info.online ? `0 0 5px ${col}` : 'none'; }
                if (st)  st.textContent = info.status || (info.online ? 'ativa' : 'inativa');
            }
        } catch (_) { /* backend fora — cards ficam neutros */ }
    }

    /* ── Boot do shell ───────────────────────────────────────── */
    function init() {
        document.body.dataset.view = 'home';
        // Sidebar lembra se estava recolhida
        if (localStorage.getItem('lyra_sb_collapsed') === '1')
            document.body.classList.add('sb-collapsed');
        _setupConfig();
        _setupModeloSelect();
        _renderIntegracoes();
        _pollIntegracoes();
        setInterval(_pollIntegracoes, 12000);
        _carregarSessoes();
        setInterval(_carregarSessoes, 20000);  // pega título automático da 1ª msg
    }

    document.addEventListener('DOMContentLoaded', init);
    if (document.readyState !== 'loading') init();

    return { showView, escapeView, currentView, novaConversa };
})();
