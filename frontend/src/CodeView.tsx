import {FileCode2} from 'lucide-react';

export type Span = {file: string; line: number; endLine: number; column: number; endColumn: number};
export type CodeLine = {line: number; text: string};

const keyword = /^(async|await|def|class|return|if|elif|else|while|for|in|not|and|or|is|None|True|False|from|import|as|with|try|except|finally|raise|break|continue|pass|yield|lambda|match|case|assert|global|nonlocal|del|property|staticmethod|classmethod)$/;
const pattern = /(#.*$|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\b(?:async|await|def|class|return|if|elif|else|while|for|in|not|and|or|is|None|True|False|from|import|as|with|try|except|finally|raise|break|continue|pass|yield|lambda|match|case|assert|global|nonlocal|del|property|staticmethod|classmethod)\b|\b\d+(?:\.\d+)?\b)/g;

export function highlighted(line: string) {
  return line.split(pattern).map((part, index) => <span key={index}
    className={part.startsWith('#') ? 'tok-comment' : /^["']/.test(part) ? 'tok-string' :
      /^\d/.test(part) ? 'tok-number' : keyword.test(part) ? 'tok-keyword' : ''}>{part}</span>);
}

export function CodeLines({lines, highlight, dense = false}: {
  lines: CodeLine[]; highlight?: Span; dense?: boolean;
}) {
  return <div className={`code-view block-code ${dense ? 'dense' : ''}`}>
    {lines.map(row => {
      const active = !!highlight && row.line >= highlight.line && row.line <= highlight.endLine;
      return <div className={`code-line ${active ? 'hit' : ''}`} key={row.line}>
        <span className="line-number">{row.line}</span>
        <code>{highlighted(row.text.replace(/\r$/, '')) || ' '}</code>
      </div>;
    })}
  </div>;
}

export function SourceView({source, highlight, label}: {source: string; highlight?: Span; label?: string}) {
  const lines = source.split('\n');
  const start = highlight?.line || 1, end = highlight?.endLine || start;
  return <div className="source-box">
    <div className="source-location"><FileCode2 size={13} /><span>{label || '源码片段'}</span><small>L{start}–{end}</small></div>
    <div className="code-view">{lines.map((line, index) => {
      const number = index + 1, active = number >= start && number <= end;
      return <div className={`code-line ${active ? 'hit' : ''}`} key={number}>
        <span className="line-number">{number}</span><code>{highlighted(line.replace(/\r$/, '')) || ' '}</code>
      </div>;
    })}</div>
  </div>;
}
