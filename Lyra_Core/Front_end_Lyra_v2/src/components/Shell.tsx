import { useEffect, useRef, useState } from 'react';
import Sidebar from './Sidebar';
import RightPanel from './RightPanel';
import Chat, { type Message } from './Chat';
import Orb from './Orb';
import SearchOverlay from './SearchOverlay';
import SettingsModal from './SettingsModal';
import {
  getHistorico, getSessoes, novaSessao, ativarSessao, renomearSessao, deletarSessao,
  enviarChat, setTtsMudo, type Sessao,
} from '../api';

function toMessage(role: string, content: string, timestamp?: string): Message {
  return { role: role === 'assistant' ? 'lyra' : 'user', body: content, timestamp };
}

const LS_MODEL = 'lyra_default_model';
const LS_TTS_MUTED = 'lyra_tts_muted';
const LS_NAME = 'lyra_display_name';
const LS_FONT_SIZE = 'lyra_font_size';
const LS_REDUCE_MOTION = 'lyra_reduce_motion';

const FONT_SIZES: Record<string, string> = { small: '0.85rem', medium: '0.92rem', large: '1.02rem' };

const SUGESTOES = [
  'O que você lembra da nossa última conversa?',
  'Qual o status do sistema agora?',
  'Como está o clima em Marília?',
];

export default function Shell() {
  const [chromeVisible, setChromeVisible] = useState(true);
  const [collapsed, setCollapsed] = useState(false);
  const [sessoes, setSessoes] = useState<Sessao[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [sending, setSending] = useState(false);
  const [model, setModel] = useState(() => localStorage.getItem(LS_MODEL) ?? 'auto');
  const [ttsMuted, setTtsMutedState] = useState(() => localStorage.getItem(LS_TTS_MUTED) === '1');
  const [searchOpen, setSearchOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [displayName, setDisplayName] = useState(() => localStorage.getItem(LS_NAME) ?? 'Antônio');
  const [fontSize, setFontSize] = useState<'small' | 'medium' | 'large'>(
    () => (localStorage.getItem(LS_FONT_SIZE) as 'small' | 'medium' | 'large') ?? 'medium',
  );
  const [reduceMotion, setReduceMotion] = useState(() => localStorage.getItem(LS_REDUCE_MOTION) === '1');
  const [emptyDraft, setEmptyDraft] = useState('');
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    document.documentElement.style.setProperty('--chat-font-size', FONT_SIZES[fontSize]);
  }, [fontSize]);

  useEffect(() => {
    document.documentElement.dataset.reduceMotion = reduceMotion ? '1' : '0';
  }, [reduceMotion]);

  async function refreshSessoes() {
    const { sessoes: lista } = await getSessoes();
    setSessoes(lista);
  }

  async function loadHistorico(sessaoId?: string) {
    const hist = await getHistorico(sessaoId);
    setMessages(hist.map((m) => toMessage(m.role, m.content, m.timestamp)));
    setCollapsed(hist.length > 0);
  }

  useEffect(() => {
    refreshSessoes().catch(() => {});
    loadHistorico().catch(() => {});
    setTtsMudo(ttsMuted).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleSelectSessao(sessaoId: string) {
    try {
      await ativarSessao(sessaoId);
      await refreshSessoes();
      await loadHistorico(sessaoId);
    } catch { /* backend fora do ar — mantém estado atual */ }
  }

  async function handleNewChat() {
    try {
      await novaSessao();
      await refreshSessoes();
      setMessages([]);
      setCollapsed(false);
    } catch { /* backend fora do ar — mantém estado atual */ }
  }

  async function handleRename(sessaoId: string, titulo: string) {
    if (!titulo.trim()) return;
    try {
      await renomearSessao(sessaoId, titulo.trim());
      await refreshSessoes();
    } catch { /* backend fora do ar — mantém estado atual */ }
  }

  async function handleDelete(sessaoId: string) {
    try {
      await deletarSessao(sessaoId);
      await refreshSessoes();
      await loadHistorico();
    } catch { /* backend fora do ar — mantém estado atual */ }
  }

  function handleToggleTts() {
    const next = !ttsMuted;
    setTtsMutedState(next);
    localStorage.setItem(LS_TTS_MUTED, next ? '1' : '0');
    setTtsMudo(next).catch(() => {});
  }

  function handleChangeModel(m: string) {
    setModel(m);
    localStorage.setItem(LS_MODEL, m);
  }

  function handleChangeDisplayName(n: string) {
    setDisplayName(n);
    localStorage.setItem(LS_NAME, n);
  }

  function handleChangeFontSize(s: 'small' | 'medium' | 'large') {
    setFontSize(s);
    localStorage.setItem(LS_FONT_SIZE, s);
  }

  function handleToggleReduceMotion() {
    const next = !reduceMotion;
    setReduceMotion(next);
    localStorage.setItem(LS_REDUCE_MOTION, next ? '1' : '0');
  }

  function streamReply(texto: string) {
    setSending(true);
    setCollapsed(true);

    const controller = new AbortController();
    abortRef.current = controller;

    enviarChat(texto, model, {
      onTier: (tier) => {
        setMessages((prev) => {
          const next = [...prev];
          next[next.length - 1] = { ...next[next.length - 1], tier: `via ${tier}` };
          return next;
        });
      },
      onText: (chunk) => {
        setMessages((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];
          next[next.length - 1] = { ...last, body: last.body + chunk };
          return next;
        });
      },
      onDone: () => { setSending(false); refreshSessoes().catch(() => {}); },
      onError: (err) => {
        setSending(false);
        if ((err as { name?: string })?.name !== 'AbortError') {
          setMessages((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            next[next.length - 1] = { ...last, body: last.body + '\n\n_(erro de conexão)_' };
            return next;
          });
        }
      },
    }, controller.signal);
  }

  function handleSend(texto: string) {
    setMessages((prev) => [...prev, { role: 'user', body: texto }, { role: 'lyra', body: '' }]);
    streamReply(texto);
  }

  function handleRetry() {
    if (sending) return;
    const lastUserIdx = messages.map((m) => m.role).lastIndexOf('user');
    if (lastUserIdx === -1) return;
    const texto = messages[lastUserIdx].body;
    setMessages((prev) => [...prev.slice(0, lastUserIdx + 1), { role: 'lyra', body: '' }]);
    streamReply(texto);
  }

  function handleStop() {
    abortRef.current?.abort();
    setSending(false);
  }

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setSearchOpen(true);
      }
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'o') {
        e.preventDefault();
        handleNewChat();
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const isEmpty = messages.length === 0;
  const tituloAtivo = sessoes.find((s) => s.ativa)?.titulo ?? 'Conversa';

  return (
    <div className="lyra-shell">
      <div className="ambient" />
      <div className="grain" />

      {chromeVisible && (
        <Sidebar
          collapsed={collapsed}
          onToggleCollapsed={() => setCollapsed((c) => !c)}
          sessoes={sessoes}
          onSelect={handleSelectSessao}
          onNewChat={handleNewChat}
          onRename={handleRename}
          onDelete={handleDelete}
          onOpenSearch={() => setSearchOpen(true)}
          onOpenSettings={() => setSettingsOpen(true)}
          displayName={displayName}
        />
      )}

      {isEmpty ? (
        <div className="orb-empty" style={{ width: '100%' }}>
          <div className="orb-canvas-wrap">
            <div className="orb-glow" />
            <Orb size={180} variant="centerpiece" />
          </div>
          <div className="hint">Ready when you are.</div>
          <div className="chat-input" style={{ width: 520, marginTop: '0.8rem' }}>
            <input
              placeholder="Talk to Lyra…"
              autoFocus
              value={emptyDraft}
              onChange={(e) => setEmptyDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && emptyDraft.trim()) {
                  handleSend(emptyDraft.trim());
                  setEmptyDraft('');
                }
              }}
            />
            <button
              className="send-btn"
              onClick={() => {
                if (emptyDraft.trim()) {
                  handleSend(emptyDraft.trim());
                  setEmptyDraft('');
                }
              }}
            >↑</button>
          </div>
          <div className="suggestions">
            {SUGESTOES.map((s) => (
              <button key={s} className="suggestion-chip" onClick={() => handleSend(s)}>{s}</button>
            ))}
          </div>
        </div>
      ) : (
        <Chat
          title={tituloAtivo}
          messages={messages}
          sending={sending}
          model={model}
          onModelChange={handleChangeModel}
          ttsMuted={ttsMuted}
          onToggleTts={handleToggleTts}
          onSend={handleSend}
          onRetry={handleRetry}
          onStop={handleStop}
          onToggleChrome={() => setChromeVisible((v) => !v)}
        />
      )}

      {chromeVisible && !isEmpty && <RightPanel />}

      {searchOpen && <SearchOverlay onClose={() => setSearchOpen(false)} />}
      {settingsOpen && (
        <SettingsModal
          ttsMuted={ttsMuted}
          onToggleTts={handleToggleTts}
          defaultModel={model}
          onChangeDefaultModel={handleChangeModel}
          onClearConversation={() => { setMessages([]); setCollapsed(false); }}
          displayName={displayName}
          onChangeDisplayName={handleChangeDisplayName}
          fontSize={fontSize}
          onChangeFontSize={handleChangeFontSize}
          reduceMotion={reduceMotion}
          onToggleReduceMotion={handleToggleReduceMotion}
          onClose={() => setSettingsOpen(false)}
        />
      )}
    </div>
  );
}
