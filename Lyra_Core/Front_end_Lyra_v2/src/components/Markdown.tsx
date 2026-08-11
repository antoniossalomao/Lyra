import { useMemo } from 'react';
import { marked, type Tokens } from 'marked';
import DOMPurify from 'dompurify';

marked.setOptions({ breaks: true });

const renderer = new marked.Renderer();
renderer.code = ({ text, lang }: Tokens.Code) => {
  const escaped = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return `<div class="code-block"><div class="code-block-head"><span>${lang || ''}</span><button class="code-copy-btn" type="button">Copy</button></div><pre><code>${escaped}</code></pre></div>`;
};

export default function Markdown({ text }: { text: string }) {
  const html = useMemo(() => {
    const raw = marked.parse(text, { async: false, renderer }) as string;
    return DOMPurify.sanitize(raw, { ADD_ATTR: ['class'] });
  }, [text]);

  function handleClick(e: React.MouseEvent<HTMLDivElement>) {
    const btn = (e.target as HTMLElement).closest('.code-copy-btn');
    if (!btn) return;
    const code = btn.closest('.code-block')?.querySelector('code');
    if (!code) return;
    navigator.clipboard.writeText(code.textContent ?? '');
    btn.textContent = 'Copied';
    setTimeout(() => { btn.textContent = 'Copy'; }, 1500);
  }

  // eslint-disable-next-line react/no-danger
  return <div className="md" onClick={handleClick} dangerouslySetInnerHTML={{ __html: html }} />;
}
