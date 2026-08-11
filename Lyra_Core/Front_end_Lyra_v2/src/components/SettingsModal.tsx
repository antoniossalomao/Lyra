import { useEffect, useState } from 'react';
import { getInfo, getIntegracoes, exportarConversa, limparHistorico, type Integracao } from '../api';

interface SettingsModalProps {
  ttsMuted: boolean;
  onToggleTts: () => void;
  defaultModel: string;
  onChangeDefaultModel: (m: string) => void;
  onClearConversation: () => void;
  displayName: string;
  onChangeDisplayName: (n: string) => void;
  fontSize: 'small' | 'medium' | 'large';
  onChangeFontSize: (s: 'small' | 'medium' | 'large') => void;
  reduceMotion: boolean;
  onToggleReduceMotion: () => void;
  onClose: () => void;
}

const MODELS = [
  { value: 'auto', label: 'Auto (cascade)' },
  { value: 'groq', label: 'Groq' },
  { value: 'gemini', label: 'Gemini' },
  { value: 'claude', label: 'Claude' },
  { value: 'local', label: 'Local' },
];

const INTEGRACOES_LABEL: Record<string, string> = {
  telegram: 'Telegram bot',
  voz_live: 'Voice Live (Gemini)',
  mic: 'Mic wake-word',
  tts: 'Text-to-speech',
  enxame: 'Swarm agents',
  upload: 'File upload',
};

const TABS = ['Profile', 'Appearance', 'Model & voice', 'Connected apps', 'Data controls', 'Keyboard shortcuts', 'About'] as const;
type Tab = (typeof TABS)[number];

export default function SettingsModal({
  ttsMuted, onToggleTts, defaultModel, onChangeDefaultModel, onClearConversation,
  displayName, onChangeDisplayName, fontSize, onChangeFontSize, reduceMotion, onToggleReduceMotion,
  onClose,
}: SettingsModalProps) {
  const [tab, setTab] = useState<Tab>('Model & voice');
  const [info, setInfo] = useState<{ ativo: boolean; versao: string } | null>(null);
  const [integracoes, setIntegracoes] = useState<Record<string, Integracao> | null>(null);
  const [nameDraft, setNameDraft] = useState(displayName);

  useEffect(() => {
    getInfo().then(setInfo).catch(() => {});
  }, []);

  useEffect(() => {
    if (tab === 'Connected apps') {
      getIntegracoes().then(setIntegracoes).catch(() => {});
    }
  }, [tab]);

  async function handleExport() {
    try {
      const { markdown } = await exportarConversa();
      const blob = new Blob([markdown], { type: 'text/markdown' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `lyra-conversa-${new Date().toISOString().slice(0, 10)}.md`;
      a.click();
      URL.revokeObjectURL(url);
    } catch { /* backend fora do ar */ }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="settings-panel" onClick={(e) => e.stopPropagation()}>
        <nav className="settings-nav">
          <h2>Settings</h2>
          {TABS.map((t) => (
            <button
              key={t}
              className={`settings-nav-item${tab === t ? ' active' : ''}`}
              onClick={() => setTab(t)}
            >
              {t}
            </button>
          ))}
        </nav>

        <div className="settings-body">
          {tab === 'Profile' && (
            <>
              <h3>Profile</h3>
              <div className="settings-row">
                <span>Display name</span>
                <input
                  className="text-input"
                  value={nameDraft}
                  onChange={(e) => setNameDraft(e.target.value)}
                  onBlur={() => nameDraft.trim() && onChangeDisplayName(nameDraft.trim())}
                  onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
                />
              </div>
              <div className="settings-row">
                <span>Assistant</span>
                <span style={{ color: 'var(--text)' }}>Lyra AI</span>
              </div>
            </>
          )}

          {tab === 'Appearance' && (
            <>
              <h3>Appearance</h3>
              <div className="settings-row">
                <span>Theme</span>
                <span style={{ color: 'var(--text-faint)' }}>Dark (fixed)</span>
              </div>
              <div className="settings-row">
                <span>Message text size</span>
                <div className="size-picker">
                  {(['small', 'medium', 'large'] as const).map((s) => (
                    <button
                      key={s}
                      className={`size-btn${fontSize === s ? ' active' : ''}`}
                      onClick={() => onChangeFontSize(s)}
                      style={{ fontSize: s === 'small' ? '0.72rem' : s === 'medium' ? '0.86rem' : '1.02rem' }}
                      title={s}
                    >
                      Aa
                    </button>
                  ))}
                </div>
              </div>
              <div className="settings-row">
                <div>
                  <div>Reduce motion</div>
                  <div className="settings-row-desc">Turns off orb glow, message fade-in and other animations.</div>
                </div>
                <div className={`toggle${reduceMotion ? ' on' : ''}`} onClick={onToggleReduceMotion}><i /></div>
              </div>
            </>
          )}

          {tab === 'Model & voice' && (
            <>
              <h3>Model &amp; voice</h3>
              <div className="settings-row">
                <span>Voice replies (TTS)</span>
                <div className={`toggle${ttsMuted ? '' : ' on'}`} onClick={onToggleTts}><i /></div>
              </div>
              <div className="settings-row">
                <span>Default model</span>
                <select className="model-select" value={defaultModel} onChange={(e) => onChangeDefaultModel(e.target.value)}>
                  {MODELS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
                </select>
              </div>
            </>
          )}

          {tab === 'Connected apps' && (
            <>
              <h3>Connected apps</h3>
              {!integracoes && <div className="settings-row-desc">Loading…</div>}
              {integracoes && Object.entries(integracoes).map(([id, info2]) => (
                <div className="settings-row" key={id}>
                  <div className="integration-row">
                    <span className={`integration-dot${info2.online ? ' on' : ''}`} />
                    <div>
                      <div className="integration-name">{INTEGRACOES_LABEL[id] ?? id}</div>
                      <div className="integration-status">{info2.status}</div>
                    </div>
                  </div>
                </div>
              ))}
            </>
          )}

          {tab === 'Data controls' && (
            <>
              <h3>Data controls</h3>
              <div className="settings-row">
                <div>
                  <div>Export this conversation</div>
                  <div className="settings-row-desc">Downloads the current chat as markdown.</div>
                </div>
                <button className="settings-danger-btn" style={{ color: 'var(--neon)', borderColor: 'var(--border)' }} onClick={handleExport}>
                  Export
                </button>
              </div>
              <div className="settings-row">
                <div>
                  <div>Clear this conversation</div>
                  <div className="settings-row-desc">Wipes in-memory history only — long-term memory (SurrealDB/Qdrant) is untouched.</div>
                </div>
                <button
                  className="settings-danger-btn"
                  onClick={async () => { await limparHistorico(); onClearConversation(); }}
                >
                  Clear
                </button>
              </div>
            </>
          )}

          {tab === 'Keyboard shortcuts' && (
            <>
              <h3>Keyboard shortcuts</h3>
              <div className="settings-row"><span>Send message</span><span className="kbd">Enter</span></div>
              <div className="settings-row"><span>New line</span><span className="kbd">Shift+Enter</span></div>
              <div className="settings-row"><span>Search memory</span><span className="kbd">Ctrl+K</span></div>
              <div className="settings-row"><span>New chat</span><span className="kbd">Ctrl+Shift+O</span></div>
            </>
          )}

          {tab === 'About' && (
            <>
              <h3>About</h3>
              <div className="settings-row">
                <span>Cérebro Maestro</span>
                <span>{info ? `v${info.versao} · ${info.ativo ? 'online' : 'offline'}` : '—'}</span>
              </div>
              <div className="settings-row">
                <span>System dashboard</span>
                <a href="http://127.0.0.1:8000/dashboard" style={{ color: 'var(--neon)', fontSize: '0.78rem' }}>
                  Open ↗
                </a>
              </div>
            </>
          )}
        </div>

        <button className="settings-close" onClick={onClose}>✕</button>
      </div>
    </div>
  );
}
