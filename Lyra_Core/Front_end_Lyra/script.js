/* ==========================================================================
   LYRA AI — NUCLEUS v6  |  Particle Sphere
   Three.js r128 · WS-driven · pywebview desktop
   ==========================================================================
   Partículas aleatórias distribuídas na superfície de uma esfera.
   3 camadas: grandes/brilhantes · médias · pequenas/dim.
   Toda a lógica de WS, chat, painel e input preservada.
   ========================================================================== */

const PI = Math.PI;

/* --------------------------------------------------------------------------
   CONFIGURAÇÃO DA ESFERA DE PARTÍCULAS
   -------------------------------------------------------------------------- */
const SPHERE_R  = 25;   // raio base

// [count, size, color, baseOpacity, radiusJitter]
// jitter baixo = partículas coladas na superfície (esfera visível)
const LAYERS = [
    { n: 60,  size: 2.00, color: 0xCCEEFF, op: 0.90, jitter: 0.025 }, // grandes/brilhantes
    { n: 240, size: 1.15, color: 0x00CCFF, op: 0.60, jitter: 0.035 }, // médias
    { n: 300, size: 0.65, color: 0x0066CC, op: 0.35, jitter: 0.045 }, // pequenas/dim
];


/* --------------------------------------------------------------------------
   ESTADO GLOBAL
   -------------------------------------------------------------------------- */
let scene, camera, renderer, nucleus, glow;
let particleLayers = [];   // [{pts, mat, baseOp, phase}]
let nebulas = [];          // [{spr, mat, baseOp, baseX, baseY, phase}]
let curState   = 'idle';
let audioInten = 0.0;
let smoothA    = 0.0;
let curScale   = 0.001;  // núcleo nasce colapsado — brota durante o boot
let bootFlashT = 1.0;    // 0 = flash no pico, 1 = encerrado
let sweepAngle = 0;      // ângulo da varredura do estado "processando"

// Lavagem de cor sutil por estado — a esfera muda de "humor" sem precisar
// de shader: cada camada interpola lentamente sua cor base em direção a
// esta cor-alvo (ou de volta à base, se for null).
const STATE_TINT = {
    idle:       null,
    listening:  new THREE.Color(0x00FF99),
    processing: new THREE.Color(0xFFAA33),
    speaking:   new THREE.Color(0xBB44FF),
};

let _lyraFull          = '';
let _hideTimer         = null;
let _currentLyraMsgEl  = null;
let _pendingNewLyraMsg = true;
// Histórico de mensagens enviadas — ↑/↓ navegam (estilo terminal), até 50.
// _histIdx === _histInput.length significa "fora do histórico" (digitando novo).
const _HIST_INPUT_MAX = 50;
let _histInput = [];
let _histIdx   = 0;
let _histDraft = '';           // rascunho preservado ao entrar no histórico
const _MAX_MSGS = 60;
let _slowTimer         = null;
const _SLOW_THRESHOLD_MS = 8000;

/* --------------------------------------------------------------------------
   TEXTURA SPRITE — gradiente radial branco → transparente (32×32)
   -------------------------------------------------------------------------- */
const _spriteTex = (() => {
    const sz = 32, cv = document.createElement('canvas');
    cv.width = cv.height = sz;
    const ctx = cv.getContext('2d');
    const gr  = ctx.createRadialGradient(sz/2,sz/2,0, sz/2,sz/2,sz/2);
    gr.addColorStop(0.00, 'rgba(255,255,255,1.00)');
    gr.addColorStop(0.20, 'rgba(255,255,255,0.80)');
    gr.addColorStop(0.50, 'rgba(255,255,255,0.18)');
    gr.addColorStop(0.80, 'rgba(255,255,255,0.03)');
    gr.addColorStop(1.00, 'rgba(255,255,255,0.00)');
    ctx.fillStyle = gr;
    ctx.fillRect(0, 0, sz, sz);
    return new THREE.CanvasTexture(cv);
})();

/* --------------------------------------------------------------------------
   INIT
   -------------------------------------------------------------------------- */
function init() {
    const container = document.getElementById('canvas-container');

    scene  = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(38, innerWidth / innerHeight, 0.1, 800);
    camera.position.z = 140;

    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(innerWidth, innerHeight);
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    _buildSphere();
    _buildGlow();
    _buildNebulas();
    _setupInput();
    _setupWS();
    _setupPanel();
    _setupMetrics();
    _setupHealth();
    _setupChatScroll();
    _setupDragDrop();
    _setupVoiceLive();
    window.addEventListener('resize', _onResize);

    window.setAudioIntensity = v => { audioInten = Math.max(0, Math.min(1, +v || 0)); };
    window.setLyraState      = s => _setState(s);

    animate();
}

/* --------------------------------------------------------------------------
   ESFERA DE PARTÍCULAS
   Pontos aleatórios na superfície esférica com jitter de raio por camada.
   -------------------------------------------------------------------------- */
function _buildSphere() {
    nucleus        = new THREE.Group();
    particleLayers = [];

    for (let li = 0; li < LAYERS.length; li++) {
        const L   = LAYERS[li];
        const pos = new Float32Array(L.n * 3);

        for (let i = 0; i < L.n; i++) {
            // Distribuição uniforme na superfície da esfera
            const u     = Math.random();
            const v     = Math.random();
            const theta = 2 * PI * u;
            const phi   = Math.acos(2 * v - 1);
            const r     = SPHERE_R * (1 - L.jitter/2 + Math.random() * L.jitter);

            pos[i*3]   = r * Math.sin(phi) * Math.cos(theta);
            pos[i*3+1] = r * Math.sin(phi) * Math.sin(theta);
            pos[i*3+2] = r * Math.cos(phi);
        }

        // Cor por vértice — começa igual à cor base da camada (visual idêntico
        // ao de antes em repouso), mas permite "lavar" a cor por estado e,
        // na camada brilhante, desenhar a faixa de varredura do "processando".
        const baseColor = new THREE.Color(L.color);
        const colors = new Float32Array(L.n * 3);
        for (let i = 0; i < L.n; i++) {
            colors[i*3] = baseColor.r; colors[i*3+1] = baseColor.g; colors[i*3+2] = baseColor.b;
        }

        const geo = new THREE.BufferGeometry();
        geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
        geo.setAttribute('color',    new THREE.BufferAttribute(colors, 3));

        const mat = new THREE.PointsMaterial({
            color:           0xffffff,
            vertexColors:    true,
            map:             _spriteTex,
            size:            L.size,
            transparent:     true,
            opacity:         L.op,
            blending:        THREE.AdditiveBlending,
            depthWrite:      false,
            sizeAttenuation: true,
            alphaTest:       0.001,
        });

        const pts = new THREE.Points(geo, mat);
        nucleus.add(pts);

        particleLayers.push({
            pts, mat,
            baseOp: L.op,
            phase:  li * 1.47 + Math.random() * 0.5,
            baseColor,
            n: L.n,
            posAttr:   geo.attributes.position,
            colorAttr: geo.attributes.color,
        });
    }

    scene.add(nucleus);
}

/* --------------------------------------------------------------------------
   GLOW CENTRAL
   -------------------------------------------------------------------------- */
function _buildGlow() {
    const sz  = 128, cv = document.createElement('canvas');
    cv.width  = cv.height = sz;
    const ctx = cv.getContext('2d');
    const gr  = ctx.createRadialGradient(sz/2,sz/2,0, sz/2,sz/2,sz/2);
    gr.addColorStop(0.00, 'rgba(0, 235, 255, 0.88)');
    gr.addColorStop(0.15, 'rgba(0, 170, 255, 0.42)');
    gr.addColorStop(0.40, 'rgba(0,  60, 200, 0.10)');
    gr.addColorStop(1.00, 'rgba(0,   0,   0, 0.00)');
    ctx.fillStyle = gr;
    ctx.fillRect(0, 0, sz, sz);

    glow = new THREE.Sprite(new THREE.SpriteMaterial({
        map:         new THREE.CanvasTexture(cv),
        blending:    THREE.AdditiveBlending,
        depthWrite:  false,
        transparent: true,
        opacity:     0.45,
    }));
    glow.scale.set(14, 14, 1);
    nucleus.add(glow);
}

/* --------------------------------------------------------------------------
   NEBULOSAS DE FUNDO
   Nuvens irregulares e bem discretas, soltas na cena (fora do grupo
   `nucleus`) para criar paralaxe independente da rotação do núcleo.
   Textura desenhada com várias manchas radiais sobrepostas, em vez de
   um único gradiente — evita o efeito "borrão circular" óbvio.
   -------------------------------------------------------------------------- */
function _makeNebulaTexture(rgb) {
    const sz = 256, cv = document.createElement('canvas');
    cv.width = cv.height = sz;
    const ctx = cv.getContext('2d');
    for (let i = 0; i < 5; i++) {
        const x = sz * (0.30 + Math.random() * 0.40);
        const y = sz * (0.30 + Math.random() * 0.40);
        const r = sz * (0.20 + Math.random() * 0.20);
        const gr = ctx.createRadialGradient(x, y, 0, x, y, r);
        gr.addColorStop(0.00, `rgba(${rgb},0.45)`);
        gr.addColorStop(0.55, `rgba(${rgb},0.14)`);
        gr.addColorStop(1.00, `rgba(${rgb},0.00)`);
        ctx.fillStyle = gr;
        ctx.fillRect(0, 0, sz, sz);
    }
    return new THREE.CanvasTexture(cv);
}

function _buildNebulas() {
    const defs = [
        { rgb: '0,80,150',   pos: [-58, 16, -95],  scale: 60, op: 0.04 },
        { rgb: '60,30,120',  pos: [62, -20, -125], scale: 70, op: 0.03 },
    ];
    nebulas = defs.map(d => {
        const mat = new THREE.SpriteMaterial({
            map: _makeNebulaTexture(d.rgb),
            transparent: true,
            opacity: d.op,
            depthWrite: false,
            blending: THREE.NormalBlending,
        });
        const spr = new THREE.Sprite(mat);
        spr.position.set(...d.pos);
        spr.scale.set(d.scale, d.scale, 1);
        scene.add(spr);
        return { spr, mat, baseOp: d.op, baseX: d.pos[0], baseY: d.pos[1], phase: Math.random() * 10 };
    });
}

/* --------------------------------------------------------------------------
   VISUALIZADOR DE GRAFO DE MEMÓRIA
   Busca /grafo/completo do backend, renderiza com 3d-force-graph.
   O overlay é aberto via botão "Memória" no painel lateral.
   -------------------------------------------------------------------------- */
let _grafoInstance = null;
let _grafoData     = null;

function _grafoMockData() {
    const kws = ['python','memória','lyra','ia','código','rag','llm','frontend',
                 'backend','qdrant','surreal','ollama','embeddings','voz',
                 'websocket','agente','planejamento','contexto','three.js','fastapi'];
    const topicos = kws.map(t => ({ id:`topico:${t}`, tipo:'topico', label:t }));
    const frases = [
        'Implementamos o módulo de RAG híbrido com BM25 e BGE-M3',
        'Corrigido bug no endpoint /chat SSE do cerebro_maestro',
        'Adicionada ferramenta navegar_web com Playwright',
        'Configurado Telegram bot em modo polling bidirecional',
        'Criados axônios sinápticos no frontend Three.js',
        'Shadow Thoughts: ciclo NREM/REM/DEEP implementado',
        'Migração BGE-M3 concluída com sucesso',
        'Cascata de modelos Groq → Gemini → Claude → local',
        'Boot overlay com animação de partículas implementado',
        'Visualizador 3D de grafo integrado ao painel',
    ];
    const eventos = Array.from({ length: 80 }, (_, i) => ({
        id: `evento:ev${String(i).padStart(3,'0')}`, tipo:'evento',
        label: frases[i % frases.length], ator: ['user','lyra'][i % 2],
    }));
    const links = [];
    eventos.forEach((ev, i) => {
        const n = 2 + (i % 3);
        for (let k = 0; k < n; k++)
            links.push({ source: ev.id, target: topicos[(i*3+k*7) % topicos.length].id, rel:'sobre' });
    });
    return { nodes: [...topicos, ...eventos], links };
}

function abrirGrafo() {
    const ov = document.getElementById('grafo-overlay');
    if (!ov) return;
    ov.classList.add('open');
    _carregarGrafo();
}

function fecharGrafo() {
    document.getElementById('grafo-overlay')?.classList.remove('open');
}

async function _carregarGrafo() {
    const container = document.getElementById('grafo-container');
    if (!container) return;

    // Spinner de carregamento
    let loadEl = document.getElementById('grafo-loading');
    if (!loadEl) {
        loadEl = document.createElement('div');
        loadEl.id = 'grafo-loading';
        loadEl.textContent = 'carregando memória…';
        container.appendChild(loadEl);
    }
    loadEl.style.display = 'flex';

    let demo = false;
    try {
        const ctrl = new AbortController();
        const tid  = setTimeout(() => ctrl.abort(), 6000);
        const res  = await fetch('http://127.0.0.1:8000/grafo/completo?limite=500', { signal: ctrl.signal });
        clearTimeout(tid);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        _grafoData = await res.json();
        if (!_grafoData.nodes?.length) throw new Error('vazio');
    } catch (e) {
        demo = true;
        _grafoData = _grafoMockData();
    }

    loadEl.style.display = 'none';

    const stats = document.getElementById('grafo-stats');
    const badge = document.getElementById('grafo-stats');
    if (stats) {
        const n = _grafoData.nodes?.length ?? 0;
        const l = _grafoData.links?.length ?? 0;
        stats.textContent = `${n} Memórias · ${l} Conexões${demo ? ' · Demo' : ''}`;
    }

    _renderGrafo(_grafoData);
}

function _renderGrafo(data) {
    const container = document.getElementById('grafo-container');
    if (!container || typeof ForceGraph3D === 'undefined') return;

    if (_grafoInstance) {
        _grafoInstance._destructor?.();
        _grafoInstance = null;
        container.innerHTML = '';
        const loadEl = document.createElement('div');
        loadEl.id = 'grafo-loading';
        loadEl.style.display = 'none';
        container.appendChild(loadEl);
    }

    const W = container.clientWidth  || 900;
    const H = container.clientHeight || 580;
    const GRAFO_R   = 70;  // raio da casca esférica das memórias
    const LYRA_NODE = 'lyra:core';

    // Capitaliza label para exibição
    const _capG = s => {
        if (!s) return s;
        if (s.length <= 30 && !s.includes(' ')) return s.replace(/\b\w/g, c => c.toUpperCase());
        return s.charAt(0).toUpperCase() + s.slice(1);
    };

    // Grau de cada nó (para escalar tamanho dos hubs)
    const deg = {};
    (data.links || []).forEach(l => {
        const s = l.source?.id ?? l.source;
        const t = l.target?.id ?? l.target;
        deg[s] = (deg[s] || 0) + 1;
        deg[t] = (deg[t] || 0) + 1;
    });

    // Nó central Lyra — fixado na origem
    const nodes = [...(data.nodes || [])];
    // Link apontando pra um id fora de `nodes` crasha o 3d-force-graph com
    // um erro não tratado que derruba o grafo inteiro (achado real: link
    // órfão vindo do backend). Filtro defensivo aqui, além do fix na origem
    // em cerebro_maestro.py — não deixa uma futura regressão do backend (ou
    // dado velho já salvo) quebrar a visualização de novo.
    const _idsValidos = new Set(nodes.map(n => n.id));
    const links = (data.links || []).filter(l => _idsValidos.has(l.source) && _idsValidos.has(l.target));
    nodes.push({ id: LYRA_NODE, tipo: 'lyra', label: 'Lyra', _deg: 999,
                 fx: 0, fy: 0, fz: 0 });

    // Conectar todos os tópicos ao núcleo Lyra
    nodes.filter(n => n.tipo === 'topico').forEach(t => {
        links.push({ source: LYRA_NODE, target: t.id, rel: 'lyra' });
    });

    nodes.forEach(n => { n._deg = deg[n.id] || 1; });

    // Curvatura orgânica aleatória por link
    links.forEach(l => {
        if (!('_curv' in l)) {
            if (l.rel === 'lyra')       { l._curv = 0.18 + Math.random() * 0.22; l._rot = Math.random() * Math.PI * 2; }
            else if (l.rel === 'sobre') { l._curv = 0.08 + Math.random() * 0.18; l._rot = Math.random() * Math.PI * 2; }
            else                        { l._curv = 0; l._rot = 0; }
        }
    });

    // Posições iniciais em Fibonacci na superfície esférica (ignora Lyra)
    const shell = nodes.filter(n => n.id !== LYRA_NODE);
    shell.forEach((n, i) => {
        const phi   = Math.acos(1 - 2 * (i + 0.5) / shell.length);
        const theta = Math.PI * (1 + Math.sqrt(5)) * i;
        n.x = GRAFO_R * Math.sin(phi) * Math.cos(theta);
        n.y = GRAFO_R * Math.sin(phi) * Math.sin(theta);
        n.z = GRAFO_R * Math.cos(phi);
    });

    // Cores
    const _gC = {
        topico:      new THREE.Color(0xcc9944),
        evento_lyra: new THREE.Color(0x00bbee),
        evento_user: new THREE.Color(0x4477cc),
    };

    // Cada nó = sprites concêntricos com glow (reutiliza _spriteTex do núcleo)
    const _makeGrafoNode = n => {
        const group = new THREE.Group();
        const spr = (sz, col, op) => {
            const s = new THREE.Sprite(new THREE.SpriteMaterial({
                map: _spriteTex, color: col,
                blending: THREE.AdditiveBlending,
                transparent: true, opacity: op, depthWrite: false,
            }));
            s.scale.set(sz, sz, 1); group.add(s);
        };

        if (n.id === LYRA_NODE) {
            // Núcleo Lyra — idêntico ao glow central da esfera de partículas
            spr(44, new THREE.Color(0x003388), 0.07);
            spr(26, new THREE.Color(0x0077bb), 0.16);
            spr(14, new THREE.Color(0x22aaff), 0.38);
            spr(7,  new THREE.Color(0x66ddff), 0.68);
            spr(3,  new THREE.Color(0xffffff), 0.96);
            return group;
        }

        const isTopic = n.tipo === 'topico';
        const col     = isTopic ? _gC.topico : (n.ator === 'lyra' ? _gC.evento_lyra : _gC.evento_user);
        const boost   = 1 + Math.log2(Math.max(n._deg || 1, 1)) * (isTopic ? 0.45 : 0.20);
        const core    = (isTopic ? 2.4 : 1.4) * boost;

        spr(core * 3.0, col, isTopic ? 0.04 : 0.025);
        spr(core * 1.7, col, isTopic ? 0.16 : 0.11);
        spr(core,       col, isTopic ? 0.90 : 0.80);
        return group;
    };

    // Força radial — exclui Lyra (fixada)
    const _grafoSphereForce = (() => {
        let _ns = [];
        function f(alpha) {
            for (const n of _ns) {
                if (n.id === LYRA_NODE) continue;
                const d = Math.sqrt((n.x||0)**2 + (n.y||0)**2 + (n.z||0)**2) || 0.001;
                const k = (GRAFO_R / d - 1) * 0.90 * alpha;
                n.vx = (n.vx||0) + (n.x||0) * k;
                n.vy = (n.vy||0) + (n.y||0) * k;
                n.vz = (n.vz||0) + (n.z||0) * k;
            }
        }
        f.initialize = ns => { _ns = ns; };
        return f;
    })();

    // Campo de estrelas no fundo
    const _addGrafoStars = sc => {
        const pos = new Float32Array(1400 * 3);
        for (let i = 0; i < 1400; i++) {
            const phi = Math.acos(2 * Math.random() - 1);
            const th  = Math.random() * Math.PI * 2;
            const r   = 380 + Math.random() * 200;
            pos[i*3]   = r * Math.sin(phi) * Math.cos(th);
            pos[i*3+1] = r * Math.sin(phi) * Math.sin(th);
            pos[i*3+2] = r * Math.cos(phi);
        }
        const geo = new THREE.BufferGeometry();
        geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
        sc.add(new THREE.Points(geo, new THREE.PointsMaterial({
            color: 0xaaccff, size: 0.55,
            transparent: true, opacity: 0.30, depthWrite: false,
        })));
    };

    _grafoInstance = ForceGraph3D({ controlType: 'orbit' })(container)
        .width(W).height(H)
        .backgroundColor('rgba(0,0,0,0)')
        .showNavInfo(false)
        .graphData({ nodes, links })
        .nodeLabel(n => n.id === LYRA_NODE ? 'Lyra' : _capG(n.label || n.id))
        .nodeThreeObject(_makeGrafoNode)
        .nodeThreeObjectExtend(false)
        .nodeVal(n => n.id === LYRA_NODE ? 30 : Math.max(1, (n._deg||1) * (n.tipo==='topico' ? 1.1 : 0.45)))
        // Apenas Lyra→tópico visíveis — sobre invisível mas mantém topologia
        .linkColor(l => l.rel === 'lyra' ? 'rgba(0,170,255,0.30)' : 'rgba(0,0,0,0)')
        .linkWidth(l => l.rel === 'lyra' ? 0.45 : 0)
        .linkCurvature(l => l._curv || 0)
        .linkCurveRotation(l => l._rot || 0)
        .linkDirectionalParticles(0)
        .d3AlphaDecay(0.04)
        .d3VelocityDecay(0.35)
        .cooldownTicks(200)
        .onEngineStop(() => {
            const c = _grafoInstance.controls();
            if (c) { c.autoRotate = true; c.autoRotateSpeed = 0.28; }
        })
        .onNodeClick(n => _mostrarDetalheGrafo(n))
        .onBackgroundClick(() => {
            document.getElementById('grafo-detail')?.classList.remove('show');
        });

    _addGrafoStars(_grafoInstance.scene());
    _grafoInstance.d3Force('radial-sphere', _grafoSphereForce);
    _grafoInstance.d3Force('charge').strength(-10);
    if (_grafoInstance.d3Force('link'))
        _grafoInstance.d3Force('link').distance(GRAFO_R * 0.80).strength(0.03);

    _grafoInstance.cameraPosition({ x: 0, y: 0, z: GRAFO_R * 3.6 });

    const ctrl = _grafoInstance.controls();
    if (ctrl) {
        ctrl.enableDamping  = true;
        ctrl.dampingFactor  = 0.07;
    }

    // Busca de nós pelo input
    const srch = document.getElementById('grafo-search');
    if (srch) {
        srch.oninput = () => {
            const q = srch.value.trim().toLowerCase();
            if (!_grafoInstance || !_grafoData) return;
            _grafoInstance.graphData({
                nodes: q ? nodes.filter(n => n.id===LYRA_NODE || (n.label||n.id).toLowerCase().includes(q)) : nodes,
                links,
            });
        };
    }
}

function _mostrarDetalheGrafo(n) {
    const el = document.getElementById('grafo-detail');
    if (!el) return;
    if (n.id === 'lyra:core') {
        el.innerHTML = `<div style="color:rgba(0,221,255,0.55);font-size:0.68rem;letter-spacing:.08em;margin-bottom:6px;font-weight:300">✦ Lyra</div>
<div style="color:rgba(255,255,255,0.55);font-size:0.62rem;line-height:1.6">Núcleo central de memória.</div>`;
        el.classList.add('show');
        return;
    }
    const tipo  = n.tipo === 'topico' ? '◆ Tópico' : (n.ator === 'lyra' ? '◇ Memória — Lyra' : '◇ Memória — Usuário');
    const label = n.label || n.id;
    const ts    = n.ts ? new Date(n.ts).toLocaleString('pt-BR', { day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit' }) : '';
    el.innerHTML = `<div style="color:rgba(0,221,255,0.38);font-size:0.57rem;letter-spacing:.12em;margin-bottom:5px">${tipo}</div>
<div style="color:rgba(255,255,255,0.80);line-height:1.5;word-break:break-word">${label}</div>
${ts ? `<div style="color:rgba(0,221,255,0.36);font-size:0.59rem;margin-top:5px">${ts}</div>` : ''}
${n.ator ? `<div style="color:rgba(255,255,255,0.25);font-size:0.58rem;margin-top:2px">Ator: ${n.ator.charAt(0).toUpperCase()+n.ator.slice(1)}</div>` : ''}
${n._deg ? `<div style="color:rgba(0,221,255,0.22);font-size:0.56rem;margin-top:3px">${n._deg} conexão${n._deg!==1?'ões':''}</div>` : ''}`;
    el.classList.add('show');
}

/* --------------------------------------------------------------------------
   LOOP DE ANIMAÇÃO
   -------------------------------------------------------------------------- */
let _focused   = true;
let _frameSkip = 0;
window.addEventListener('blur',  () => { _focused = false; });
window.addEventListener('focus', () => { _focused = true; });
document.addEventListener('visibilitychange', () => { _focused = !document.hidden; });

function animate() {
    requestAnimationFrame(animate);

    // Modo economia — sem foco na janela, renderiza só 1 em cada 4 frames
    // (~15fps em vez de 60fps) pra não gastar GPU com a tela em segundo plano.
    if (!_focused) {
        _frameSkip = (_frameSkip + 1) % 4;
        if (_frameSkip !== 0) return;
    }

    const t  = Date.now() * 0.001;
    smoothA += (audioInten - smoothA) * 0.09;
    const a  = smoothA;

    // Rotação suave da esfera inteira
    nucleus.rotation.y += 0.00018;
    nucleus.rotation.x  = Math.sin(t * 0.032) * 0.040;

    // Escala reativa ao áudio
    const tgt = 1.0 + a * 0.12;
    curScale += (tgt - curScale) * 0.07;
    if (curState === 'speaking') {
        // Wobble não-uniforme por eixo — sugere algo "vivo/líquido" sem
        // precisar de um vertex shader de distorção (fora de escopo por ora).
        const wob = a * 0.05;
        nucleus.scale.set(
            curScale + Math.sin(t * 3.1)       * wob,
            curScale + Math.sin(t * 3.1 + 2.1) * wob,
            curScale + Math.sin(t * 3.1 + 4.2) * wob,
        );
    } else {
        nucleus.scale.setScalar(curScale);
    }

    // Pulso de opacidade por camada + lavagem de cor sutil por estado
    const tint = STATE_TINT[curState];
    for (const p of particleLayers) {
        const pulse = Math.sin(t * 1.2 + p.phase) * 0.06
                    + Math.sin(t * 2.7 + p.phase * 1.5) * 0.025;
        p.mat.opacity = Math.max(0.04, Math.min(1, p.baseOp + pulse + a * 0.28));

        const col   = p.colorAttr.array;
        const wash  = tint ? 0.22 : 0;
        const tr    = tint ? tint.r : p.baseColor.r;
        const tg    = tint ? tint.g : p.baseColor.g;
        const tb    = tint ? tint.b : p.baseColor.b;
        const targR = p.baseColor.r * (1 - wash) + tr * wash;
        const targG = p.baseColor.g * (1 - wash) + tg * wash;
        const targB = p.baseColor.b * (1 - wash) + tb * wash;
        for (let i = 0; i < p.n; i++) {
            col[i*3]   += (targR - col[i*3])   * 0.05;
            col[i*3+1] += (targG - col[i*3+1]) * 0.05;
            col[i*3+2] += (targB - col[i*3+2]) * 0.05;
        }
        p.colorAttr.needsUpdate = true;
    }

    // "Processando" — faixa de varredura na camada brilhante (radar sutil)
    if (curState === 'processing') {
        const bright = particleLayers[0];
        sweepAngle += 0.045;
        const arr = bright.posAttr.array;
        const col = bright.colorAttr.array;
        const bw  = 0.5;
        for (let i = 0; i < bright.n; i++) {
            const theta = Math.atan2(arr[i*3+1], arr[i*3]);
            let d = Math.abs(theta - (sweepAngle % (2 * PI)));
            if (d > PI) d = 2 * PI - d;
            const boost = d < bw ? (1 - d / bw) * 0.8 : 0;
            if (boost > 0) {
                col[i*3]   = Math.min(1, col[i*3]   + boost);
                col[i*3+1] = Math.min(1, col[i*3+1] + boost);
                col[i*3+2] = Math.min(1, col[i*3+2] + boost);
            }
        }
        bright.colorAttr.needsUpdate = true;
    }

    // Glow central
    const flash = bootFlashT < 1 ? (1 - bootFlashT) ** 2 : 0;
    if (bootFlashT < 1) bootFlashT += 0.018;
    const gs = 14 + a * 18 + Math.sin(t * 1.85) * 1.2 + flash * 22;
    glow.scale.set(gs, gs, 1);
    glow.material.opacity = 0.32 + a * 0.42 + Math.sin(t * 2.1) * 0.04 + flash * 0.55;

    // Nebulosas — deriva lenta e independente, sem girar com o núcleo
    for (const n of nebulas) {
        n.spr.position.x = n.baseX + Math.sin(t * 0.028 + n.phase) * 4;
        n.spr.position.y = n.baseY + Math.cos(t * 0.021 + n.phase) * 3;
        n.mat.opacity     = n.baseOp + Math.sin(t * 0.15 + n.phase) * 0.02;
    }

    // Mic ring — reage ao audioInten quando ouvindo
    if (curState === 'listening') {
        const micRing = document.getElementById('mic-ring');
        if (micRing) {
            const s  = (1 + a * 2.8).toFixed(3);
            const op = (0.22 + a * 0.72).toFixed(3);
            micRing.style.transform   = `scale(${s})`;
            micRing.style.borderColor = `rgba(0,221,255,${op})`;
        }
    }

    renderer.render(scene, camera);
}

/* --------------------------------------------------------------------------
   GERENCIAMENTO DE ESTADO
   -------------------------------------------------------------------------- */
// Casing consistente com o resto da UI (só a primeira palavra maiúscula,
// como em todos os data-tip/aria-label) — "Em Espera" destoava (Title Case).
const S_LABELS = {
    idle:       'Em espera',
    listening:  'Ouvindo',
    processing: 'Processando',
    speaking:   'Falando',
};
// idle usava #00CCFF, um azul levemente diferente do --neon oficial do app
// (#00DDFF) — o dot central ficava com essa cor errada na maior parte do
// tempo, já que "idle" é o estado padrão/mais comum.
const S_COLORS = {
    idle:       '#00DDFF',
    listening:  '#00FF99',
    processing: '#FFAA33',
    speaking:   '#BB44FF',
};

function _setState(s) {
    if (curState === s) return;
    curState = s;

    const col = S_COLORS[s] || '#fff';

    const dot = document.getElementById('state-dot');
    const lbl = document.getElementById('state-indicator');
    if (dot) { dot.style.background = col; dot.style.boxShadow = `0 0 9px ${col}`; }
    if (lbl) lbl.textContent = S_LABELS[s] || s;

    const mic = document.getElementById('mic-btn');
    if (mic) mic.classList.toggle('active', s === 'listening');

    if (s !== 'listening') {
        const micRing = document.getElementById('mic-ring');
        if (micRing) {
            micRing.style.transform   = 'scale(1)';
            micRing.style.borderColor = 'rgba(0,221,255,0)';
        }
    }

    const pLabel  = document.getElementById('p-state-label');
    const pDot    = document.getElementById('dot-state');
    if (pLabel) pLabel.textContent = S_LABELS[s] || s;
    if (pDot)   { pDot.style.background = col; pDot.style.boxShadow = `0 0 5px ${col}`; }

    const chatDot = document.getElementById('chat-header-dot');
    if (chatDot) { chatDot.style.background = col; chatDot.style.boxShadow = `0 0 6px ${col}`; }

    if (s === 'processing') audioInten = 0.35;
    if (s === 'idle')       setTimeout(() => { if (curState === 'idle') audioInten = 0.0; }, 600);
}

/* --------------------------------------------------------------------------
   WEBSOCKET
   -------------------------------------------------------------------------- */
function _setupWS() {
    let ws, delay = 2000;

    const connect = () => {
        try {
            ws = new WebSocket('ws://localhost:8765');

            ws.onopen = () => {
                delay = 2000;
                _updatePanelDot('ws', true);
                _hideToast();
            };

            ws.onmessage = ({ data }) => {
                try {
                    const m = JSON.parse(data);

                    if (m.state     != null) _setState(m.state);
                    if (m.intensity != null) audioInten = Math.max(0, Math.min(1, m.intensity));

                    if (m.state === 'processing') {
                        _lyraFull          = '';
                        _pendingNewLyraMsg = true;
                        _currentLyraMsgEl  = null;
                        if (_hideTimer) { clearTimeout(_hideTimer); _hideTimer = null; }
                        _showTyping();
                        _armSlowHint();
                    }

                    if (m.user_text) _showBubble('user', m.user_text);

                    if (m.tier) {
                        const el = document.getElementById('p-fonte-label');
                        if (el) el.textContent = m.tier;
                    }

                    if (m.ai_chunk) {
                        _disarmSlowHint();
                        _lyraFull += m.ai_chunk;
                        _showBubble('lyra', _lyraFull);
                    }

                    if (m.state === 'idle' && _lyraFull) {
                        _hideTimer = null;
                    }
                } catch (_) {}
            };

            ws.onclose = () => {
                _disarmSlowHint();
                _updatePanelDot('ws', false);
                _showToast('Conexão perdida — reconectando…');
                setTimeout(connect, delay);
                delay = Math.min(delay * 1.5, 15000);
            };
            ws.onerror = () => ws.close();

        } catch (_) { setTimeout(connect, delay); }
    };

    connect();
}

/* --------------------------------------------------------------------------
   VOZ LIVE — Gemini Live API via ws://.../ws/voice
   Pipeline paralelo e independente do mic-btn/mic_engine.py acima: aqui o
   browser captura, envia e toca áudio diretamente, sem passar pelo hub :8765.
   -------------------------------------------------------------------------- */
let _vlWS = null, _vlStream = null, _vlCtx = null, _vlSource = null, _vlProcessor = null;
let _vlPlayCtx = null, _vlPlayNextTime = 0, _vlActive = false;

function _vlGetPlayCtx() {
    if (!_vlPlayCtx) {
        try { _vlPlayCtx = new (window.AudioContext || window.webkitAudioContext)(); }
        catch (_) { _vlPlayCtx = null; }
    }
    return _vlPlayCtx;
}

function _vlPlayPCM24k(buf) {
    const ctx = _vlGetPlayCtx();
    if (!ctx || !buf.byteLength) return;
    const int16 = new Int16Array(buf);
    const f32   = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) f32[i] = int16[i] / 32768;

    const audioBuf = ctx.createBuffer(1, f32.length, 24000);
    audioBuf.getChannelData(0).set(f32);

    const src = ctx.createBufferSource();
    src.buffer = audioBuf;
    src.connect(ctx.destination);

    const startAt = Math.max(ctx.currentTime, _vlPlayNextTime);
    src.start(startAt);
    _vlPlayNextTime = startAt + audioBuf.duration;

    _setState('speaking');
}

function _vlSendCmd(cmd) {
    if (_vlWS && _vlWS.readyState === WebSocket.OPEN) _vlWS.send(JSON.stringify({ cmd }));
}

async function _vlStart() {
    if (_vlActive) return;
    _vlActive = true;
    document.getElementById('voice-live-btn')?.classList.add('active');

    try {
        _vlStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
        _showBubble('lyra', 'Não foi possível acessar o microfone: ' + e.message);
        _vlActive = false;
        document.getElementById('voice-live-btn')?.classList.remove('active');
        return;
    }

    // Pede 16kHz direto no AudioContext pra evitar resample manual —
    // Chromium (base do pywebview no Windows) honra esse hint.
    _vlCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
    _vlSource    = _vlCtx.createMediaStreamSource(_vlStream);
    _vlProcessor = _vlCtx.createScriptProcessor(4096, 1, 1);

    const silence = _vlCtx.createGain();
    silence.gain.value = 0;
    _vlSource.connect(_vlProcessor);
    _vlProcessor.connect(silence);
    silence.connect(_vlCtx.destination);

    _vlProcessor.onaudioprocess = e => {
        if (!_vlWS || _vlWS.readyState !== WebSocket.OPEN) return;
        const f32   = e.inputBuffer.getChannelData(0);
        const int16 = new Int16Array(f32.length);
        for (let i = 0; i < f32.length; i++) {
            const s = Math.max(-1, Math.min(1, f32[i]));
            int16[i] = s < 0 ? s * 32768 : s * 32767;
        }
        _vlWS.send(int16.buffer);
    };

    _vlWS = new WebSocket('ws://localhost:8000/ws/voice');
    _vlWS.binaryType = 'arraybuffer';

    _vlWS.onopen = () => {
        _vlSendCmd('start');
        _setState('listening');
    };

    _vlWS.onmessage = ({ data }) => {
        if (data instanceof ArrayBuffer) {
            _vlPlayPCM24k(data);
            return;
        }
        try {
            const m = JSON.parse(data);
            if (m.type === 'text' && m.text) _showBubble('lyra', m.text);
            if (m.type === 'done') { if (_vlActive) _setState('listening'); }
            if (m.type === 'error') {
                _showBubble('lyra', 'Voz Live — erro: ' + m.msg);
                _vlStop();
            }
        } catch (_) {}
    };

    _vlWS.onerror = () => { _showBubble('lyra', 'Voz Live — falha na conexão.'); _vlStop(); };
    _vlWS.onclose = () => { if (_vlActive) _vlStop(); };
}

function _vlStop() {
    if (!_vlActive) return;
    _vlActive = false;
    document.getElementById('voice-live-btn')?.classList.remove('active');

    _vlSendCmd('stop');
    try { _vlWS?.close(); } catch (_) {}
    _vlWS = null;

    _vlStream?.getTracks().forEach(t => t.stop());
    _vlStream = null;

    try { _vlProcessor?.disconnect(); _vlSource?.disconnect(); } catch (_) {}
    try { _vlCtx?.close(); } catch (_) {}
    _vlCtx = null; _vlSource = null; _vlProcessor = null;

    _vlPlayNextTime = 0;
    _setState('idle');
}

function _setupVoiceLive() {
    const btn = document.getElementById('voice-live-btn');
    if (!btn) return;
    btn.addEventListener('click', () => { _vlActive ? _vlStop() : _vlStart(); });
}

/* --------------------------------------------------------------------------
   PAINEL LATERAL
   -------------------------------------------------------------------------- */
function _setupPanel() {
    const checkCerebro = async () => {
        try {
            const ctrl = new AbortController();
            const tid  = setTimeout(() => ctrl.abort(), 2000);
            await fetch('http://127.0.0.1:8000/', { signal: ctrl.signal });
            clearTimeout(tid);
            _updatePanelDot('cerebro', true);
        } catch (_) {
            _updatePanelDot('cerebro', false);
        }
    };
    checkCerebro();
    setInterval(checkCerebro, 8000);

    // Seletor de modelo — persiste em localStorage pra já abrir com a
    // última escolha do usuário (default 'auto' = cascata Groq/Gemini/Claude/local).
    const sel = document.getElementById('sel-modelo');
    if (sel) {
        sel.value = localStorage.getItem('lyra_modelo_escolhido') || 'auto';
        sel.addEventListener('change', () => {
            localStorage.setItem('lyra_modelo_escolhido', sel.value);
        });
    }
}

function _updatePanelDot(id, online) {
    const dot = document.getElementById(`dot-${id}`);
    if (!dot) return;
    const col = online ? '#00FF99' : '#FF3355';
    dot.style.background = col;
    dot.style.boxShadow  = `0 0 5px ${col}`;
}

function togglePanel() {
    // Sidebar persistente estilo app Claude: o hambúrguer recolhe pra
    // um rail de ícones em vez de esconder o painel inteiro.
    const collapsed = document.body.classList.toggle('sb-collapsed');
    localStorage.setItem('lyra_sb_collapsed', collapsed ? '1' : '0');
}

/* --------------------------------------------------------------------------
   TOAST DE STATUS
   -------------------------------------------------------------------------- */
let _toastTimer = null;
function _showToast(text) {
    const el = document.getElementById('toast');
    if (!el) return;
    el.textContent = text;
    el.classList.add('show');
    if (_toastTimer) clearTimeout(_toastTimer);
}
function _hideToast() {
    const el = document.getElementById('toast');
    if (!el) return;
    if (_toastTimer) clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => el.classList.remove('show'), 400);
}

/* --------------------------------------------------------------------------
   CHAT — VIEW central (estilo app Claude), aberta via sidebar ou "/"
   -------------------------------------------------------------------------- */
let _chatOpen = false;

function toggleChat(force) {
    // Fachada pra todos os pontos antigos que chamam toggleChat ("/", Esc) —
    // o roteamento real mora em LyraUI.showView (ui.js).
    const abrir = typeof force === 'boolean' ? force : !_chatOpen;
    if (window.LyraUI) LyraUI.showView(abrir ? 'chat' : 'home');
}

function _setChatBadge(on) {
    document.getElementById('chat-toggle-badge')?.classList.toggle('show', on);
}

async function limparHistorico() {
    if (!confirm('Limpar histórico em memória? (SurrealDB/Qdrant não são afetados)')) return;
    try {
        await fetch('http://127.0.0.1:8000/historico', { method: 'DELETE' });
        document.getElementById('chat-messages').innerHTML = '';
        _showBubble('lyra', '— histórico em memória limpo —');
    } catch (e) {
        _showBubble('lyra', 'Falha ao limpar histórico: ' + e.message);
    }
}

async function exportarConversa() {
    try {
        const res = await fetch('http://127.0.0.1:8000/exportar');
        const d   = await res.json();
        if (!d.markdown || d.total_msgs === 0) {
            _showToast('Nada para exportar ainda.');
            return;
        }
        const blob = new Blob([d.markdown], { type: 'text/markdown;charset=utf-8' });
        const url  = URL.createObjectURL(blob);
        const a    = document.createElement('a');
        const ts   = new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-');
        a.href = url;
        a.download = `lyra-conversa-${ts}.md`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        _showToast(`Conversa exportada (${d.total_msgs} msgs).`);
    } catch (e) {
        _showToast('Falha ao exportar: ' + e.message);
    }
}

/* --------------------------------------------------------------------------
   PAINEL — ATIVIDADE (latência / cpu / ram + sparkline)
   Poll leve (4s) só em CPU/RAM via psutil no backend — sem GPU de propósito,
   pra não somar carga numa GPU que já está ocupada com os modelos do Ollama.
   -------------------------------------------------------------------------- */
const _LAT_HISTORY_MAX = 24;
let _latHistory = [];

function _setupMetrics() {
    const elLat  = document.getElementById('m-latencia');
    const elCpu  = document.getElementById('m-cpu');
    const elRam  = document.getElementById('m-ram');
    const elGpu  = document.getElementById('m-gpu');
    const elVram = document.getElementById('m-vram');
    const elLine = document.getElementById('m-spark-line');
    if (!elLat || !elCpu || !elRam || !elLine) return;

    const poll = async () => {
        try {
            const ctrl = new AbortController();
            const tid  = setTimeout(() => ctrl.abort(), 2000);
            const res  = await fetch('http://127.0.0.1:8000/metrics', { signal: ctrl.signal });
            clearTimeout(tid);
            const m = await res.json();

            elCpu.textContent  = m.cpu_pct  != null ? `${Math.round(m.cpu_pct)}%`  : '—';
            elRam.textContent  = m.ram_pct  != null ? `${Math.round(m.ram_pct)}%`  : '—';
            if (elGpu)  elGpu.textContent  = m.gpu_pct  != null ? `${m.gpu_pct}%`  : '—';
            if (elVram) elVram.textContent = m.vram_pct != null ? `${m.vram_pct}%` : '—';

            if (m.latencia_ms != null) {
                elLat.textContent = `${m.latencia_ms}ms`;
                _latHistory.push(m.latencia_ms);
                if (_latHistory.length > _LAT_HISTORY_MAX) _latHistory.shift();
                _drawSparkline(elLine);
            } else {
                elLat.textContent = '—';
            }
        } catch (_) {
            elLat.textContent = elCpu.textContent = elRam.textContent = '—';
        }
    };

    poll();
    setInterval(poll, 4000);
}

/* --------------------------------------------------------------------------
   PAINEL — TELEMETRIA (distribuição de uso da cascata) + SAÚDE DOS SERVIÇOS
   Poll de /stats e /health a cada 10s — dados mudam devagar, sem pressa.
   -------------------------------------------------------------------------- */
function _setupHealth() {
    const elTotal = document.getElementById('t-total');
    const elTiers = document.getElementById('t-tiers');
    const elHist  = document.getElementById('t-hist-spark-line');

    const pollStats = async () => {
        try {
            const ctrl = new AbortController();
            const tid  = setTimeout(() => ctrl.abort(), 2500);
            const res  = await fetch('http://127.0.0.1:8000/stats', { signal: ctrl.signal });
            clearTimeout(tid);
            const s = await res.json();
            if (elTotal) elTotal.textContent = s.total_chats ?? '0';
            if (elTiers && s.tiers) {
                const ordem = ['Groq', 'Gemini', 'Claude', 'Local'];
                elTiers.innerHTML = ordem
                    .filter(n => s.tiers[n])
                    .map(n => {
                        const t = s.tiers[n];
                        const pct = s.distribuicao_pct?.[n] ?? 0;
                        const lat = t.latencia_media_ms != null ? `${t.latencia_media_ms}ms` : '—';
                        return `<div class="tier-mini" data-tip="${t.usos} usos · ${t.falhas} falhas · ${lat}">
                                  <div class="tier-mini-top"><span>${n}</span><span>${pct}%</span></div>
                                  <div class="tier-mini-bar"><span style="width:${pct}%"></span></div>
                                </div>`;
                    }).join('');
            }
        } catch (_) {}
    };

    const pollHealth = async () => {
        try {
            const ctrl = new AbortController();
            const tid  = setTimeout(() => ctrl.abort(), 3000);
            const res  = await fetch('http://127.0.0.1:8000/health', { signal: ctrl.signal });
            clearTimeout(tid);
            const h = await res.json();
            _svcDot('qdrant',  h.qdrant?.ok,  `Qdrant ${h.qdrant?.latencia_ms ?? '—'}ms`);
            _svcDot('surreal', h.surreal?.ok, `Surreal ${h.surreal?.latencia_ms ?? '—'}ms`);
            _svcDot('ollama',  h.ollama?.ok,  `Ollama ${h.ollama?.latencia_ms ?? '—'}ms`);
        } catch (_) {
            ['qdrant','surreal','ollama'].forEach(s => _svcDot(s, false, `${s.charAt(0).toUpperCase()+s.slice(1)} off`));
        }
    };

    // Histórico (snapshots ~5min do loop_proativo) — muda devagar, poll bem menos frequente.
    const pollHistorico = async () => {
        if (!elHist) return;
        try {
            const ctrl = new AbortController();
            const tid  = setTimeout(() => ctrl.abort(), 3000);
            const res  = await fetch('http://127.0.0.1:8000/stats/historico?limite=48', { signal: ctrl.signal });
            clearTimeout(tid);
            const { snapshots } = await res.json();
            _drawHistoricoSparkline(elHist, (snapshots || []).map(s => s.total_chats || 0));
        } catch (_) {}
    };

    const tick = () => { pollStats(); pollHealth(); };
    tick();
    setInterval(tick, 10000);
    pollHistorico();
    setInterval(pollHistorico, 60000);
}

function _svcDot(svc, online, label) {
    const dot = document.getElementById(`dot-${svc}`);
    const txt = document.getElementById(`svc-${svc}`);
    if (dot) {
        const col = online ? '#00FF99' : '#FF3355';
        dot.style.background = col;
        dot.style.boxShadow  = `0 0 5px ${col}`;
    }
    if (txt) txt.textContent = label;
}

function _drawSparkline(elLine) {
    if (_latHistory.length < 2) { elLine.setAttribute('points', ''); return; }
    const w = 200, h = 32;
    const max = Math.max(..._latHistory, 1);
    const min = Math.min(..._latHistory);
    const span = Math.max(max - min, 1);
    const step = w / (_LAT_HISTORY_MAX - 1);
    const pts = _latHistory.map((v, i) => {
        const x = i * step;
        const y = h - 2 - ((v - min) / span) * (h - 4);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    elLine.setAttribute('points', pts);
}

function _drawHistoricoSparkline(elLine, valores) {
    if (!valores || valores.length < 2) { elLine.setAttribute('points', ''); return; }
    const w = 200, h = 32;
    const max = Math.max(...valores, 1);
    const min = Math.min(...valores);
    const span = Math.max(max - min, 1);
    const step = w / (valores.length - 1);
    const pts = valores.map((v, i) => {
        const x = i * step;
        const y = h - 2 - ((v - min) / span) * (h - 4);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    elLine.setAttribute('points', pts);
}

/* --------------------------------------------------------------------------
   CHAT — TERMINAL HISTÓRICO ACUMULATIVO
   -------------------------------------------------------------------------- */
let _currentSlowHintEl = null;

function _armSlowHint() {
    _disarmSlowHint();
    _slowTimer = setTimeout(() => {
        _currentSlowHintEl?.classList.add('show');
    }, _SLOW_THRESHOLD_MS);
}
function _disarmSlowHint() {
    if (_slowTimer) { clearTimeout(_slowTimer); _slowTimer = null; }
    _currentSlowHintEl?.classList.remove('show');
}

function _showTyping() {
    const container = document.getElementById('chat-messages');
    if (!container) return;
    while (container.children.length >= _MAX_MSGS) container.removeChild(container.firstChild);

    const row    = document.createElement('div');
    row.className = 'msg-lyra-row';
    const avatar = document.createElement('div');
    avatar.className = 'chat-avatar';
    const col    = document.createElement('div');
    col.className = 'msg-lyra-col';

    _currentLyraMsgEl = document.createElement('div');
    _currentLyraMsgEl.className = 'msg msg-lyra typing-indicator';
    _currentLyraMsgEl.innerHTML = '<span></span><span></span><span></span>';

    const time = document.createElement('div');
    time.className = 'msg-time';
    time.textContent = new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });

    _currentSlowHintEl = document.createElement('div');
    _currentSlowHintEl.className = 'msg-slow-hint';
    _currentSlowHintEl.textContent = 'ainda processando…';

    col.appendChild(_currentLyraMsgEl);
    col.appendChild(time);
    col.appendChild(_currentSlowHintEl);
    row.appendChild(avatar);
    row.appendChild(col);
    container.appendChild(row);

    requestAnimationFrame(() => _currentLyraMsgEl.classList.add('visible'));
    _pendingNewLyraMsg = false;
    _playMsgChime();
    if (!_chatOpen) _setChatBadge(true);
    _scrollChat(true);
}

/* --------------------------------------------------------------------------
   MARKDOWN LEVE — apenas o essencial (negrito, itálico, código, listas)
   Escapa HTML primeiro pra evitar que texto do usuário/modelo injete tags.
   -------------------------------------------------------------------------- */
function _escapeHtml(s) {
    return s.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
}

function _renderMarkdown(raw) {
    const blocks = raw.split(/```([\s\S]*?)```/g);
    let html = '';
    for (let i = 0; i < blocks.length; i++) {
        if (i % 2 === 1) {
            html += `<pre><code>${_escapeHtml(blocks[i].replace(/^\w*\n/, ''))}</code></pre>`;
            continue;
        }
        let seg = _escapeHtml(blocks[i]);
        // Imagem inline (gerar_imagem devolve ![desc](url) na resposta) —
        // precisa vir antes do `código` pra não confundir com crase.
        seg = seg.replace(/!\[([^\]]*)\]\((https?:\/\/[^\s)]+)\)/g,
            '<img src="$2" alt="$1" class="msg-img" loading="lazy" onclick="window.open(this.src)">');
        seg = seg.replace(/`([^`]+)`/g, '<code>$1</code>');
        seg = seg.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        seg = seg.replace(/(?<![\w*])\*([^*\n]+)\*(?![\w*])/g, '<em>$1</em>');

        const lines = seg.split('\n');
        let out = '', inList = false, firstTextLine = true;
        for (const line of lines) {
            const m = line.match(/^\s*[-*]\s+(.*)/);
            if (m) {
                if (!inList) { out += '<ul>'; inList = true; }
                out += `<li>${m[1]}</li>`;
            } else {
                if (inList) { out += '</ul>'; inList = false; firstTextLine = true; }
                out += (firstTextLine ? '' : '<br>') + line;
                firstTextLine = false;
            }
        }
        if (inList) out += '</ul>';
        html += out;
    }
    return html;
}

function _addCopyButton(bubbleEl, textSpan) {
    const btn = document.createElement('div');
    btn.className = 'msg-copy';
    btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/></svg>';
    btn.addEventListener('click', e => {
        e.stopPropagation();
        navigator.clipboard?.writeText(textSpan.textContent || '').then(() => {
            btn.classList.add('copied');
            setTimeout(() => btn.classList.remove('copied'), 900);
        }).catch(() => {});
    });
    bubbleEl.appendChild(btn);
}

function _addSpeakButton(bubbleEl, textSpan) {
    const btn = document.createElement('div');
    btn.className = 'msg-speak';
    btn.setAttribute('data-tip', 'Reler em voz alta');
    btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5 6 9H2v6h4l5 4V5Z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/></svg>';
    btn.addEventListener('click', e => {
        e.stopPropagation();
        const txt = (textSpan.textContent || '').trim();
        if (!txt) return;
        btn.classList.add('speaking');
        setTimeout(() => btn.classList.remove('speaking'), 1200);
        fetch('http://127.0.0.1:8000/tts/falar', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ texto: txt }),
        }).catch(() => {});
    });
    bubbleEl.appendChild(btn);
}

function _showBubble(who, text) {
    const container = document.getElementById('chat-messages');
    if (!container) return;

    if (who === 'user') {
        while (container.children.length >= _MAX_MSGS) container.removeChild(container.firstChild);
        const el = document.createElement('div');
        el.className = 'msg msg-user';
        const textSpan = document.createElement('span');
        textSpan.className = 'msg-text';
        textSpan.textContent = text;
        el.appendChild(textSpan);
        _addCopyButton(el, textSpan);
        container.appendChild(el);
        requestAnimationFrame(() => el.classList.add('visible'));
        if (!_chatOpen) _setChatBadge(true);
        _scrollChat(true);

    } else if (who === 'lyra') {
        _disarmSlowHint();
        if (_pendingNewLyraMsg || !_currentLyraMsgEl) {
            while (container.children.length >= _MAX_MSGS) container.removeChild(container.firstChild);

            const row = document.createElement('div');
            row.className = 'msg-lyra-row';

            const avatar = document.createElement('div');
            avatar.className = 'chat-avatar';

            const col = document.createElement('div');
            col.className = 'msg-lyra-col';

            _currentLyraMsgEl = document.createElement('div');
            _currentLyraMsgEl.className = 'msg msg-lyra';

            const time = document.createElement('div');
            time.className = 'msg-time';
            time.textContent = new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });

            col.appendChild(_currentLyraMsgEl);
            col.appendChild(time);
            row.appendChild(avatar);
            row.appendChild(col);
            container.appendChild(row);

            requestAnimationFrame(() => _currentLyraMsgEl.classList.add('visible'));
            _pendingNewLyraMsg = false;
        }
        if (_currentLyraMsgEl.classList.contains('typing-indicator') || !_currentLyraMsgEl.querySelector('.msg-text')) {
            _currentLyraMsgEl.classList.remove('typing-indicator');
            _currentLyraMsgEl.innerHTML = '';
            const textSpan = document.createElement('span');
            textSpan.className = 'msg-text';
            _currentLyraMsgEl.appendChild(textSpan);
            _addCopyButton(_currentLyraMsgEl, textSpan);
            _addSpeakButton(_currentLyraMsgEl, textSpan);
        }
        _currentLyraMsgEl.querySelector('.msg-text').innerHTML = _renderMarkdown(text);
        _scrollChat();
    }
}

function _hideBubble(who) {
    if (who === 'lyra') {
        _pendingNewLyraMsg = true;
        _currentLyraMsgEl  = null;
    }
}

function _hideAll() {
    _lyraFull  = '';
    _hideTimer = null;
}

const _SCROLL_NEAR_BOTTOM_PX = 48;

function _scrollChat(force) {
    const c = document.getElementById('chat-messages');
    if (!c) return;
    const nearBottom = c.scrollHeight - c.scrollTop - c.clientHeight < _SCROLL_NEAR_BOTTOM_PX;
    if (force || nearBottom) c.scrollTop = c.scrollHeight;
    _updateScrollBtn();
}

function _updateScrollBtn() {
    const c   = document.getElementById('chat-messages');
    const btn = document.getElementById('chat-scroll-btn');
    if (!c || !btn) return;
    const nearBottom = c.scrollHeight - c.scrollTop - c.clientHeight < _SCROLL_NEAR_BOTTOM_PX;
    btn.classList.toggle('show', !nearBottom && c.scrollHeight > c.clientHeight);
}

function _setupChatScroll() {
    document.getElementById('chat-messages')?.addEventListener('scroll', _updateScrollBtn);
}

/* --------------------------------------------------------------------------
   INPUT DE TEXTO
   -------------------------------------------------------------------------- */
function _setupInput() {
    const inp = document.getElementById('lyra-input');

    document.addEventListener('contextmenu', e => e.preventDefault());

    document.addEventListener('keydown', e => {
        // Escape: fecha na ordem de empilhamento — grafo (overlay por cima de
        // tudo) > chat > painel. Sem a checagem do grafo, Esc fechava o chat
        // escondido ATRÁS do grafo e o overlay ficava sem resposta visível.
        if (e.key === 'Escape') {
            const grafo = document.getElementById('grafo-overlay');
            if (grafo?.classList.contains('open')) { fecharGrafo(); return; }
            window.LyraUI?.escapeView();   // fecha a view atual (chat/config/integrações) → home
            return;
        }
        // "/" abre o chat e foca o input (se não estiver já digitando em algum campo)
        const digitando = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName);
        if (e.key === '/' && !_chatOpen && !digitando) {
            e.preventDefault();
            toggleChat(true);
        }
    });

    inp.addEventListener('keydown', e => {
        // ↑/↓ navegam o histórico de enviadas (estilo terminal). Só entra no
        // histórico com ↑ se o cursor está no input vazio OU já navegando —
        // não rouba a seta de quem está editando texto novo.
        if (e.key === 'ArrowUp' && _histInput.length
            && (!inp.value || _histIdx < _histInput.length)) {
            e.preventDefault();
            if (_histIdx === _histInput.length) _histDraft = inp.value;
            if (_histIdx > 0) _histIdx--;
            inp.value = _histInput[_histIdx];
            return;
        }
        if (e.key === 'ArrowDown' && _histIdx < _histInput.length) {
            e.preventDefault();
            _histIdx++;
            inp.value = _histIdx === _histInput.length ? _histDraft : _histInput[_histIdx];
            return;
        }
        if (e.key !== 'Enter') return;
        const v = inp.value.trim();
        if (!v) return;
        inp.value = '';
        // Evita duplicata consecutiva no histórico (mandar "sim" 3x = 1 entrada)
        if (_histInput[_histInput.length - 1] !== v) {
            _histInput.push(v);
            if (_histInput.length > _HIST_INPUT_MAX) _histInput.shift();
        }
        _histIdx = _histInput.length;
        _histDraft = '';
        _playSendTick();
        _enviarComando(v);
    });

    // Colar imagem direto no campo de chat (ex: print copiado) — sobe pro
    // backend e já manda como mensagem, sem precisar do botão de anexo.
    inp.addEventListener('paste', e => {
        const items = e.clipboardData?.items;
        if (!items) return;
        for (const item of items) {
            if (item.type && item.type.startsWith('image/')) {
                e.preventDefault();
                const file = item.getAsFile();
                if (file) window.handleFileAttach([file]);
                return;
            }
        }
    });
}

function _enviarComando(v) {
    if (!v || !v.trim()) return;
    const elFonte = document.getElementById('p-fonte-label');
    if (elFonte) elFonte.textContent = '…';
    if (window.pywebview?.api) {
        const modelo = document.getElementById('sel-modelo')?.value || 'auto';
        window.pywebview.api.process_command(v, modelo);
    } else {
        _showBubble('user', v);
        console.log('[Lyra] pywebview não disponível — modo browser.');
    }
}

/* --------------------------------------------------------------------------
   ANEXAR ARQUIVO (imagem/áudio/vídeo) — botão de clipe ou colar no input.
   Sobe pro /upload do cerebro_maestro e manda uma mensagem de chat normal
   referenciando o caminho salvo; o modelo decide chamar analisar_imagem ou
   transcrever_audio dependendo do tipo.
   -------------------------------------------------------------------------- */
// Arrastar arquivo de qualquer lugar da janela → anexa como se fosse pelo
// clipe. Aceita os mesmos tipos do input #file-attach (imagem/áudio/vídeo).
function _setupDragDrop() {
    const chat = document.getElementById('chat-terminal');
    let _dragDepth = 0;   // dragenter/leave disparam por elemento filho — conta profundidade

    document.addEventListener('dragover', e => e.preventDefault());
    document.addEventListener('dragenter', e => {
        e.preventDefault();
        if (!e.dataTransfer?.types?.includes('Files')) return;
        _dragDepth++;
        chat?.classList.add('drag-over');
    });
    document.addEventListener('dragleave', e => {
        e.preventDefault();
        if (--_dragDepth <= 0) { _dragDepth = 0; chat?.classList.remove('drag-over'); }
    });
    document.addEventListener('drop', e => {
        e.preventDefault();
        _dragDepth = 0;
        chat?.classList.remove('drag-over');
        const file = [...(e.dataTransfer?.files || [])].find(f =>
            /^(image|audio)\//.test(f.type) ||
            ['video/mp4', 'video/quicktime', 'video/webm'].includes(f.type));
        if (!file) { _showToast?.('Tipo de arquivo não suportado (imagem/áudio/vídeo).'); return; }
        if (!_chatOpen) toggleChat(true);
        window.handleFileAttach([file]);
    });
}

window.handleFileAttach = async (files) => {
    const file = files?.[0];
    if (!file) return;
    const fileInput = document.getElementById('file-attach');
    const btnAttach = document.getElementById('btn-attach');

    btnAttach?.classList.add('uploading');
    _showToast?.(`Enviando ${file.name}…`);
    try {
        const form = new FormData();
        form.append('file', file);
        const res = await fetch('http://127.0.0.1:8000/upload', { method: 'POST', body: form });
        const r = await res.json();
        if (!r.ok) throw new Error(r.erro || 'falha no upload');

        const ehImagem = file.type.startsWith('image/');
        const verbo = ehImagem
            ? 'O que tem nessa imagem que anexei (use analisar_imagem)'
            : 'Transcreva esse áudio/vídeo que anexei (use transcrever_audio)';
        _enviarComando(`${verbo}: ${r.path}`);
    } catch (e) {
        _showToast?.('Falha ao enviar arquivo: ' + e.message);
        console.error('[Lyra] upload erro:', e);
    } finally {
        if (fileInput) fileInput.value = '';
        btnAttach?.classList.remove('uploading');
    }
};

/* --------------------------------------------------------------------------
   CONTROLES DE JANELA
   -------------------------------------------------------------------------- */
const _api = () => window.pywebview?.api;

const _CLOSE_FADE_MS = 460;
window.closeLyra = () => {
    const overlay = document.getElementById('close-overlay');
    overlay?.classList.add('show');
    setTimeout(() => { _api()?.close_app() ?? window.close(); }, _CLOSE_FADE_MS);
};
window.maximizeLyra = () => _api()?.toggle_maximize?.();
window.minimizeLyra = () => _api()?.minimize_app?.();

/* ── Mudo (resposta por voz) ──────────────────────────────────────────────
   Estado vive no backend (cerebro_maestro :8000) — é ele quem chama
   audio_manager.falar(), não o frontend. O botão só liga/desliga via HTTP e
   reflete o estado salvo em localStorage pra já nascer correto no boot. */
let _ttsMudo = localStorage.getItem('lyra_tts_mudo') === '1';

function _applyMuteIcon() {
    document.getElementById('btn-mute')?.classList.toggle('muted', _ttsMudo);
    document.getElementById('mute-slash')?.setAttribute('style', _ttsMudo ? '' : 'display:none');
}

async function _syncTtsMudo(valor) {
    try {
        await fetch('http://127.0.0.1:8000/tts/mudo', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mudo: valor }),
        });
    } catch (_) { /* cérebro offline — aplica local mesmo assim, sincroniza quando voltar */ }
}

window.toggleTtsMute = () => {
    _ttsMudo = !_ttsMudo;
    localStorage.setItem('lyra_tts_mudo', _ttsMudo ? '1' : '0');
    _applyMuteIcon();
    _syncTtsMudo(_ttsMudo);
    _playSendTick?.();
};

_applyMuteIcon();
_syncTtsMudo(_ttsMudo);

function _onResize() {
    camera.aspect = innerWidth / innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(innerWidth, innerHeight);
}

/* --------------------------------------------------------------------------
   ÁUDIO — tons sintetizados via Web Audio API (sem arquivos externos)
   Navegadores/webviews bloqueiam áudio antes do primeiro gesto do
   usuário; o chime de boot pode não tocar na 1ª abertura por isso —
   é esperado, não é bug. Sons seguintes (mensagens) já têm gesto prévio.
   -------------------------------------------------------------------------- */
let _audioCtx = null;
function _getAudioCtx() {
    if (!_audioCtx) {
        try { _audioCtx = new (window.AudioContext || window.webkitAudioContext)(); }
        catch (_) { _audioCtx = null; }
    }
    return _audioCtx;
}
document.addEventListener('pointerdown', () => { _getAudioCtx()?.resume(); }, { once: true });
document.addEventListener('keydown',     () => { _getAudioCtx()?.resume(); }, { once: true });

function _playTone({ freq = 440, glideTo = null, duration = 0.3, type = 'sine', volume = 0.04, delay = 0 }) {
    const ctx = _getAudioCtx();
    if (!ctx) return;
    const t0   = ctx.currentTime + delay;
    const osc  = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, t0);
    if (glideTo) osc.frequency.exponentialRampToValueAtTime(glideTo, t0 + duration);
    gain.gain.setValueAtTime(0.0001, t0);
    gain.gain.linearRampToValueAtTime(volume, t0 + 0.025);
    gain.gain.exponentialRampToValueAtTime(0.0001, t0 + duration);
    osc.connect(gain).connect(ctx.destination);
    osc.start(t0);
    osc.stop(t0 + duration + 0.05);
}

function _playBootChime() {
    _playTone({ freq: 220, glideTo: 440, duration: 0.9, type: 'sine',   volume: 0.05 });
    _playTone({ freq: 440, duration: 0.6, type: 'sine',                volume: 0.028, delay: 0.12 });
}

function _playMsgChime() {
    _playTone({ freq: 780, glideTo: 980, duration: 0.16, type: 'sine', volume: 0.032 });
}

function _playSendTick() {
    _playTone({ freq: 540, duration: 0.08, type: 'sine', volume: 0.022 });
}

/* --------------------------------------------------------------------------
   SEQUÊNCIA DE BOOT
   Linhas de log são "digitadas" em cadência, depois a marca Lyra surge
   por um instante, e por fim o overlay some revelando o núcleo já
   brotando (curScale parte de 0.001) com um flash de glow sincronizado.
   -------------------------------------------------------------------------- */
const _wait = ms => new Promise(r => setTimeout(r, ms));

function _typeText(el, text, speed = 26) {
    return new Promise(resolve => {
        let i = 0;
        const tick = () => {
            el.textContent = text.slice(0, ++i);
            if (i < text.length) setTimeout(tick, speed);
            else resolve();
        };
        tick();
    });
}

async function _runBootSequence() {
    const overlay = document.getElementById('boot-overlay');
    const linesEl  = document.getElementById('boot-lines');
    const brandEl  = document.getElementById('boot-brand');
    if (!overlay || !linesEl || !brandEl) return;

    const LOG = [
        'núcleo lyra · inicializando',
        'sincronizando memória',
        'conexão neural estabelecida',
    ];

    for (const text of LOG) {
        linesEl.innerHTML = '';
        const span = document.createElement('div');
        span.className = 'boot-line visible typing';
        linesEl.appendChild(span);
        await _typeText(span, text);
        span.classList.remove('typing');
        await _wait(280);
    }

    await _wait(160);
    linesEl.innerHTML = '';
    document.getElementById('boot-dot')?.style.setProperty('opacity', '0');
    brandEl.classList.add('visible');
    await _wait(620);

    bootFlashT = 0;               // dispara o flash de glow do núcleo
    _playBootChime();
    overlay.classList.add('hide');
    setTimeout(() => overlay.remove(), 750);
}

/* --------------------------------------------------------------------------
   START
   -------------------------------------------------------------------------- */
_setState('idle');
init();
_runBootSequence();
