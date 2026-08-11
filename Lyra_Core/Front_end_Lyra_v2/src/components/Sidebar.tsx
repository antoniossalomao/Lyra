import { useState } from 'react';
import Orb from './Orb';
import type { Sessao } from '../api';

interface SidebarProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
  sessoes: Sessao[];
  onSelect: (sessaoId: string) => void;
  onNewChat: () => void;
  onRename: (sessaoId: string, titulo: string) => void;
  onDelete: (sessaoId: string) => void;
  onOpenSearch: () => void;
  onOpenSettings: () => void;
  displayName: string;
}

function agruparPorData(sessoes: Sessao[]): [string, Sessao[]][] {
  const hoje = new Date(); hoje.setHours(0, 0, 0, 0);
  const ontem = new Date(hoje); ontem.setDate(ontem.getDate() - 1);
  const semana = new Date(hoje); semana.setDate(semana.getDate() - 7);
  const grupos: Record<string, Sessao[]> = { Today: [], Yesterday: [], 'This week': [], Older: [] };
  for (const s of sessoes) {
    if (s.sessao_id === 'legado') { grupos.Older.push(s); continue; }
    const d = new Date(s.criada);
    if (d >= hoje) grupos.Today.push(s);
    else if (d >= ontem) grupos.Yesterday.push(s);
    else if (d >= semana) grupos['This week'].push(s);
    else grupos.Older.push(s);
  }
  return Object.entries(grupos).filter(([, v]) => v.length > 0);
}

export default function Sidebar({
  collapsed, onToggleCollapsed, sessoes, onSelect, onNewChat,
  onRename, onDelete, onOpenSearch, onOpenSettings, displayName,
}: SidebarProps) {
  const [renaming, setRenaming] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const grupos = agruparPorData(sessoes);

  return (
    <aside className={`sb${collapsed ? ' collapsed' : ''}`}>
      <div className="sb-head">
        <Orb size={20} />
        {!collapsed && <div className="sb-brand">Lyra <span>AI</span></div>}
        <button
          className="ide-open-btn"
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          onClick={onToggleCollapsed}
          style={collapsed ? { marginLeft: 0 } : undefined}
        >
          ☰
        </button>
      </div>

      <button className="sb-new" title="New chat" onClick={onNewChat}>
        ＋{!collapsed && <span>&nbsp;New chat</span>}
      </button>
      <button className="sb-new" title="Search memory" onClick={onOpenSearch} style={{ marginTop: 0 }}>
        🔍{!collapsed && <span>&nbsp;Search memory</span>}
      </button>

      {collapsed ? (
        <div className="rail-spacer" />
      ) : (
        <div className="sb-convs">
          {grupos.map(([label, itens]) => (
            <div key={label}>
              <div className="sb-section-label">{label}</div>
              {itens.map((s) => (
                <div
                  key={s.sessao_id}
                  className={`sb-conv${s.ativa ? ' active' : ''}`}
                  onClick={() => onSelect(s.sessao_id)}
                  style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.4rem' }}
                >
                  {renaming === s.sessao_id ? (
                    <input
                      autoFocus
                      value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      onClick={(e) => e.stopPropagation()}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') { onRename(s.sessao_id, draft); setRenaming(null); }
                        if (e.key === 'Escape') setRenaming(null);
                      }}
                      onBlur={() => setRenaming(null)}
                      style={{
                        background: 'var(--surface-2)', border: '1px solid var(--border)', borderRadius: 5,
                        color: 'var(--text)', fontSize: '0.78rem', fontFamily: 'inherit',
                        padding: '0.15rem 0.4rem', width: '100%',
                      }}
                    />
                  ) : (
                    <>
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0, flex: 1 }}>
                        {s.titulo}
                      </span>
                      {!s.somente_leitura && (
                        <span className="sb-conv-actions" style={{ display: 'flex', gap: '0.3rem', flexShrink: 0 }}>
                          <button
                            className="copy-btn"
                            title="Rename"
                            onClick={(e) => { e.stopPropagation(); setDraft(s.titulo); setRenaming(s.sessao_id); }}
                          >✎</button>
                          <button
                            className="copy-btn"
                            title="Delete"
                            onClick={(e) => { e.stopPropagation(); if (confirm(`Delete "${s.titulo}"?`)) onDelete(s.sessao_id); }}
                          >🗑</button>
                        </span>
                      )}
                    </>
                  )}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}

      <div className="sb-foot" style={collapsed ? { justifyContent: 'center' } : undefined}>
        <button className="account-chip" title="Settings" onClick={onOpenSettings} style={collapsed ? { flex: 'none', padding: 0 } : undefined}>
          <span className="account-avatar">{displayName.charAt(0).toUpperCase()}</span>
          {!collapsed && <span className="account-name">{displayName}</span>}
        </button>
      </div>
    </aside>
  );
}
