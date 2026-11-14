import {useEffect, useId, useRef, useState} from 'react';
import type {FormEvent, ReactNode} from 'react';
import {
  ArrowDown, ArrowUp, ChevronRight, Clock3, FileJson, Folder, FolderOpen, Home,
  Plus, Save, Trash2, X,
} from 'lucide-react';
import {
  browseDirectory, createWorkspace, deleteWorkspace, fetchEvents, fetchProject,
  fetchRecentWorkspaces, fetchView, forgetWorkspace,
  openWorkspace as openWorkspaceApi, saveProject,
} from './blocks-api';
import type {
  BranchList, BrowseResponse, CodeMapping, EventTarget, ProjectManifest, RBlock,
  RecentWorkspace, SaveProjectResponse, ViewConfig, ViewMeta,
} from './blocks-types';
import {
  collectIds, linesText, maxBlockId, parseLineText, replaceBlock,
} from './blocks-edit-utils';

type ApplyView = (config: ViewConfig, focusId?: number) => Promise<void>;
type BlockChoice = {id: number; name: string; on?: string};

function choicesOf(blocks: RBlock[], onlyEvents = false): BlockChoice[] {
  const result: BlockChoice[] = [];
  const walk = (items: RBlock[]) => items.forEach(block => {
    if (!onlyEvents || block.on) {
      result.push({id: block.id, name: block.name, on: block.on});
    }
    block.branches?.forEach(list => walk(list.steps));
    if (block.finally) walk(block.finally);
  });
  walk(blocks);
  return result.sort((a, b) => a.id - b.id);
}

type CreateType = 'normal' | 'branch-single' | 'branch-multi' | 'try';
type BranchStructure = {branches: BranchList[]; finally?: RBlock[]};

function normalStep(id: number, name: string): RBlock {
  return {id, type: 'normal', name, description: '待补充。'};
}

function cloneStructure(block?: RBlock): BranchStructure {
  if (!block || block.type !== 'branch') return {branches: [], finally: []};
  return {
    branches: JSON.parse(JSON.stringify(block.branches || [])) as BranchList[],
    finally: block.finally
      ? JSON.parse(JSON.stringify(block.finally)) as RBlock[] : [],
  };
}

function defaultStructure(type: CreateType, allocate: () => number): BranchStructure {
  if (type === 'try') {
    return {branches: [
      {role: 'body', steps: [normalStep(allocate(), '主体步骤')]},
      {role: 'except', condition: 'Exception', steps: [normalStep(allocate(), '异常处理')]},
    ], finally: []};
  }
  if (type === 'branch-multi') {
    return {branches: [
      {condition: '分支 1', steps: [normalStep(allocate(), '并行步骤 1')]},
      {condition: '分支 2', steps: [normalStep(allocate(), '并行步骤 2')]},
    ], finally: []};
  }
  return {branches: [
    {condition: '条件 1', steps: [normalStep(allocate(), '条件步骤')]},
    {steps: [normalStep(allocate(), '默认步骤')]},
  ], finally: []};
}

function typeLabel(type: CreateType): string {
  if (type === 'try') return '异常结构 try / except / finally';
  if (type === 'branch-multi') return '条件分支块 · 并行';
  if (type === 'branch-single') return '条件分支块 · 单选';
  return '普通块 normal';
}

function stepTypeLabel(step: RBlock): string {
  if (step.type !== 'branch') return '';
  if (step.kind === 'try') return 'try';
  return step.select === 'multi' ? '并行' : '单选';
}

function makeBranchStep(id: number, type: CreateType, allocate: () => number): RBlock {
  const structure = defaultStructure(type, allocate);
  return {
    id, type: 'branch',
    select: type === 'branch-multi' ? 'multi' : 'single',
    name: type === 'try' ? 'try 结构' : type === 'branch-multi' ? '并行分支' : '单选分支',
    description: '待补充。',
    ...(type === 'try' ? {kind: 'try' as const} : {}),
    branches: structure.branches,
    ...(structure.finally?.length ? {finally: structure.finally} : {}),
  };
}

function cleanBlock(step: RBlock): RBlock {
  const name = step.name.trim();
  const description = step.description.trim();
  if (!name || !description) throw new Error(`块 ${step.id} 的名称和描述不能为空`);
  if (step.type !== 'branch') return {...step, name, description};
  const cleaned = cleanStructure(
    {branches: step.branches || [], finally: step.finally}, step.kind === 'try');
  const result: RBlock = {...step, name, description, branches: cleaned.branches};
  if (cleaned.finally.length) result.finally = cleaned.finally;
  else delete result.finally;
  return result;
}

function cleanStructure(structure: BranchStructure, isTry: boolean): {
  branches: BranchList[]; finally: RBlock[];
} {
  const branches = structure.branches.map((list, index) => {
    const condition = list.condition?.trim();
    return {
      ...(isTry ? {role: (index === 0 ? 'body' : 'except') as 'body' | 'except'} : {}),
      ...(condition && (!isTry || index > 0) ? {condition} : {}),
      steps: list.steps.map(cleanBlock),
    };
  });
  const finallySteps = (structure.finally || []).map(cleanBlock);
  if (!branches.length) throw new Error('分支至少需要一个分支列表');
  if (branches.some(list => !list.steps.length)) {
    throw new Error('每个分支列表至少需要一个步骤');
  }
  if (isTry && branches.length <= 1 && !finallySteps.length) {
    throw new Error('try 至少需要一个 except 或非空 finally');
  }
  return {branches, finally: finallySteps};
}

function AddStepControl({canNestBranch, label, onAdd}: {
  canNestBranch: boolean;
  label: string;
  onAdd: (type: CreateType) => void;
}) {
  const [type, setType] = useState<CreateType>('normal');
  return <div className="branch-add-row">
    <select value={type} aria-label={label}
      onChange={event => setType(event.target.value as CreateType)}>
      <option value="normal">普通步骤</option>
      <option value="branch-single" disabled={!canNestBranch}>单选分支</option>
      <option value="branch-multi" disabled={!canNestBranch}>并行分支</option>
      <option value="try" disabled={!canNestBranch}>try 结构</option>
    </select>
    <button type="button" className="branch-add" onClick={() => onAdd(type)}>
      <Plus size={12} />添加
    </button>
  </div>;
}

function StepListEditor({steps, onChange, allocate, depth, onOpenJson, allowEmpty = false}: {
  steps: RBlock[];
  onChange: (next: RBlock[]) => void;
  allocate: () => number;
  depth: number;
  onOpenJson: () => void;
  allowEmpty?: boolean;
}) {
  const updateStep = (index: number, patch: Partial<RBlock>) => {
    onChange(steps.map((step, i) => i === index ? {...step, ...patch} : step));
  };
  const moveStep = (index: number, delta: number) => {
    const target = index + delta;
    if (target < 0 || target >= steps.length) return;
    const next = [...steps];
    [next[index], next[target]] = [next[target]!, next[index]!];
    onChange(next);
  };
  return <div className="branch-steps">
    {steps.map((step, index) => <div className="branch-step-wrap" key={step.id}>
      <div className="branch-step">
        <span className="branch-step-id">{step.id}</span>
        <input value={step.name} aria-label={`步骤 ${step.id} 名称`}
          onChange={event => updateStep(index, {name: event.target.value})} />
        <input value={step.description} aria-label={`步骤 ${step.id} 描述`}
          onChange={event => updateStep(index, {description: event.target.value})}
          placeholder="描述" />
        <span className="branch-step-type">{stepTypeLabel(step)}</span>
        <span className="branch-step-actions">
          <button type="button" className="editor-icon-button" aria-label={`上移步骤 ${step.id}`}
            disabled={index === 0} onClick={() => moveStep(index, -1)}><ArrowUp size={12} /></button>
          <button type="button" className="editor-icon-button" aria-label={`下移步骤 ${step.id}`}
            disabled={index === steps.length - 1} onClick={() => moveStep(index, 1)}>
            <ArrowDown size={12} /></button>
          <button type="button" className="editor-icon-button" aria-label={`删除步骤 ${step.id}`}
            disabled={!allowEmpty && steps.length <= 1}
            onClick={() => onChange(steps.filter((_, i) => i !== index))}>
            <Trash2 size={12} /></button>
        </span>
      </div>
      {step.type === 'branch' && <details className="branch-step-children">
        <summary>嵌套结构 · {stepTypeLabel(step)}</summary>
        <BranchStructureEditor
          structure={{branches: step.branches || [], finally: step.finally || []}}
          isTry={step.kind === 'try'}
          depth={depth}
          mode={step.kind === 'try' ? undefined : step.select || 'single'}
          onModeChange={mode => updateStep(index, {select: mode})}
          onChange={nested => updateStep(index, {
            branches: nested.branches,
            finally: nested.finally?.length ? nested.finally : undefined,
          })}
          allocate={allocate}
          onOpenJson={onOpenJson} />
      </details>}
    </div>)}
  </div>;
}

function BranchStructureEditor({structure, isTry, depth, mode, onModeChange,
  onChange, allocate, onOpenJson}: {
  structure: BranchStructure;
  isTry: boolean;
  depth: number;
  mode?: 'single' | 'multi';
  onModeChange?: (mode: 'single' | 'multi') => void;
  onChange: (next: BranchStructure) => void;
  allocate: () => number;
  onOpenJson: () => void;
}) {
  const stepDepth = depth + 1;
  const canNestBranch = stepDepth <= 4;
  const updateList = (index: number, next: BranchList) => {
    onChange({...structure,
      branches: structure.branches.map((list, i) => i === index ? next : list)});
  };
  const addStep = (listIndex: number, type: CreateType) => {
    const list = structure.branches[listIndex]!;
    const chosen = type !== 'normal' && !canNestBranch ? 'normal' : type;
    const name = isTry ? (listIndex === 0 ? '主体步骤' : '异常处理') : '新步骤';
    const step = chosen === 'normal'
      ? normalStep(allocate(), name)
      : makeBranchStep(allocate(), chosen, allocate);
    updateList(listIndex, {...list, steps: [...list.steps, step]});
  };
  const addList = () => {
    const step = normalStep(allocate(), isTry ? '异常处理' : '分支步骤');
    onChange({...structure, branches: [...structure.branches,
      isTry ? {role: 'except', steps: [step]} : {steps: [step]}]});
  };
  const canRemoveList = (index: number) => {
    if (isTry) {
      if (index === 0) return false;
      return structure.branches.length > 2 || (structure.finally?.length || 0) > 0;
    }
    return structure.branches.length > 1;
  };
  const removeList = (index: number) => {
    if (!canRemoveList(index)) return;
    onChange({...structure,
      branches: structure.branches.filter((_, i) => i !== index)});
  };
  const finallySteps = structure.finally || [];
  const updateFinally = (steps: RBlock[]) => onChange({...structure, finally: steps});
  const addFinallyStep = (type: CreateType) => {
    const chosen = type !== 'normal' && !canNestBranch ? 'normal' : type;
    const step = chosen === 'normal'
      ? normalStep(allocate(), 'finally 步骤')
      : makeBranchStep(allocate(), chosen, allocate);
    onChange({...structure, finally: [...finallySteps, step]});
  };
  return <div className="branch-editor">
    <div className="branch-editor-head">
      <b>分支结构</b>
      <div className="branch-editor-head-actions">
        {!isTry && mode && onModeChange && <select className="branch-mode-select" value={mode}
          aria-label="嵌套分支模式"
          onChange={event => onModeChange(event.target.value as 'single' | 'multi')}>
          <option value="single">单选</option>
          <option value="multi">并行</option>
        </select>}
        <span>{isTry ? 'body / except / finally' : '列表尾自动汇合'}</span>
      </div>
    </div>
    {structure.branches.map((list, li) => <section className="branch-list" key={li}>
      <div className="branch-list-head">
        <span className="branch-list-title">
          {isTry ? (li === 0 ? '主体 body' : `异常 except ${li}`) : `分支 ${li + 1}`}
        </span>
        {(!isTry || li > 0) && <input className="branch-condition" value={list.condition || ''}
          aria-label={isTry ? `异常 ${li} 类型` : `分支 ${li + 1} 条件`}
          onChange={event => updateList(li, {...list, condition: event.target.value})}
          placeholder={isTry ? '异常类型（可留空）' : '条件说明（可留空）'} />}
        {canRemoveList(li) && <button type="button" className="editor-icon-button"
          aria-label={`删除分支列表 ${li + 1}`} onClick={() => removeList(li)}>
          <Trash2 size={13} />
        </button>}
      </div>
      <StepListEditor steps={list.steps} depth={stepDepth}
        onChange={steps => updateList(li, {...list, steps})}
        allocate={allocate} onOpenJson={onOpenJson} />
      <AddStepControl canNestBranch={canNestBranch}
        label={`分支 ${li + 1} 新步骤类型`} onAdd={type => addStep(li, type)} />
    </section>)}
    {isTry && <section className="branch-list">
      <div className="branch-list-head"><span className="branch-list-title">finally</span>
        <span className="branch-list-title">{finallySteps.length} 步</span></div>
      <StepListEditor steps={finallySteps} depth={stepDepth}
        allowEmpty={structure.branches.length > 1}
        onChange={updateFinally} allocate={allocate} onOpenJson={onOpenJson} />
      <AddStepControl canNestBranch={canNestBranch}
        label="finally 新步骤类型" onAdd={addFinallyStep} />
    </section>}
    <div className="branch-editor-actions">
      <button type="button" className="subtle-button" onClick={addList}>
        <Plus size={13} />{isTry ? '添加异常分支' : '添加分支列表'}
      </button>
      <button type="button" className="subtle-button" onClick={onOpenJson}>
        <FileJson size={13} />用视图 JSON 编辑
      </button>
    </div>
    <Hint>分支列表里可以继续嵌套普通块、分支块和 try（最多 5 层）。步骤的 next / jump / emit / 代码映射保存后在图中选中编辑。</Hint>
  </div>;
}

/* ------------------------------------------------------------------ */
/* Block create/edit                                                   */
/* ------------------------------------------------------------------ */

function Modal({title, onClose, children, wide = false}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const titleId = useId();
  const panelRef = useRef<HTMLElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const panel = panelRef.current;
    panel?.querySelector<HTMLElement>('input:not([readonly]), textarea, select, button')?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeRef.current();
        return;
      }
      if (event.key !== 'Tab' || !panel) return;
      const items = Array.from(panel.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])'));
      if (!items.length) return;
      const first = items[0]!;
      const last = items[items.length - 1]!;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);
  return <div className="dialog-overlay" onClick={onClose}>
    <section ref={panelRef} role="dialog" aria-modal="true" aria-labelledby={titleId}
      className={`config-dialog editor-dialog ${wide ? 'editor-dialog-wide' : ''}`}
      onClick={event => event.stopPropagation()}>
      <div className="dialog-title">
        <h2 id={titleId}>{title}</h2>
        <button type="button" className="editor-close" aria-label="关闭" onClick={onClose}>
          <X size={18} />
        </button>
      </div>
      {children}
    </section>
  </div>;
}

function ErrorLine({error}: {error: string}) {
  return error ? <p className="editor-error" role="alert">{error}</p> : null;
}

function Hint({children}: {children: ReactNode}) {
  return <p className="editor-hint">{children}</p>;
}

function ReadonlyRow({label, value}: {label: string; value: ReactNode}) {
  return <div className="editor-readonly-row"><span>{label}</span><b>{value}</b></div>;
}

/* ------------------------------------------------------------------ */
/* Block create/edit                                                   */
/* ------------------------------------------------------------------ */

export function BlockEditorDialog({mode, config, block, afterId, views, files,
  topLevelIds, workspacePath, flatMode = false, onApply, onOpenJson, onClose}: {
  mode: 'create' | 'edit';
  config: ViewConfig;
  block?: RBlock;
  afterId?: number;
  views: ViewMeta[];
  files: string[];
  topLevelIds: number[];
  workspacePath?: string;
  flatMode?: boolean;
  onApply: ApplyView;
  onOpenJson: () => void;
  onClose: () => void;
}) {
  const newId = maxBlockId(config.blocks) + 1;
  const initialType: CreateType = mode === 'create'
    ? 'normal'
    : block?.type === 'branch'
      ? block.kind === 'try' ? 'try'
        : block.select === 'multi' ? 'branch-multi' : 'branch-single'
      : 'normal';
  const [blockType, setBlockType] = useState<CreateType>(initialType);
  const isBranch = blockType !== 'normal';
  const isTry = blockType === 'try';
  const idRef = useRef(mode === 'create' ? newId + 1 : maxBlockId(config.blocks) + 1);
  const allocate = () => idRef.current++;
  const [structure, setStructure] = useState<BranchStructure>(() =>
    mode === 'edit' ? cloneStructure(block) : {branches: [], finally: []});
  const isFirst = mode === 'edit' && !!block && topLevelIds[0] === block.id;
  const targetIds = collectIds(config.blocks).filter(id => id !== block?.id);
  const canInsertAfter = afterId !== undefined && topLevelIds.includes(afterId);
  const [name, setName] = useState(block?.name || '');
  const [description, setDescription] = useState(block?.description || '');
  const [position, setPosition] = useState<'append' | 'after'>(canInsertAfter ? 'after' : 'append');
  const [codeEnabled, setCodeEnabled] = useState(!!block?.code_mapping);
  const [codeFile, setCodeFile] = useState(block?.code_mapping?.file || files[0] || '');
  const [codeLines, setCodeLines] = useState(linesText(block?.code_mapping));
  const [nextMode, setNextMode] = useState<'default' | 'jump' | 'stop'>(() => {
    if (!block) return 'default';
    if (block.next === null) return 'stop';
    return typeof block.next === 'number' ? 'jump' : 'default';
  });
  const [nextTarget, setNextTarget] = useState(
    typeof block?.next === 'number' ? String(block.next) : '');
  const [jumpEnabled, setJumpEnabled] = useState(!!block?.jump);
  const [jumpView, setJumpView] = useState(block?.jump?.view || '');
  const [jumpId, setJumpId] = useState(block?.jump ? String(block.jump.id) : '');
  const [emitEnabled, setEmitEnabled] = useState(!!block?.emit?.length);
  const [emit, setEmit] = useState<{view: string; id: string}[]>(
    block?.emit?.map(item => ({view: item.view || '', id: String(item.id)})) || []);
  const [on, setOn] = useState(block?.on || '');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [viewChoices, setViewChoices] = useState<Record<string, BlockChoice[]>>({});
  const [viewErrors, setViewErrors] = useState<Record<string, string>>({});
  const [events, setEvents] = useState<string[]>([]);
  const [eventsError, setEventsError] = useState('');
  const loadingViews = useRef(new Set<string>());
  const neededViews: string[] = [];
  if (jumpEnabled && jumpView && jumpView !== config.view.id) neededViews.push(jumpView);
  if (emitEnabled) {
    emit.forEach(row => {
      if (row.view && row.view !== config.view.id && !neededViews.includes(row.view)) {
        neededViews.push(row.view);
      }
    });
  }
  const neededKey = neededViews.join('|');

  useEffect(() => {
    if (!workspacePath) return;
    let active = true;
    fetchEvents(workspacePath).then(data => {
      if (active) setEvents(data.events);
    }).catch(reason => {
      if (active) setEventsError(reason instanceof Error ? reason.message : String(reason));
    });
    return () => { active = false; };
  }, [workspacePath]);

  useEffect(() => {
    if (!workspacePath) return;
    neededViews.forEach(viewId => {
      if (viewChoices[viewId] || loadingViews.current.has(viewId)) return;
      loadingViews.current.add(viewId);
      fetchView(workspacePath, viewId).then(data => {
        setViewChoices(previous => ({...previous, [viewId]: choicesOf(data.config.blocks)}));
        setViewErrors(previous => {
          if (!(viewId in previous)) return previous;
          const next = {...previous};
          delete next[viewId];
          return next;
        });
      }).catch(reason => {
        setViewErrors(previous => ({
          ...previous, [viewId]: reason instanceof Error ? reason.message : String(reason),
        }));
      }).finally(() => loadingViews.current.delete(viewId));
    });
  }, [workspacePath, neededKey]);

  const choicesFor = (viewId: string, onlyEvents: boolean): BlockChoice[] => {
    if (!viewId || viewId === config.view.id) return choicesOf(config.blocks, onlyEvents);
    return (viewChoices[viewId] || []).filter(choice => !onlyEvents || choice.on);
  };
  const eventOptions = Array.from(new Set([...events, ...(on ? [on] : [])])).sort();

  function changeType(next: CreateType) {
    setBlockType(next);
    if (next === 'normal') return;
    if (next === 'try') {
      setStructure(defaultStructure('try', allocate));
      return;
    }
    if (blockType === 'try' || !structure.branches.length) {
      setStructure(defaultStructure(next, allocate));
    }
  }

  function mappingValue(): CodeMapping | undefined {
    if (!codeEnabled) return undefined;
    const lines = parseLineText(codeLines);
    if (!codeFile || !lines.length) throw new Error('代码映射需要选择文件并填写行号');
    if (lines.some(line => !/^\d+(-\d+)?$/.test(String(line)))) {
      throw new Error('行号格式应为 1、2 或 6-9');
    }
    return {file: codeFile, lines};
  }

  function jumpValue(): EventTarget | undefined {
    if (!jumpEnabled) return undefined;
    const id = Number(jumpId);
    if (!Number.isInteger(id) || id < 1) throw new Error('跳转目标编号必须是正整数');
    return {id, ...(jumpView ? {view: jumpView} : {})};
  }

  function emitValue(): EventTarget[] | undefined {
    if (!emitEnabled) return undefined;
    const targets = emit
      .filter(row => row.id.trim())
      .map(row => ({id: Number(row.id), ...(row.view ? {view: row.view} : {})}));
    if (!targets.length) throw new Error('事件发出至少需要一个目标');
    if (targets.some(target => !Number.isInteger(target.id) || target.id < 1)) {
      throw new Error('事件目标编号必须是正整数');
    }
    return targets;
  }

  async function saveBlocks(blocks: RBlock[], focusId: number) {
    setBusy(true);
    setError('');
    try {
      await onApply({...config, blocks}, focusId);
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError('');
    if (!name.trim() || !description.trim()) {
      setError('名称和描述不能为空');
      return;
    }
    try {
      const mapping = mappingValue();
      const jump = jumpValue();
      if (mode === 'edit' && block) {
        const updated: RBlock = {...block, name: name.trim(), description: description.trim()};
        if (mapping) updated.code_mapping = mapping;
        else delete updated.code_mapping;
        if (jump) updated.jump = jump;
        else delete updated.jump;
        if (updated.type === 'branch') {
          if (updated.kind !== 'try') {
            updated.select = blockType === 'branch-multi' ? 'multi' : 'single';
          }
          const cleaned = cleanStructure(structure, updated.kind === 'try');
          updated.branches = cleaned.branches;
          if (cleaned.finally.length) updated.finally = cleaned.finally;
          else delete updated.finally;
        } else {
          if (nextMode === 'stop') updated.next = null;
          else if (nextMode === 'jump') {
            const target = Number(nextTarget);
            if (!targetIds.includes(target)) throw new Error('请选择 next 目标');
            updated.next = target;
          } else delete updated.next;
          const emits = emitValue();
          if (emits) updated.emit = emits;
          else delete updated.emit;
        }
        if (isFirst && on.trim()) updated.on = on.trim();
        else delete updated.on;
        await saveBlocks(replaceBlock(config.blocks, block.id, updated), block.id);
        return;
      }
      let created: RBlock;
      if (blockType === 'normal') {
        created = {
          id: newId, type: 'normal', name: name.trim(), description: description.trim(),
        };
        if (mapping) created.code_mapping = mapping;
        if (nextMode === 'stop') created.next = null;
        else if (nextMode === 'jump') {
          const target = Number(nextTarget);
          if (!targetIds.includes(target)) throw new Error('请选择 next 目标');
          created.next = target;
        }
        if (jump) created.jump = jump;
        const emits = emitValue();
        if (emits) created.emit = emits;
      } else {
        const cleaned = cleanStructure(structure, isTry);
        created = {
          id: newId, type: 'branch',
          select: blockType === 'branch-multi' ? 'multi' : 'single',
          name: name.trim(), description: description.trim(),
          branches: cleaned.branches,
        };
        if (isTry) created.kind = 'try';
        if (cleaned.finally.length) created.finally = cleaned.finally;
        if (mapping) created.code_mapping = mapping;
        if (jump) created.jump = jump;
      }
      const blocks = [...config.blocks];
      if (position === 'after' && canInsertAfter) {
        const at = blocks.findIndex(item => item.id === afterId);
        blocks.splice(at + 1, 0, created);
      } else {
        blocks.push(created);
      }
      await saveBlocks(blocks, newId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  const jumpChoices = choicesFor(jumpView, false);
  const title = mode === 'create'
    ? (blockType === 'normal' ? '添加普通块'
      : blockType === 'try' ? '添加异常结构' : '添加条件分支块')
    : `编辑块 ${block?.id}`;
  return <Modal title={title} onClose={onClose}>
    <form className="editor-form" onSubmit={submit}>
      {mode === 'create'
        ? <div className="editor-form-grid">
            <label className="editor-field"><span>类型</span>
              <select value={blockType}
                onChange={event => changeType(event.target.value as CreateType)}>
                <option value="normal">普通块 normal</option>
                <option value="branch-single">条件分支 · 单选</option>
                <option value="branch-multi">条件分支 · 并行</option>
                <option value="try">异常结构 try / except / finally</option>
              </select>
            </label>
            <div className="editor-field"><span>块编号</span>
              <div className="editor-static-value">{newId} · 自动分配</div>
            </div>
          </div>
        : <div className="editor-meta-row">
            {isBranch && blockType !== 'try' && <label className="editor-field editor-field-inline">
              <span>分支模式</span>
              <select value={blockType}
                onChange={event => setBlockType(event.target.value as CreateType)}>
                <option value="branch-single">单选（只进一条）</option>
                <option value="branch-multi">并行（多选）</option>
              </select>
            </label>}
            <div className="editor-meta">编号 <b>{block?.id}</b> · 类型 <b>{typeLabel(blockType)}</b></div>
          </div>}
      <div className="editor-form-grid">
        <label className="editor-field"><span>名称</span>
          <input value={name} onChange={event => setName(event.target.value)} placeholder="例如：读取输入" />
        </label>
        <label className="editor-field editor-field-wide"><span>描述</span>
          <textarea rows={2} value={description} onChange={event => setDescription(event.target.value)}
            placeholder="这个块做什么。" />
        </label>
        {mode === 'create' && canInsertAfter && <label className="editor-field"><span>插入位置</span>
          <select value={position} onChange={event => setPosition(event.target.value as 'append' | 'after')}>
            <option value="append">顶层末尾</option>
            <option value="after">所选块之后</option>
          </select>
        </label>}
      </div>

      {isBranch && !flatMode && <BranchStructureEditor structure={structure} isTry={isTry} depth={1}
        onChange={setStructure} allocate={allocate} onOpenJson={onOpenJson} />}
      {isBranch && flatMode && <Hint>子块在左侧“块结构”里单独添加、删除和排序；这里只编辑当前分支块本身。</Hint>}

      {!isBranch && <div className="editor-form-grid">
        <label className="editor-field"><span>next</span>
            <select value={nextMode} onChange={event => setNextMode(event.target.value as typeof nextMode)}>
              <option value="default">顺序下一块</option>
              <option value="jump">跳转到指定编号</option>
              <option value="stop">终止（next: null）</option>
            </select>
          </label>
          {nextMode === 'jump' && <label className="editor-field"><span>next 目标</span>
            <select value={nextTarget} onChange={event => setNextTarget(event.target.value)}>
              <option value="">选择块</option>
              {targetIds.map(id => <option key={id} value={id}>{id}</option>)}
            </select>
          </label>}
      </div>}

      <fieldset className="editor-fieldset">
        <legend><label className="editor-check"><input type="checkbox" checked={jumpEnabled}
          onChange={event => setJumpEnabled(event.target.checked)} />跳转 jump</label></legend>
        {jumpEnabled && <div className="editor-form-grid">
            <label className="editor-field"><span>目标视图</span>
              <select value={jumpView} onChange={event => {setJumpView(event.target.value); setJumpId('');}}>
                <option value="">本视图</option>
                {views.map(view => <option key={view.view_id} value={view.view_id}>{view.name}（{view.view_id}）</option>)}
              </select>
            </label>
            <label className="editor-field"><span>目标编号</span>
              <select value={jumpId} onChange={event => setJumpId(event.target.value)}>
                <option value="">选择块</option>
                {jumpChoices.map(choice => (
                  <option key={choice.id} value={choice.id}>{choice.id} · {choice.name}</option>
                ))}
                {jumpId && !jumpChoices.some(choice => String(choice.id) === jumpId)
                  && <option value={jumpId}>{jumpId}（当前值）</option>}
              </select>
            </label>
          </div>}
        {jumpView && viewErrors[jumpView] && <Hint>无法读取目标视图：{viewErrors[jumpView]}</Hint>}
      </fieldset>

      {!isBranch && <fieldset className="editor-fieldset">
        <legend><label className="editor-check"><input type="checkbox" checked={emitEnabled}
            onChange={event => {
              const checked = event.target.checked;
              setEmitEnabled(checked);
              if (checked && !emit.length) setEmit([{view: '', id: ''}]);
            }} />事件发出 emit</label></legend>
          {emitEnabled && <>
            {emit.map((row, index) => <div className="editor-emit-row" key={index}>
              <select value={row.view} onChange={event => {
                const next = [...emit];
                next[index] = {...row, view: event.target.value, id: ''};
                setEmit(next);
              }}>
                <option value="">本视图</option>
                {views.map(view => <option key={view.view_id} value={view.view_id}>{view.view_id}</option>)}
              </select>
              <select value={row.id} onChange={event => {
                const next = [...emit];
                next[index] = {...row, id: event.target.value};
                setEmit(next);
              }}>
                <option value="">选择事件入口</option>
                {choicesFor(row.view, true).map(choice => (
                  <option key={choice.id} value={choice.id}>{choice.id} · {choice.name}</option>
                ))}
                {row.id && !choicesFor(row.view, true).some(choice => String(choice.id) === row.id)
                  && <option value={row.id}>{row.id}（当前值）</option>}
              </select>
              <button type="button" className="editor-icon-button" aria-label="删除事件目标"
                onClick={() => setEmit(emit.filter((_, item) => item !== index))}>
                <Trash2 size={14} />
              </button>
            </div>)}
            <button type="button" className="subtle-button"
              onClick={() => setEmit([...emit, {view: '', id: ''}])}>
              <Plus size={13} />添加事件目标
            </button>
            {emit.some(row => row.view && viewErrors[row.view])
              && <Hint>有目标视图读取失败，请检查视图 id。</Hint>}
            {emit.length > 0
              && emit.every(row => !row.view || row.view === config.view.id || viewChoices[row.view])
              && emit.every(row => choicesFor(row.view, true).length === 0)
              && <Hint>目标视图没有带 on 的事件入口；先在目标视图首块设置 on。</Hint>}
          </>}
      </fieldset>}

      <fieldset className="editor-fieldset">
        <legend><label className="editor-check"><input type="checkbox" checked={codeEnabled}
          disabled={!files.length}
          onChange={event => setCodeEnabled(event.target.checked)} />代码映射 code_mapping</label></legend>
        {codeEnabled && <div className="editor-form-grid">
          <label className="editor-field"><span>文件</span>
            <select value={codeFile} onChange={event => setCodeFile(event.target.value)}>
              {files.map(file => <option key={file} value={file}>{file}</option>)}
            </select>
          </label>
          <label className="editor-field"><span>行号</span>
            <input value={codeLines} onChange={event => setCodeLines(event.target.value)}
              placeholder='例如 12-16, 20' />
          </label>
        </div>}
        {!files.length && <Hint>工作区还没有声明源码文件；先在 codifold.json 的 files 里添加。</Hint>}
      </fieldset>

      {isFirst && <label className="editor-field"><span>事件入口 on</span>
        <select value={on} onChange={event => setOn(event.target.value)}>
          <option value="">无（不标记事件入口）</option>
          {eventOptions.map(name => <option key={name} value={name}>{name}</option>)}
        </select>
      </label>}
      {isFirst && eventsError && <Hint>事件名读取失败：{eventsError}</Hint>}
      {isFirst && !eventsError && eventOptions.length === 0
        && <Hint>工作区里还没有 on 值；需要新事件名时请用视图 JSON。</Hint>}

      <ErrorLine error={error} />
      <div className="dialog-actions">
        <button type="button" className="subtle-button" onClick={onClose}>取消</button>
        <button type="submit" className="primary-button" disabled={busy}>
          <Save size={14} />{busy ? '保存中…' : '保存'}
        </button>
      </div>
    </form>
  </Modal>;
}

/* ------------------------------------------------------------------ */
/* Views                                                               */
/* ------------------------------------------------------------------ */

export function NewViewDialog({views, onApply, onClose}: {
  views: ViewMeta[];
  onApply: ApplyView;
  onClose: () => void;
}) {
  const [id, setId] = useState('');
  const [name, setName] = useState('新视图');
  const [description, setDescription] = useState('新建视图');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError('');
    const viewId = id.trim();
    if (!/^[a-z][a-z0-9_-]{0,63}$/.test(viewId)) {
      setError('视图 id 必须以小写字母开头，只能包含小写字母、数字、_、-');
      return;
    }
    if (views.some(view => view.view_id === viewId)) {
      setError('视图 id 已存在');
      return;
    }
    if (!name.trim() || !description.trim()) {
      setError('名称和描述不能为空');
      return;
    }
    const config: ViewConfig = {
      view: {id: viewId, name: name.trim(), description: description.trim()},
      blocks: [{id: 1, type: 'normal', name: '开始', description: '流程起点。', next: null}],
    };
    setBusy(true);
    try {
      await onApply(config, 1);
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  return <Modal title="新建视图" onClose={onClose}>
    <form className="editor-form" onSubmit={submit}>
      <div className="editor-form-grid">
        <label className="editor-field"><span>视图 id</span>
          <input value={id} onChange={event => setId(event.target.value)} placeholder="例如 errors" autoFocus />
        </label>
        <label className="editor-field"><span>文件</span>
          <input readOnly value={id.trim() ? '根据视图 id 和后缀生成' : '根据 id 生成'} />
        </label>
        <label className="editor-field editor-field-wide"><span>名称</span>
          <input value={name} onChange={event => setName(event.target.value)} />
        </label>
        <label className="editor-field editor-field-wide"><span>描述</span>
          <input value={description} onChange={event => setDescription(event.target.value)} />
        </label>
      </div>
      <Hint>新视图会生成一个终止的“开始”块，之后可以继续添加块。</Hint>
      <ErrorLine error={error} />
      <div className="dialog-actions">
        <button type="button" className="subtle-button" onClick={onClose}>取消</button>
        <button type="submit" className="primary-button" disabled={busy}>
          <Plus size={14} />{busy ? '创建中…' : '创建视图'}
        </button>
      </div>
    </form>
  </Modal>;
}

export function ViewSettingsDialog({config, file, entry, onApply, onOpenJson, onDelete, onClose}: {
  config: ViewConfig;
  file?: string;
  entry?: boolean;
  onApply: ApplyView;
  onOpenJson: () => void;
  onDelete: () => void;
  onClose: () => void;
}) {
  const [name, setName] = useState(config.view.name);
  const [description, setDescription] = useState(config.view.description);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError('');
    if (!name.trim() || !description.trim()) {
      setError('名称和描述不能为空');
      return;
    }
    setBusy(true);
    try {
      await onApply({...config, view: {...config.view, name: name.trim(), description: description.trim()}},
        config.blocks[0]?.id);
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  return <Modal title="视图设置" onClose={onClose}>
    <form className="editor-form" onSubmit={submit}>
      <div className="editor-readonly">
        <ReadonlyRow label="视图 id" value={config.view.id} />
        <ReadonlyRow label="文件" value={file || '—'} />
        <ReadonlyRow label="入口" value={entry ? '是' : '否'} />
      </div>
      <div className="editor-form-grid">
        <label className="editor-field editor-field-wide"><span>名称</span>
          <input value={name} onChange={event => setName(event.target.value)} />
        </label>
        <label className="editor-field editor-field-wide"><span>描述</span>
          <input value={description} onChange={event => setDescription(event.target.value)} />
        </label>
      </div>
      <Hint>删除或修改入口视图可能影响跳转和事件引用；服务端会校验并拒绝破坏性修改。</Hint>
      <ErrorLine error={error} />
      <div className="dialog-actions editor-actions-split">
        <div className="editor-actions-left">
          <button type="button" className="subtle-button" onClick={onOpenJson}>
            <FileJson size={14} />编辑 JSON
          </button>
          <button type="button" className="danger-button" onClick={onDelete}>
            <Trash2 size={14} />删除视图
          </button>
        </div>
        <div className="editor-actions-right">
          <button type="button" className="subtle-button" onClick={onClose}>取消</button>
          <button type="submit" className="primary-button" disabled={busy}>
            <Save size={14} />{busy ? '保存中…' : '保存'}
          </button>
        </div>
      </div>
    </form>
  </Modal>;
}

export function ViewJsonDialog({config, onApply, onClose}: {
  config: ViewConfig;
  onApply: ApplyView;
  onClose: () => void;
}) {
  const [text, setText] = useState(() => JSON.stringify(config, null, 2));
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError('');
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch (reason) {
      setError('JSON 解析失败：' + (reason instanceof Error ? reason.message : String(reason)));
      return;
    }
    if (!parsed || typeof parsed !== 'object') {
      setError('视图 JSON 必须是对象');
      return;
    }
    const nextView = (parsed as {view?: {id?: string}}).view;
    if (!nextView || nextView.id !== config.view.id) {
      setError(`视图 id 不能修改（当前是 ${config.view.id}）；需要新 id 请新建视图。`);
      return;
    }
    setBusy(true);
    try {
      await onApply(parsed as ViewConfig);
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  return <Modal title="编辑视图 JSON" onClose={onClose} wide>
    <form className="editor-form" onSubmit={submit}>
      <Hint>直接编辑整个视图。保存会先通过完整校验，再按规范格式重写文件；未知字段会被丢弃。</Hint>
      <textarea className="editor-json" spellCheck={false} value={text}
        onChange={event => setText(event.target.value)} />
      <ErrorLine error={error} />
      <div className="dialog-actions">
        <button type="button" className="subtle-button" onClick={onClose}>取消</button>
        <button type="submit" className="primary-button" disabled={busy}>
          <Save size={14} />{busy ? '保存中…' : '保存 JSON'}
        </button>
      </div>
    </form>
  </Modal>;
}

/* ------------------------------------------------------------------ */
/* Project settings                                                    */
/* ------------------------------------------------------------------ */

export function ProjectSettingsDialog({workspacePath, onApply, onClose}: {
  workspacePath: string;
  onApply: (result: SaveProjectResponse) => void;
  onClose: () => void;
}) {
  const [manifest, setManifest] = useState<ProjectManifest>();
  const [revision, setRevision] = useState('');
  const [views, setViews] = useState<ViewMeta[]>([]);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [root, setRoot] = useState('.');
  const [files, setFiles] = useState<string[]>([]);
  const [entry, setEntry] = useState('');
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    fetchProject(workspacePath).then(data => {
      if (cancelled) return;
      setManifest(data.manifest);
      setRevision(data.revision);
      setViews(data.index.views);
      setName(data.manifest.project.name);
      setDescription(data.manifest.project.description);
      setRoot(data.manifest.project.root);
      setFiles([...data.manifest.files]);
      setEntry(data.manifest.views.entry || data.index.entry
        || data.index.views[0]?.view_id || '');
      setLoading(false);
    }).catch(reason => {
      if (cancelled) return;
      setError(reason instanceof Error ? reason.message : String(reason));
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [workspacePath, reloadKey]);

  function updateFile(index: number, value: string) {
    setFiles(previous => previous.map((file, at) => at === index ? value : file));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!manifest) return;
    setError('');
    const nextName = name.trim();
    const nextDescription = description.trim();
    const nextRoot = root.trim();
    const nextFiles = files.map(file => file.trim());
    if (!nextName || !nextDescription || !nextRoot) {
      setError('项目名称、项目描述和源码根目录都不能为空');
      return;
    }
    if (nextFiles.some(file => !file)) {
      setError('源码文件路径不能为空；不需要的行请删除');
      return;
    }
    if (new Set(nextFiles).size !== nextFiles.length) {
      setError('源码文件路径不能重复');
      return;
    }
    if (!entry) {
      setError('请选择入口视图');
      return;
    }
    setBusy(true);
    try {
      const result = await saveProject(workspacePath, {
        ...manifest,
        project: {
          ...manifest.project,
          name: nextName,
          description: nextDescription,
          root: nextRoot,
        },
        files: nextFiles,
        views: {...manifest.views, entry},
      }, revision);
      onApply(result);
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  return <Modal title="项目设置" onClose={onClose}>
    {loading ? <Hint>正在读取项目设置…</Hint>
      : !manifest ? <>
          <ErrorLine error={error} />
          <div className="dialog-actions">
            <button type="button" className="subtle-button" onClick={onClose}>关闭</button>
            <button type="button" className="primary-button"
              onClick={() => setReloadKey(value => value + 1)}>重试</button>
          </div>
        </>
      : <form className="editor-form" onSubmit={submit}>
          <div className="editor-readonly">
            <ReadonlyRow label="工作区" value={<code>{workspacePath}</code>} />
            <ReadonlyRow label="视图后缀" value={manifest.views.suffix || '.blocks.json'} />
            <ReadonlyRow label="清单修订" value={revision.slice(0, 12)} />
          </div>
          <div className="editor-form-grid">
            <label className="editor-field"><span>项目名称</span>
              <input value={name} onChange={event => setName(event.target.value)} />
            </label>
            <label className="editor-field"><span>源码根目录 root</span>
              <input value={root} onChange={event => setRoot(event.target.value)}
                placeholder="." />
            </label>
            <label className="editor-field editor-field-wide"><span>项目描述</span>
              <input value={description} onChange={event => setDescription(event.target.value)} />
            </label>
            <label className="editor-field"><span>入口视图</span>
              <select value={entry} onChange={event => setEntry(event.target.value)}>
                {views.map(view => <option key={view.view_id} value={view.view_id}>
                  {view.view_id} · {view.name}
                </option>)}
              </select>
            </label>
          </div>
          <fieldset className="editor-fieldset">
            <legend>可映射源码文件</legend>
            <Hint>相对 root 的路径。只有这里声明的文件，块的 code_mapping 才能引用。</Hint>
            <div className="project-file-list">
              {files.map((file, index) => <div className="project-file-row" key={index}>
                <input value={file} placeholder="src/main.py"
                  onChange={event => updateFile(index, event.target.value)} />
                <button type="button" className="editor-icon-button"
                  aria-label={`删除文件 ${index + 1}`}
                  onClick={() => setFiles(previous => previous.filter((_, at) => at !== index))}>
                  <Trash2 size={13} />
                </button>
              </div>)}
            </div>
            <button type="button" className="subtle-button project-add-file"
              onClick={() => setFiles(previous => [...previous, ''])}>
              <Plus size={13} />添加文件
            </button>
          </fieldset>
          <Hint>保存会先校验 root 和 files 是否真实存在，再跑整项目复检；失败会回滚 codifold.json。</Hint>
          <ErrorLine error={error} />
          <div className="dialog-actions">
            <button type="button" className="subtle-button" onClick={onClose}>取消</button>
            <button type="submit" className="primary-button" disabled={busy}>
              <Save size={14} />{busy ? '保存中…' : '保存项目设置'}
            </button>
          </div>
        </form>}
  </Modal>;
}

/* ------------------------------------------------------------------ */
/* Workspace                                                           */
/* ------------------------------------------------------------------ */

export function WorkspaceDialog({currentPath, initialBrowse, initialTab, onOpen, onClose}: {
  currentPath?: string;
  initialBrowse?: boolean;
  initialTab?: 'open' | 'new';
  onOpen: (path: string) => void;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<'open' | 'new'>(initialTab || 'open');
  const [path, setPath] = useState(currentPath || '');
  const [browsing, setBrowsing] = useState(!!initialBrowse);
  const [listing, setListing] = useState<BrowseResponse>();
  const [browseLoading, setBrowseLoading] = useState(false);
  const [browseError, setBrowseError] = useState('');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [viewId, setViewId] = useState('main');
  const [viewName, setViewName] = useState('主流程');
  const [recent, setRecent] = useState<RecentWorkspace[]>([]);
  const [recentLoading, setRecentLoading] = useState(true);
  const [recentError, setRecentError] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<RecentWorkspace>();
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setRecentLoading(true);
    setRecentError('');
    fetchRecentWorkspaces().then(data => {
      if (cancelled) return;
      setRecent(data.recent);
      setRecentLoading(false);
    }).catch(reason => {
      if (cancelled) return;
      setRecentError(reason instanceof Error ? reason.message : String(reason));
      setRecentLoading(false);
    });
    return () => { cancelled = true; };
  }, []);

  async function openPath(target: string) {
    setError('');
    setNotice('');
    if (!target.trim()) {
      setError('请填写工作区目录');
      return;
    }
    setBusy(true);
    try {
      const result = await openWorkspaceApi(target.trim());
      onOpen(result.index.source.path || target.trim());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function browseTo(target?: string) {
    setBrowseLoading(true);
    setBrowseError('');
    try {
      const result = await browseDirectory(target);
      setListing(result);
      if (result.is_workspace) setPath(result.path);
    } catch (reason) {
      setBrowseError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBrowseLoading(false);
    }
  }

  function openBrowser() {
    setBrowsing(true);
    const target = path.trim().startsWith('/') ? path.trim() : currentPath;
    void browseTo(target);
  }

  useEffect(() => {
    if (!initialBrowse) return;
    void browseTo(currentPath || undefined);
    // 只在打开窗口时定位一次；之后由目录列表驱动。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function openCurrentDirectory() {
    if (!listing?.is_workspace) return;
    setPath(listing.path);
    setBrowsing(false);
    await openPath(listing.path);
  }

  async function open(event: FormEvent) {
    event.preventDefault();
    await openPath(path);
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    setError('');
    setNotice('');
    if (!path.trim() || !name.trim() || !description.trim()) {
      setError('目录、项目名称和项目描述都不能为空');
      return;
    }
    setBusy(true);
    try {
      const result = await createWorkspace({
        directory: path.trim(), name: name.trim(), description: description.trim(),
        view_id: viewId.trim() || 'main', view_name: viewName.trim() || '主流程',
      });
      onOpen(result.index.source.path || path.trim());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function forgetRecent(item: RecentWorkspace) {
    setError('');
    setNotice('');
    try {
      const result = await forgetWorkspace(item.path);
      setRecent(result.recent);
      setNotice(`已从最近列表移除：${item.name || item.path}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function removeWorkspace() {
    if (!deleteTarget) return;
    setError('');
    setNotice('');
    setBusy(true);
    try {
      const result = await deleteWorkspace(deleteTarget.path, deleteTarget.path);
      setRecent(result.recent);
      setNotice(`已删除工作区：${deleteTarget.name || deleteTarget.path}`);
      setDeleteTarget(undefined);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  const current = deleteTarget;
  return <Modal title={current ? '删除工作区' : '工作区'} onClose={onClose}>
    {current ? <div className="workspace-delete-confirm">
      <span className="workspace-delete-icon"><Trash2 size={22} /></span>
      <h3>确定永久删除这个工作区？</h3>
      <code>{current.path}</code>
      <p>目录里的 codifold.json、视图文件和源码会一起删除，无法撤销。</p>
      {current.path === currentPath && <p className="editor-error">
        不能删除当前正在使用的工作区，请先切换到其他工作区。
      </p>}
      <ErrorLine error={error} />
      <div className="dialog-actions">
        <button type="button" className="subtle-button"
          onClick={() => {setDeleteTarget(undefined); setError('');}}>取消</button>
        <button type="button" className="danger-button"
          disabled={busy || current.path === currentPath}
          onClick={() => void removeWorkspace()}>
          <Trash2 size={14} />{busy ? '删除中…' : '永久删除目录'}
        </button>
      </div>
    </div> : <>
      <div className="editor-tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === 'open'}
          className={tab === 'open' ? 'active' : ''}
          onClick={() => {setTab('open'); setError(''); setNotice('');}}>
          <FolderOpen size={14} />打开
        </button>
        <button type="button" role="tab" aria-selected={tab === 'new'}
          className={tab === 'new' ? 'active' : ''}
          onClick={() => {setTab('new'); setError(''); setNotice('');}}>
          <Plus size={14} />新建
        </button>
      </div>
      {currentPath && <p className="editor-current-path">当前：<code>{currentPath}</code></p>}
      {tab === 'open'
        ? <form className="editor-form" onSubmit={open}>
            {browsing ? <div className="workspace-browser">
              <div className="workspace-browser-head">
                <button type="button" className="subtle-button"
                  disabled={!listing?.parent || browseLoading}
                  onClick={() => void browseTo(listing?.parent || undefined)}>
                  <ArrowUp size={13} />上一级
                </button>
                <code title={listing?.path}>{listing?.path || '正在读取…'}</code>
                <button type="button" className="subtle-button"
                  onClick={() => setBrowsing(false)}>返回手输</button>
              </div>
              <div className="workspace-shortcuts">
                {listing?.shortcuts.map(item => <button key={item.path} type="button"
                    onClick={() => void browseTo(item.path)}>
                  {item.name === '主目录' ? <Home size={12} /> : <Folder size={12} />}
                  {item.name}
                </button>)}
              </div>
              {browseError && <p className="editor-error" role="alert">{browseError}</p>}
              {browseLoading
                ? <div className="workspace-browser-empty">正在读取目录…</div>
                : listing && (listing.entries.length
                  ? <div className="workspace-dir-list">
                      {listing.entries.map(entry => <button key={entry.path} type="button"
                          className={`workspace-dir-row ${entry.is_workspace ? 'is-workspace' : ''}`}
                          onClick={() => void browseTo(entry.path)}>
                        <Folder size={15} />
                        <b>{entry.name}</b>
                        {entry.is_workspace && <em>工作区</em>}
                        <ChevronRight size={14} className="workspace-dir-arrow" />
                      </button>)}
                    </div>
                  : <div className="workspace-browser-empty">这个目录下没有子目录。</div>)}
              {listing?.truncated && <p className="editor-hint">目录过多，只显示前 400 个。</p>}
              <p className={`workspace-browser-current ${listing?.is_workspace ? 'ok' : ''}`}>
                {listing?.is_workspace
                  ? '当前目录是工作区，可以直接打开。'
                  : <>当前目录不是工作区；请进入带 <code>codifold.json</code> 的目录。</>}
              </p>
              <div className="dialog-actions">
                <button type="button" className="subtle-button"
                  onClick={() => setBrowsing(false)}>取消</button>
                <button type="button" className="primary-button"
                  disabled={!listing?.is_workspace || busy}
                  onClick={() => void openCurrentDirectory()}>
                  <FolderOpen size={14} />{busy ? '打开中…' : '打开此工作区'}
                </button>
              </div>
            </div> : <>
              <div className="workspace-recent">
                <div className="workspace-recent-head">
                  <span><Clock3 size={12} />最近打开</span>
                  <small>{recent.length}</small>
                </div>
                {recentLoading
                  ? <div className="workspace-recent-empty">正在读取最近工作区…</div>
                  : recentError
                    ? <div className="workspace-recent-empty">{recentError}</div>
                    : recent.length
                      ? <div className="workspace-recent-list">
                          {recent.map(item => <div key={item.path}
                              className={`workspace-recent-row ${item.path === currentPath ? 'current' : ''}`}>
                            <button type="button" className="workspace-recent-main"
                              disabled={busy || !item.exists}
                              title={item.exists ? `打开 ${item.path}` : '目录不存在'}
                              onClick={() => {setPath(item.path); void openPath(item.path);}}>
                              <b>{item.name || item.path.split('/').pop()}</b>
                              <small>{item.path}</small>
                              <span className="workspace-recent-meta">
                                {item.path === currentPath && <em className="current">当前</em>}
                                {!item.exists && <em>目录不存在</em>}
                                {item.description && <span>{item.description}</span>}
                              </span>
                            </button>
                            <div className="workspace-recent-actions">
                              <button type="button" title="从最近列表移除"
                                aria-label={`从最近列表移除 ${item.name || item.path}`}
                                disabled={busy}
                                onClick={() => void forgetRecent(item)}>
                                <X size={13} />
                              </button>
                              <button type="button" className="danger" title={
                                item.path === currentPath ? '不能删除当前工作区'
                                  : !item.exists ? '目录不存在' : '删除工作区目录'}
                                aria-label={`删除工作区 ${item.name || item.path}`}
                                disabled={busy || !item.exists || item.path === currentPath}
                                onClick={() => {
                                  setDeleteTarget(item);
                                  setError('');
                                  setNotice('');
                                }}>
                                <Trash2 size={13} />
                              </button>
                            </div>
                          </div>)}
                        </div>
                      : <div className="workspace-recent-empty">还没有最近打开的工作区。</div>}
              </div>
              {notice && <p className="editor-hint" role="status">{notice}</p>}
              <label className="editor-field"><span>工作区目录</span>
                <span className="workspace-path-row">
                  <input value={path} onChange={event => setPath(event.target.value)}
                    placeholder="/path/to/project 或 ~/projects/demo" autoFocus />
                  <button type="button" className="subtle-button" onClick={openBrowser}>
                    <FolderOpen size={13} />浏览…
                  </button>
                </span>
              </label>
              <Hint>目录里必须有 codifold.json；打开成功后会记入最近列表。</Hint>
              <ErrorLine error={error} />
              <div className="dialog-actions">
                <button type="button" className="subtle-button" onClick={onClose}>取消</button>
                <button type="submit" className="primary-button" disabled={busy}>
                  <FolderOpen size={14} />{busy ? '打开中…' : '打开工作区'}
                </button>
              </div>
            </>}
          </form>
        : <form className="editor-form" onSubmit={create}>
            <div className="editor-form-grid">
              <label className="editor-field editor-field-wide"><span>工作区目录</span>
                <input value={path} onChange={event => setPath(event.target.value)}
                  placeholder="/path/to/new-project 或 ~/projects/new" autoFocus />
              </label>
              <label className="editor-field"><span>项目名称</span>
                <input value={name} onChange={event => setName(event.target.value)}
                  placeholder="例如：订单系统" />
              </label>
              <label className="editor-field"><span>入口视图 id</span>
                <input value={viewId} onChange={event => setViewId(event.target.value)}
                  placeholder="main" />
              </label>
              <label className="editor-field editor-field-wide"><span>项目描述</span>
                <input value={description} onChange={event => setDescription(event.target.value)}
                  placeholder="一句话说明这个项目。" />
              </label>
              <label className="editor-field"><span>入口视图名称</span>
                <input value={viewName} onChange={event => setViewName(event.target.value)}
                  placeholder="主流程" />
              </label>
            </div>
            <Hint>会创建 codifold.json 和一个只有“开始”块的视图。目录必须为空或不存在，且不能覆盖已有文件。</Hint>
            <ErrorLine error={error} />
            <div className="dialog-actions">
              <button type="button" className="subtle-button" onClick={onClose}>取消</button>
              <button type="submit" className="primary-button" disabled={busy}>
                <Plus size={14} />{busy ? '创建中…' : '新建工作区'}
              </button>
            </div>
          </form>}
    </>}
  </Modal>;
}

/* ------------------------------------------------------------------ */
/* Confirm                                                             */
/* ------------------------------------------------------------------ */

export function ConfirmDialog({title, message, confirmLabel = '确认', onConfirm, onClose}: {
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  onConfirm: () => Promise<void>;
  onClose: () => void;
}) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function confirm() {
    setError('');
    setBusy(true);
    try {
      await onConfirm();
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  return <Modal title={title} onClose={onClose}>
    <div className="editor-confirm">
      <p>{message}</p>
      <Hint>保存前会通过完整校验；被引用的块或视图会被服务端拒绝删除。</Hint>
      <ErrorLine error={error} />
      <div className="dialog-actions">
        <button type="button" className="subtle-button" onClick={onClose}>取消</button>
        <button type="button" className="danger-button" disabled={busy} onClick={confirm}>
          <Trash2 size={14} />{busy ? '删除中…' : confirmLabel}
        </button>
      </div>
    </div>
  </Modal>;
}
