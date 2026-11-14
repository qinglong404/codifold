import {useCallback, useEffect, useState} from 'react';
import {
  Boxes, ChevronRight, Clock3, FolderOpen, Layers3, Plus, RefreshCw,
} from 'lucide-react';
import {fetchRecentWorkspaces} from './blocks-api';
import type {ExampleWorkspace, RecentWorkspace} from './blocks-types';

export function HomeScreen({onOpen, onBrowse, onNew}: {
  onOpen: (path: string) => Promise<void>;
  onBrowse: () => void;
  onNew: () => void;
}) {
  const [examples, setExamples] = useState<ExampleWorkspace[]>([]);
  const [recent, setRecent] = useState<RecentWorkspace[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busyPath, setBusyPath] = useState('');

  const load = useCallback(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    fetchRecentWorkspaces().then(data => {
      if (cancelled) return;
      setExamples(data.examples || []);
      setRecent(data.recent || []);
      setLoading(false);
    }).catch(reason => {
      if (cancelled) return;
      setError(reason instanceof Error ? reason.message : String(reason));
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => load(), [load]);

  async function open(target: string) {
    setBusyPath(target);
    setError('');
    try {
      await onOpen(target);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setBusyPath('');
    }
  }

  return <div className="home-screen">
    <header className="home-topbar">
      <span className="reader-brand"><Layers3 size={23} /><b>Codifold</b></span>
      <span className="reader-product-label">DEMO</span>
      <span className="topbar-spacer" />
      <span className="reader-status"><i />本地运行</span>
      <button type="button" className="subtle-button" onClick={load} disabled={loading}>
        <RefreshCw size={14} className={loading ? 'spin' : ''} />刷新
      </button>
    </header>
    <main className="home-main">
      <section className="home-hero">
        <span className="home-eyebrow">实验性中文逻辑图阅读器</span>
        <h1>选择一个工作区</h1>
        <p>从示例开始，或打开你编写的工作区。建议边写代码边整理逻辑图；陌生项目的自动转换方式仍在探索。流程需要人工审核，Codifold 不执行被讲解的项目。</p>
        <div className="home-actions">
          <button type="button" className="primary-button" onClick={onBrowse}>
            <FolderOpen size={15} />浏览目录
          </button>
          <button type="button" className="subtle-button" onClick={onNew}>
            <Plus size={15} />新建工作区
          </button>
        </div>
      </section>

      {error && <div className="flow-error home-error" role="alert"><span>{error}</span></div>}

      <section className="home-section">
        <div className="home-section-head">
          <h2>示例工作区</h2>
          <small>{examples.length}</small>
        </div>
        {loading
          ? <div className="home-empty">正在读取示例…</div>
          : examples.length
            ? <div className="home-example-grid">
                {examples.map(item => <button key={item.path} type="button" className="home-example"
                    disabled={!!busyPath}
                    onClick={() => void open(item.path)}>
                  <span className="home-example-icon"><Boxes size={18} /></span>
                  <b>{item.name}</b>
                  <span className="home-example-desc">{item.description}</span>
                  <span className="home-example-meta">
                    {item.views} 个视图 · 入口 {item.entry}
                    <code>{item.path}</code>
                  </span>
                  <span className="home-example-open">
                    {busyPath === item.path ? '打开中…' : <>打开<ChevronRight size={14} /></>}
                  </span>
                </button>)}
              </div>
            : <div className="home-empty">仓库 examples 目录下还没有可用工作区。</div>}
      </section>

      <section className="home-section">
        <div className="home-section-head">
          <h2><Clock3 size={14} />最近打开</h2>
          <small>{recent.length}</small>
        </div>
        {loading
          ? <div className="home-empty">正在读取最近记录…</div>
          : recent.length
            ? <div className="home-recent-list">
                {recent.map(item => <button key={item.path} type="button"
                    className={`home-recent-row ${item.exists ? '' : 'missing'}`}
                    disabled={!!busyPath || !item.exists}
                    onClick={() => void open(item.path)}>
                  <span className="home-recent-mark" />
                  <span className="home-recent-copy">
                    <b>{item.name || item.path.split('/').pop()}</b>
                    <small>{item.description || item.path}</small>
                  </span>
                  <code>{item.path}</code>
                  {!item.exists && <em>目录不存在</em>}
                  <span className="home-recent-open">
                    {busyPath === item.path ? '打开中…' : <ChevronRight size={15} />}
                  </span>
                </button>)}
              </div>
            : <div className="home-empty">还没有最近打开的工作区。用“浏览目录”选一个。</div>}
      </section>

      <footer className="home-footer">
        <span>目录里需要有 <code>codifold.json</code> 才能打开。</span>
        <span>本机 · 只读源码 · 不执行被讲解的项目</span>
      </footer>
    </main>
  </div>;
}
