import {ChevronRight, GitBranch, Plus, Trash2} from 'lucide-react';
import type {FlatBlock, FlatContainer, FlatViewConfig} from './blocks-types';

type Row =
  | {kind: 'block'; block: FlatBlock; containerId: string; depth: number}
  | {kind: 'container'; container: FlatContainer; depth: number};

function buildRows(flat: FlatViewConfig): Row[] {
  const blocks = new Map(flat.blocks.map(block => [block.id, block]));
  const containers = new Map(flat.containers.map(container => [container.id, container]));
  const rows: Row[] = [];

  const visit = (containerId: string, depth: number) => {
    const container = containers.get(containerId);
    if (!container) return;
    for (const blockId of container.blocks) {
      const block = blocks.get(blockId);
      if (!block) continue;
      rows.push({kind: 'block', block, containerId, depth});
      if (block.type !== 'branch') continue;
      for (const childId of block.branches || []) {
        const child = containers.get(childId);
        if (!child) continue;
        rows.push({kind: 'container', container: child, depth: depth + 1});
        visit(childId, depth + 2);
      }
      if (block.finally) {
        const child = containers.get(block.finally);
        if (child) {
          rows.push({kind: 'container', container: child, depth: depth + 1});
          visit(block.finally, depth + 2);
        }
      }
    }
  };

  visit('root', 0);
  return rows;
}

export function FlatBlockTree({flat, selectedId, editable, onSelect, onAddStep,
  onAddBranch, onAddFinally, onDeleteBlock, onDeleteContainer,
  onUpdateCondition}: {
  flat: FlatViewConfig;
  selectedId: number;
  editable: boolean;
  onSelect: (id: number) => void;
  onAddStep: (containerId: string) => void;
  onAddBranch: (blockId: number) => void;
  onAddFinally: (blockId: number) => void;
  onDeleteBlock: (blockId: number) => void;
  onDeleteContainer: (containerId: string) => void;
  onUpdateCondition: (containerId: string, condition: string | null) => void;
}) {
  const rows = buildRows(flat);
  const selected = flat.blocks.find(block => block.id === selectedId);
  return <div className="flat-tree">
    {rows.map((row, index) => row.kind === 'block'
      ? <div key={`b-${row.block.id}-${index}`}
          className={`flat-block-row ${row.block.id === selectedId ? 'active' : ''}`}
          style={{paddingLeft: 8 + row.depth * 15}}>
          <button type="button" className="flat-block-main"
              onClick={() => onSelect(row.block.id)}>
            <span className="flat-block-id">{row.block.id}</span>
            <span className="flat-block-kind">
              {row.block.type === 'branch'
                ? <><GitBranch size={11} />{row.block.kind === 'try' ? 'TRY' : row.block.select === 'multi' ? '并行' : '分支'}</>
                : '普通'}
            </span>
            <span className="flat-block-name">{row.block.name}</span>
          </button>
          {editable && row.block.type === 'branch' && <span className="flat-block-actions" onClick={event => event.stopPropagation()}>
            <button type="button" className="editor-icon-button" title="给这个分支添加分支列表"
              aria-label={`给 ${row.block.name} 添加分支列表`}
              onClick={() => onAddBranch(row.block.id)}><Plus size={11} /></button>
            {row.block.kind === 'try' && !row.block.finally
              && <button type="button" className="editor-icon-button" title="添加 finally"
                aria-label={`给 ${row.block.name} 添加 finally`}
                onClick={() => onAddFinally(row.block.id)}><Plus size={11} /></button>}
          </span>}
          {editable && <span className="flat-block-actions">
            <button type="button" className="editor-icon-button" title="删除这个块"
              aria-label={`删除块 ${row.block.name}`}
              onClick={() => onDeleteBlock(row.block.id)}><Trash2 size={11} /></button>
          </span>}
        </div>
      : <div key={`c-${row.container.id}-${index}`} className="flat-container-row"
          style={{paddingLeft: 8 + row.depth * 15}}>
          <ChevronRight size={11} />
          <span className="flat-container-label">
            {row.container.kind === 'finally' ? '最后一定执行'
              : row.container.role === 'body' ? '正常执行'
                : row.container.role === 'except' ? '异常处理'
                  : '分支'}
          </span>
          {row.container.kind === 'branch' && row.container.role !== 'body'
            && (editable
              ? <input key={`${row.container.id}-${row.container.condition || ''}`}
                  className="flat-container-condition" defaultValue={row.container.condition || ''}
                  placeholder={row.container.role === 'except' ? '异常条件（可留空）' : '条件（可留空）'}
                  aria-label={`容器 ${row.container.id} 条件`}
                  onBlur={event => onUpdateCondition(row.container.id, event.target.value.trim() || null)} />
              : <span className="flat-container-condition-text">{row.container.condition || '无条件'}</span>)}
          {editable && <button type="button" className="editor-icon-button" title="在这个容器末尾添加步骤"
            aria-label={`在 ${row.container.id} 末尾添加步骤`}
            onClick={() => onAddStep(row.container.id)}><Plus size={11} /></button>}
          {editable && <button type="button" className="editor-icon-button" title="删除这个分支容器"
            aria-label={`删除容器 ${row.container.id}`}
            onClick={() => onDeleteContainer(row.container.id)}><Trash2 size={11} /></button>}
        </div>)}
    {editable && <button type="button" className="flat-root-add" onClick={() => onAddStep('root')}>
      <Plus size={12} />添加到根容器
    </button>}
    {selected && <div className="flat-tree-hint">
      当前块 #{selected.id} · {selected.type === 'branch' ? '分支块' : '普通块'}
    </div>}
  </div>;
}
