import { useEffect, useRef, useState } from 'react';
import Markdown from './Markdown';
import Orb from './Orb';
import { uploadArquivo } from '../api';

export interface Message {
  role: 'user' | 'lyra';
  body: string;
  tier?: string;
  timestamp?: string;
}

function formatTime(ts?: string): string {
  if (!ts) return '';
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
}

interface ChatProps {
  title: string;
  messages: Message[];
  sending: boolean;
  model: string;
  onModelChange: (m: string) => void;
  ttsMuted: boolean;
  onToggleTts: () => void;
  onSend: (texto: string) => void;
  onRetry: () => void;
  onStop: () => void;
  onToggleChrome: () => void;
}

const MODELS = [
  { value: 'auto', label: 'Auto' },
  { value: 'groq', label: 'Groq' },
  { value: 'gemini', label: 'Gemini' },
  { value: 'claude', label: 'Claude' },
  { value: 'local', label: 'Local' },
];

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="copy-btn"
      onClick={() => {
        navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
    >
      {copied ? 'Copied' : 'Copy'}
    </button>
  );
}

export default function Chat({
  title, messages, sending, model, onModelChange, ttsMuted, onToggleTts,
  onSend, onRetry, onStop, onToggleChrome,
}: ChatProps) {
  const [draft, setDraft] = useState('');
  const [uploading, setUploading] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  useEffect(() => {
    if (!sending) textareaRef.current?.focus();
  }, [sending]);

  function submit() {
    const texto = draft.trim();
    if (!texto || sending) return;
    onSend(texto);
    setDraft('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
  }

  function handleInput(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setDraft(e.target.value);
    const el = e.target;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  }

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setUploading(true);
    try {
      const res = await uploadArquivo(file);
      if (res.ok) {
        setDraft((d) => (d ? `${d}\n${res.path}` : res.path));
        textareaRef.current?.focus();
      }
    } catch {
      /* backend fora do ar */
    } finally {
      setUploading(false);
    }
  }

  const lastLyraEmpty = messages.length > 0
    && messages[messages.length - 1].role === 'lyra'
    && messages[messages.length - 1].body === ''
    && !messages[messages.length - 1].tier;

  const lastLyraIndex = (() => {
    for (let i = messages.length - 1; i >= 0; i--) if (messages[i].role === 'lyra') return i;
    return -1;
  })();

  return (
    <div className="main">
      <div className="chat-top">
        <span className="chat-top-title">{title}</span>
        <div className="chat-top-actions">
          <button className="icon-btn" title={ttsMuted ? 'Unmute voice' : 'Mute voice'} onClick={onToggleTts}>
            {ttsMuted ? '🔇' : '🔊'}
          </button>
          <select className="model-select" value={model} onChange={(e) => onModelChange(e.target.value)}>
            {MODELS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
          <button className="icon-btn" title="Toggle chrome" onClick={onToggleChrome}>⋯</button>
        </div>
      </div>
      <div className="chat-scroll" ref={scrollRef}>
        {messages.map((m, i) => (
          <div className={`msg-row ${m.role}`} key={i}>
            {m.role === 'lyra' ? (
              <div className="msg-col">
                <div className="msg-mark">
                  <Orb size={16} />
                  {m.tier && <div className="tool-chip">{m.tier}</div>}
                </div>
                {lastLyraEmpty && i === messages.length - 1 ? (
                  <div className="thinking-dots"><i /><i /><i /></div>
                ) : (
                  <>
                    <Markdown text={m.body} />
                    {m.body && (
                      <div className="msg-actions">
                        <CopyButton text={m.body} />
                        {i === lastLyraIndex && !sending && (
                          <button className="copy-btn retry-btn" onClick={onRetry}>↻ Retry</button>
                        )}
                        {m.timestamp && <span className="msg-time">{formatTime(m.timestamp)}</span>}
                      </div>
                    )}
                  </>
                )}
              </div>
            ) : (
              <div>
                <div className="msg-body user-msg">{m.body}</div>
                <div className="msg-actions">
                  <CopyButton text={m.body} />
                  {m.timestamp && <span className="msg-time">{formatTime(m.timestamp)}</span>}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
      <div className="chat-input-wrap">
        <div className="chat-input">
          <input ref={fileInputRef} type="file" hidden onChange={handleFile} />
          <button
            className="attach-btn"
            title="Attach file"
            disabled={uploading}
            onClick={() => fileInputRef.current?.click()}
          >
            {uploading ? '…' : '📎'}
          </button>
          <textarea
            ref={textareaRef}
            rows={1}
            placeholder="Talk to Lyra… (Shift+Enter for new line)"
            value={draft}
            onChange={handleInput}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); }
            }}
            autoFocus
          />
          {sending ? (
            <button className="stop-btn" title="Stop" onClick={onStop}>■</button>
          ) : (
            <button className="send-btn" onClick={submit}>↑</button>
          )}
        </div>
      </div>
    </div>
  );
}
