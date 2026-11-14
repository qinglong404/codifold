import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import type {CSSProperties} from 'react';
import {
  BaseEdge, ReactFlow, Background, BackgroundVariant, EdgeLabelRenderer,
  Handle, MarkerType, Position, useReactFlow,
} from '@xyflow/react';
import type {Edge, EdgeProps, Node, NodeProps} from '@xyflow/react';
import {
  ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Boxes, ChevronDown, ChevronRight, Code2,
  Eye, FileCode2, FolderOpen,
  GitBranch, GitFork, Layers3, Link2, Maximize2, Palette, Pencil, Plus,
  RefreshCw, Settings2, ShieldAlert, Sparkles, Square, Trash2, Zap, ZoomIn, ZoomOut,
} from 'lucide-react';
import {CodeLines} from './CodeView';
import {ContractSourceLinks, ContractTables} from './blocks-contract';
import {deleteView, mutateView, openWorkspace as openWorkspaceApi, saveView} from './blocks-api';
import {hasBlock, removeBlock} from './blocks-edit-utils';
import {FlatBlockTree} from './blocks-flat-tree';
import {HomeScreen} from './blocks-home';
import {
  BlockEditorDialog, ConfirmDialog, NewViewDialog, ProjectSettingsDialog,
  ViewJsonDialog, ViewSettingsDialog, WorkspaceDialog,
} from './blocks-editor';
import {
  isNeonStyle, isNormalStyleId, normalStyleName, NormalCardFace, NormalStyleGallery,
} from './blocks-styles';
import type {NormalStyleId, StyleSample} from './blocks-styles';
import {BLOCK_H, blockWidth, branchWidth, LIST_GAP} from './blocks-sizing';
import {
  themeCanvasDot, themeEdges, themeSurface, themeVars,
} from './blocks-theme';
import type {EdgeTone} from './blocks-theme';
import type {
  BlocksResponse, EventTarget, FlatViewConfig, RBlock, SaveProjectResponse,
  ViewConfig, ViewKind, ViewsIndex,
} from './blocks-types';

const NORMAL_STYLE_KEY = 'codifold.normalStyle';
const DEFAULT_NORMAL_STYLE: NormalStyleId = 'cyber';
const MOTION_KEY = 'codifold.motion';
type MotionMode = 'off' | 'subtle' | 'flow';
const MOTION_LABEL: Record<MotionMode, string> = {off: '关', subtle: '轻', flow: '流动'};
const DEFAULT_MOTION: MotionMode = typeof window !== 'undefined'
  && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'off' : 'subtle';
const isMotionMode = (value: string | null): value is MotionMode =>
  value === 'off' || value === 'subtle' || value === 'flow';
const CHAIN_GAP = 32;
const FINALLY_GAP = 60;
const FAN_LANE = 46;
const TOP_GAP = 48;
const SOURCE_LANE = 12;
const TARGET_LANE = 30;

type BranchTone = 'single' | 'multi' | 'try';
type SemanticRole = 'entry' | 'emit' | 'flow' | 'jump' | 'end';
type ViewGroupKey = 'main' | 'flow' | 'entry' | 'contract' | 'function' | 'details';
const VIEW_GROUPS: {key: ViewGroupKey; label: string; kinds: ViewKind[]}[] = [
  {key: 'main', label: '主线', kinds: ['main']},
  {key: 'flow', label: '流程', kinds: ['flow']},
  {key: 'entry', label: '事件入口', kinds: ['entry']},
  {key: 'contract', label: '契约', kinds: ['contract']},
  {key: 'function', label: '函数细节', kinds: ['function']},
  {key: 'details', label: '模块与工具', kinds: ['struct', 'toolbox']},
];

const edgeStyle = (colors: Record<EdgeTone, string>, tone: EdgeTone) => ({
  stroke: colors[tone],
  strokeWidth: 1.7,
  // 圆角端点/拐角：合并干线的接触点不会出现缺口。
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
});
const edgeMarker = (colors: Record<EdgeTone, string>, tone: EdgeTone) => ({
  type: MarkerType.ArrowClosed,
  color: colors[tone],
  width: 15,
  height: 15,
});

const keyOf = (block: RBlock) => `b${block.id}`;

const contractSummary = (block: RBlock): string | null => {
  const value = block.contract;
  if (!value) return null;
  return value.kind === 'type'
    ? `类型 · ${value.fields.length} 个字段`
    : `${value.method} ${value.path}`;
};

/** next 三态：缺省 = 顺序后继；整数 = 跳转；null = 显式终止。 */
const nextMode = (block: RBlock): 'default' | 'jump' | 'stop' =>
  block.next === null ? 'stop' : typeof block.next === 'number' ? 'jump' : 'default';

const branchTone = (block: RBlock): BranchTone =>
  block.kind === 'try' ? 'try' : block.select === 'multi' ? 'multi' : 'single';

const semanticRole = (block: RBlock): SemanticRole | null => {
  if (block.on) return 'entry';
  if (block.flow) return 'flow';
  if (block.emit?.length) return 'emit';
  if (block.jump) return 'jump';
  if (block.type === 'normal' && nextMode(block) !== 'jump'
      && (nextMode(block) === 'stop' || /结束|终止/.test(block.name))) return 'end';
  return null;
};

const SEMANTIC_LABEL: Record<SemanticRole, string> = {
  entry: '入口',
  emit: '发出',
  flow: '继续',
  jump: '跳转',
  end: '结束',
};

const semanticTitle = (block: RBlock, role: SemanticRole): string => {
  if (role === 'entry') return `事件入口：${block.on}`;
  if (role === 'emit') {
    return '事件发出：' + (block.emit || [])
      .map(item => `${item.view || '本视图'} · ${item.id}`).join('、');
  }
  if (role === 'flow') return flowTitle(block);
  if (role === 'jump') return jumpTitle(block);
  return '显式终止（next: null）';
};

const jumpTitle = (block: RBlock): string => block.jump
  ? `双击跳转到${block.jump.view ? `视图 ${block.jump.view} 的` : '本视图'}编号 ${block.jump.id}`
  : '';

const flowTitle = (block: RBlock): string => block.flow
  ? `主线继续到视图 ${block.flow.view} 的编号 ${block.flow.id}`
  : '';

function linesLabel(lines: (number | string)[]): string {
  return lines.map(item => typeof item === 'number'
    ? `L${item}`
    : `L${item.replace(/\s+/g, '').replace('-', '–')}`).join('、');
}

type Box = {x: number; y: number; w: number; h: number};
type Anchor = {key: string; cx: number; bottom: number; block: RBlock;
  dashed?: boolean; tone?: EdgeTone};
type NextPlan = {source: RBlock; sourceBox: Box; targetId: number; ancestors: number[]};
type Built = {block: RBlock; box: Box; ancestors: number[]};
type BlockNodeData = {block: RBlock; built: Built; selected: boolean;
  style: NormalStyleId; enterDelay: number;
  onSelect: (id: number) => void; onEvent: (block: RBlock, target: EventTarget) => void};
type BlockNode = Node<BlockNodeData, 'block'>;
type PathData = {path?: string; label?: string; labelX?: number; labelY?: number;
  dashed?: boolean; tone?: EdgeTone;
  active?: boolean; fan?: boolean; fanDelay?: number};

function sequenceHeight(steps: RBlock[], memo: Map<RBlock, {w: number; h: number}>): number {
  return steps.reduce((sum, step, index) =>
    sum + measure(step, true, memo).h + (index ? CHAIN_GAP : 0), 0);
}

function measure(block: RBlock, inList: boolean, memo: Map<RBlock, {w: number; h: number}>): {w: number; h: number} {
  const cached = memo.get(block);
  if (cached) return cached;
  let size: {w: number; h: number};
  if (block.type === 'normal' || !block.branches?.length) {
    size = {w: blockWidth(block.name, block.description), h: BLOCK_H};
  } else {
    const widths = block.branches.map(list => Math.max(0,
      ...list.steps.map(step => measure(step, true, memo).w)));
    const contentW = widths.reduce((sum, w) => sum + w, 0) + LIST_GAP * (block.branches.length - 1);
    const heights = block.branches.map(list => list.steps.reduce((sum, step, index) =>
      sum + measure(step, true, memo).h + (index ? CHAIN_GAP : 0), 0));
    const finallySteps = block.finally || [];
    const finallyW = finallySteps.length
      ? Math.max(0, ...finallySteps.map(step => measure(step, true, memo).w))
      : 0;
    const finallyH = sequenceHeight(finallySteps, memo);
    size = {
      w: Math.max(branchWidth(block.name, block.description), contentW, finallyW),
      h: BLOCK_H + FAN_LANE + Math.max(...heights)
        + (finallySteps.length ? FINALLY_GAP + finallyH : 0),
    };
  }
  memo.set(block, size);
  return size;
}

type Ctx = {
  memo: Map<RBlock, {w: number; h: number}>;
  built: Built[];
  nodes: BlockNode[];
  edges: Edge[];
  plans: NextPlan[];
  style: NormalStyleId;
  colors: Record<EdgeTone, string>;
  onSelect: (id: number) => void;
  onEvent: (block: RBlock, target: EventTarget) => void;
};

function pushEdge(ctx: Ctx, source: string, target: string, sh: string, th: string,
  path: string, label?: string, labelX?: number, labelY?: number, dashed = false,
  tone: EdgeTone = 'default') {
  ctx.edges.push({
    id: `edge-${ctx.edges.length}`, source, target, sourceHandle: sh, targetHandle: th,
    type: 'path', data: {path, label, labelX, labelY, dashed, tone},
    style: edgeStyle(ctx.colors, tone), markerEnd: edgeMarker(ctx.colors, tone),
  });
}

/** 列表尾汇入下一块：每条出口先落到同一条车道，再一起进入目标顶部。 */
function mergeEdges(ctx: Ctx, anchors: Anchor[], target: RBlock, targetTop: number, targetCx: number) {
  const laneY = targetTop - 22;
  anchors.forEach(anchor => pushEdge(ctx, anchor.key, keyOf(target), 'bottom-out', 'top-in',
    `M ${anchor.cx} ${anchor.bottom} V ${laneY} H ${targetCx} V ${targetTop}`,
    undefined, undefined, undefined, anchor.dashed, anchor.tone || 'default'));
}

/** 顺序布局：块之间默认上下相连；返回尚未接续的出口。 */
function layoutSequence(steps: RBlock[], cx: number, top: number, ancestors: number[],
  ctx: Ctx, tone: EdgeTone = 'default'): {pending: Anchor[]; bottom: number} {
  let pending: Anchor[] = [];
  let y = top;
  steps.forEach(step => {
    if (pending.length) mergeEdges(ctx, pending, step, y, cx);
    const result = layoutBlock(step, cx, y, ancestors, true, ctx, tone);
    pending = nextMode(step) === 'default' ? result.exits : [];
    y += result.height + CHAIN_GAP;
  });
  return {pending, bottom: y - CHAIN_GAP};
}

function layoutBlock(block: RBlock, cx: number, top: number, ancestors: number[],
  inList: boolean, ctx: Ctx, tone: EdgeTone = 'default'): {exits: Anchor[]; height: number} {
  const size = measure(block, inList, ctx.memo);
  // 分支块本身只是一个分支点，不占满下面的分支布局。
  const nodeW = block.type === 'branch' ? branchWidth(block.name, block.description) : size.w;
  const nodeH = block.type === 'branch' ? BLOCK_H : size.h;
  const box: Box = {x: cx - nodeW / 2, y: top, w: nodeW, h: nodeH};
  const built: Built = {block, box, ancestors};
  ctx.built.push(built);
  const enterDelay = Math.min(240, Math.max(0, Math.round((top - 8) / 64) * 18));
  ctx.nodes.push({
    id: keyOf(block), type: 'block', position: {x: box.x, y: box.y},
    width: box.w, height: box.h, zIndex: block.type === 'branch' ? 3 : 4,
    data: {block, built, selected: false, style: ctx.style, enterDelay,
      onSelect: ctx.onSelect, onEvent: ctx.onEvent},
    style: {'--enter-delay': `${enterDelay}ms`} as CSSProperties,
    draggable: false, selectable: true, connectable: false, ariaLabel: block.name,
  });
  if (block.type === 'normal') {
    const mode = nextMode(block);
    if (mode === 'stop') return {exits: [], height: size.h};
    if (mode === 'jump') {
      ctx.plans.push({source: block, sourceBox: box, targetId: block.next as number,
        ancestors: [...ancestors, block.id]});
      return {exits: [], height: size.h};
    }
    return {exits: [{key: keyOf(block), cx, bottom: top + size.h, block, tone}],
      height: size.h};
  }
  // 条件分支块：只用线条扇出到各条分支列表，不再有容器框。
  const lists = block.branches!;
  const widths = lists.map(list => Math.max(0,
    ...list.steps.map(step => measure(step, true, ctx.memo).w)));
  const contentW = widths.reduce((sum, w) => sum + w, 0) + LIST_GAP * (lists.length - 1);
  const startX = cx - contentW / 2;
  const listsTop = top + nodeH + FAN_LANE;
  const fanLaneY = top + nodeH + FAN_LANE / 2;
  const exits: Anchor[] = [];
  // size.h 已经包含 finally；这里只取分支内容的底边，finally 的间距只在下面加一次。
  let bottom = top + nodeH + FAN_LANE;
  const parentTone = branchTone(block);
  let lx = startX;
  lists.forEach((list, index) => {
    const lcx = lx + widths[index]! / 2;
    const listTone: EdgeTone = block.kind === 'try'
      ? (list.role === 'except' ? 'except' : 'try')
      : parentTone;
    const result = layoutSequence(list.steps, lcx, listsTop, [...ancestors, block.id],
      ctx, listTone);
    const first = list.steps[0]!;
    pushEdge(ctx, keyOf(block), keyOf(first), 'fan-out', 'top-in',
      `M ${cx} ${top + nodeH} V ${fanLaneY} H ${lcx} V ${listsTop}`,
      list.condition, lcx, fanLaneY, list.role === 'except', listTone);
    result.pending.forEach(anchor => {
      if (list.role === 'except') anchor.dashed = true;
      anchor.tone = listTone;
    });
    exits.push(...result.pending);
    bottom = Math.max(bottom, result.bottom);
    lx += widths[index]! + LIST_GAP;
  });
  if (block.finally?.length) {
    const finallyTop = bottom + FINALLY_GAP;
    mergeEdges(ctx, exits, block.finally[0]!, finallyTop, cx);
    const tail = layoutSequence(block.finally, cx, finallyTop, [...ancestors, block.id],
      ctx, 'finally');
    return {exits: tail.pending, height: tail.bottom - top};
  }
  return {exits, height: bottom - top};
}

/** next 跳转的连线规则（目标在上/在下 + 在左/在右）：
 *  - B 在 A 下面：A 从底部出；同列直接进 B 顶部，否则进 B 朝向 A 的那一侧。
 *  - B 在 A 上面：A 从左右出；B 在左则 A 左 → B 右，B 在右则 A 右 → B 左。
 *  - 同列上下回环：贴列边绕，两段折线。
 *  - 优先两段折线；只有被块挡住才在空行里加一次横向绕行。 */
function routeNext(ctx: Ctx, plan: NextPlan) {
  const target = ctx.built.find(item => item.block.id === plan.targetId);
  if (!target) return;
  const nextEdge = (source: string, targetId: string, sh: string, th: string, path: string) =>
    pushEdge(ctx, source, targetId, sh, th, path, undefined, undefined, undefined, false, 'next');
  const s = plan.sourceBox, t = target.box;
  const nodes = ctx.nodes;
  // 只排除连线的两个端点。祖先分支块的卡片同样占空间：回指上层时
  // 竖线若穿过父分支块，就是穿模，不能因为“它是祖先”而放行。
  const excluded = new Set([`b${plan.source.id}`, `b${target.block.id}`]);
  const blocked = (x1: number, x2: number, y: number) => nodes.some(node => {
    if (excluded.has(node.id)) return false;
    const p = node.position, w = node.width ?? 0, h = node.height ?? 0;
    return y > p.y + 2 && y < p.y + h - 2
      && Math.max(x1, x2) > p.x + 2 && Math.min(x1, x2) < p.x + w - 2;
  });
  const vBlocked = (x: number, y1: number, y2: number) => nodes.some(node => {
    if (excluded.has(node.id)) return false;
    const p = node.position, w = node.width ?? 0, h = node.height ?? 0;
    return x > p.x + 2 && x < p.x + w - 2
      && Math.max(y1, y2) > p.y + 2 && Math.min(y1, y2) < p.y + h - 2;
  });
  const scx = s.x + s.w / 2, tcx = t.x + t.w / 2;
  const scy = s.y + s.h / 2, tcy = t.y + t.h / 2;
  const sBottom = s.y + s.h;
  const globalLeft = Math.min(...nodes.map(node => node.position.x));
  const globalRight = Math.max(...nodes.map(node => node.position.x + (node.width ?? 0)));
  const columnBounds = (cx: number) => {
    const column = nodes.filter(node => Math.abs(node.position.x + (node.width ?? 0) / 2 - cx) < 1);
    return {
      left: Math.min(...column.map(node => node.position.x)),
      right: Math.max(...column.map(node => node.position.x + (node.width ?? 0))),
    };
  };
  // 顶层块的走廊必须绕开整个分支展开区；分支内步骤才走列间空隙。
  // 源侧走廊和入侧走廊用不同偏移，避免反向箭头共用同一条竖线。
  const laneFor = (cx: number, topLevel: boolean, side: 'left' | 'right',
    role: 'source' | 'target' = 'source') => {
    if (topLevel) return side === 'left' ? globalLeft - 26 : globalRight + 26;
    const bounds = columnBounds(cx);
    const offset = role === 'target' ? TARGET_LANE : SOURCE_LANE;
    return side === 'left' ? bounds.left - offset : bounds.right + offset;
  };
  const sourceTop = plan.ancestors.length === 0;
  const targetTop = target.ancestors.length === 0;
  const horizontal = tcy < scy - 1 ? 'above' : tcy > scy + 1 ? 'below' : 'same';
  const targetIsLeft = tcx < scx;
  const side: 'left' | 'right' = targetIsLeft ? 'left' : 'right';
  const targetEntrySide: 'left' | 'right' = side === 'left' ? 'right' : 'left';
  const sourceSide = side === 'left' ? s.x : s.x + s.w;
  const targetFacing = side === 'left' ? t.x + t.w : t.x;
  // 入侧上/下错开：右侧入口偏上，左侧入口偏下，反向箭头不会撞在同一高度。
  const entryY = t.y + t.h * (targetEntrySide === 'right' ? 0.28 : 0.72);

  // B 在下面：底部出线；同列直落，错列在目标中线横向进入朝向 A 的一侧。
  if (horizontal === 'below') {
    if (Math.abs(tcx - scx) < 1) {
      nextEdge(keyOf(plan.source), keyOf(target.block), 'bottom-out', 'top-in',
        `M ${scx} ${sBottom} V ${t.y}`);
      return;
    }
    // 源块横向落在更宽的目标块范围内：从目标顶部中心进入，避免横线穿过目标。
    if (scx > t.x + 2 && scx < t.x + t.w - 2) {
      const gapY = [t.y - 14, t.y - 26, t.y - 38,
        ...nodes.map(node => node.position.y - 14)]
        .filter(y => y > sBottom + 6 && y < t.y - 4)
        .sort((a, b) => b - a)
        .find(y => !blocked(scx, tcx, y) && !vBlocked(tcx, y, t.y));
      if (gapY !== undefined) {
        nextEdge(keyOf(plan.source), keyOf(target.block), 'bottom-out', 'top-in',
          `M ${scx} ${sBottom} V ${gapY} H ${tcx} V ${t.y}`);
        return;
      }
    }
    if (!vBlocked(scx, sBottom, entryY) && !blocked(scx, targetFacing, entryY)) {
      nextEdge(keyOf(plan.source), keyOf(target.block), 'bottom-out',
        side === 'left' ? 'right-in' : 'left-in',
        `M ${scx} ${sBottom} V ${entryY} H ${targetFacing}`);
      return;
    }
    // 被中间块挡住：从源列外侧下来，在目标上方空行横移，从顶部进入。
    const sourceLaneX = laneFor(scx, sourceTop, side, 'source');
    const gapY = [t.y - 14, t.y - 26, sBottom + 16,
      ...nodes.map(node => node.position.y - 14)]
      .filter(y => y > sBottom + 6 && y < t.y - 4)
      .sort((a, b) => b - a)
      .find(y => !blocked(sourceLaneX, tcx, y) && !vBlocked(tcx, y, t.y));
    if (gapY !== undefined) {
      nextEdge(keyOf(plan.source), keyOf(target.block), 'bottom-out', 'top-in',
        `M ${scx} ${sBottom} V ${sBottom + 14} H ${sourceLaneX} V ${gapY} H ${tcx} V ${t.y}`);
      return;
    }
    nextEdge(keyOf(plan.source), keyOf(target.block), 'bottom-out', 'top-in',
      `M ${scx} ${sBottom} V ${t.y - 14} H ${tcx} V ${t.y}`);
    return;
  }

  // B 在上面：两侧出线。同列贴列边回环；错列优先两段折线（源侧 → 行间竖线 → 目标侧）。
  if (horizontal === 'above') {
    if (Math.abs(tcx - scx) < 1) {
      const preferred: 'left' | 'right' = scx <= (globalLeft + globalRight) / 2 ? 'left' : 'right';
      // 分支内步骤回指上层时，源和目标可能被布局放在同一列。
      // 先试靠近整图中线的一侧，再试另一侧；两条边都要检查横线出口
      // 和竖线走廊，避免竖线穿过更宽的父分支块或兄弟卡片。
      for (const loopSide of [preferred, preferred === 'left' ? 'right' as const : 'left' as const]) {
        const laneX = laneFor(scx, sourceTop, loopSide);
        const loopEntryY = t.y + t.h * (loopSide === 'right' ? 0.28 : 0.72);
        const sourceSideX = loopSide === 'left' ? s.x : s.x + s.w;
        const targetSideX = loopSide === 'left' ? t.x : t.x + t.w;
        if (blocked(sourceSideX, laneX, scy) || vBlocked(laneX, loopEntryY, scy)
          || blocked(laneX, targetSideX, loopEntryY)) continue;
        nextEdge(keyOf(plan.source), keyOf(target.block),
          loopSide === 'left' ? 'left-out' : 'right-out',
          loopSide === 'left' ? 'left-in' : 'right-in',
          `M ${sourceSideX} ${scy} H ${laneX} V ${loopEntryY} H ${targetSideX}`);
        return;
      }
      // 两侧都不通：交给下面的通用绕行，用空行横移。
    }
    const laneX = laneFor(scx, sourceTop, side, 'source');
    const laneOutsideTarget = side === 'left' ? laneX > targetFacing : laneX < targetFacing;
    if (laneOutsideTarget && !blocked(sourceSide, laneX, scy) && !vBlocked(laneX, entryY, scy)
      && !blocked(laneX, targetFacing, entryY)) {
      nextEdge(keyOf(plan.source), keyOf(target.block),
        side === 'left' ? 'left-out' : 'right-out',
        side === 'left' ? 'right-in' : 'left-in',
        `M ${sourceSide} ${scy} H ${laneX} V ${entryY} H ${targetFacing}`);
      return;
    }
    // 被块挡住：沿两侧走廊上下，在无块的空行横移。
    // 进目标的右侧，走廊就放在目标右侧；进左侧同理，避免横线穿过目标块。
    const sourceLaneX = laneFor(scx, sourceTop, side, 'source');
    const targetLaneX = laneFor(tcx, targetTop, targetEntrySide, 'target');
    const desired = (scy + entryY) / 2;
    const gapY = [t.y - 14, t.y - 26, s.y - 14,
      ...nodes.flatMap(node => [node.position.y - 14, node.position.y + (node.height ?? 0) + 14])]
      .filter(y => !vBlocked(sourceLaneX, y, scy) && !vBlocked(targetLaneX, entryY, y))
      .sort((a, b) => Math.abs(a - desired) - Math.abs(b - desired))
      .find(y => !blocked(sourceLaneX, targetLaneX, y)) ?? t.y - 14;
    nextEdge(keyOf(plan.source), keyOf(target.block),
      side === 'left' ? 'left-out' : 'right-out',
      side === 'left' ? 'right-in' : 'left-in',
      `M ${sourceSide} ${scy} H ${sourceLaneX} V ${gapY} H ${targetLaneX} V ${entryY} H ${targetFacing}`);
    return;
  }

  // 同一水平带：左右直连。
  if (!blocked(sourceSide, targetFacing, scy)) {
    nextEdge(keyOf(plan.source), keyOf(target.block),
      side === 'left' ? 'left-out' : 'right-out',
      side === 'left' ? 'right-in' : 'left-in',
      `M ${sourceSide} ${scy} H ${targetFacing}`);
    return;
  }
  // 同排但被中间块挡住：走两侧走廊，从目标朝向 A 的一侧进入。
  const sourceLaneX = laneFor(scx, sourceTop, side, 'source');
  const targetLaneX = laneFor(tcx, targetTop, targetEntrySide, 'target');
  const desired = (scy + entryY) / 2;
  const gapY = [s.y - 14, t.y - 14,
    ...nodes.flatMap(node => [node.position.y - 14, node.position.y + (node.height ?? 0) + 14])]
    .filter(y => !vBlocked(sourceLaneX, y, scy) && !vBlocked(targetLaneX, entryY, y))
    .sort((a, b) => Math.abs(a - desired) - Math.abs(b - desired))
    .find(y => !blocked(sourceLaneX, targetLaneX, y)) ?? s.y - 14;
  nextEdge(keyOf(plan.source), keyOf(target.block),
    side === 'left' ? 'left-out' : 'right-out',
    side === 'left' ? 'right-in' : 'left-in',
    `M ${sourceSide} ${scy} H ${sourceLaneX} V ${gapY} H ${targetLaneX} V ${entryY} H ${targetFacing}`);
}

type PathPoint = [number, number];

/** 解析本文件生成的 M/V/H 折线。 */
function parseOrthogonalPath(path: string): PathPoint[] | null {
  const tokens = path.match(/[MVH][^MVH]*/g) || [];
  let x = 0;
  let y = 0;
  const points: PathPoint[] = [];
  for (const token of tokens) {
    const numbers = (token.slice(1).match(/-?\d+(?:\.\d+)?/g) || []).map(Number);
    if (token[0] === 'M') {
      if (numbers.length < 2) return null;
      x = numbers[0]!;
      y = numbers[1]!;
    } else if (token[0] === 'V') {
      if (!numbers.length) return null;
      y = numbers[0]!;
    } else if (token[0] === 'H') {
      if (!numbers.length) return null;
      x = numbers[0]!;
    } else {
      return null;
    }
    points.push([x, y]);
  }
  return points.length >= 2 ? points : null;
}

function formatOrthogonalPath(points: PathPoint[]): string | null {
  const fmt = (value: number) => String(Math.round(value * 100) / 100);
  let path = `M ${fmt(points[0]![0])} ${fmt(points[0]![1])}`;
  for (let index = 1; index < points.length; index += 1) {
    const [x, y] = points[index]!;
    const [px, py] = points[index - 1]!;
    if (x === px) path += ` V ${fmt(y)}`;
    else if (y === py) path += ` H ${fmt(x)}`;
    else return null;
  }
  return path;
}

/** 电线式合并：同一目标、同一入口、同色同虚实的多条线共用最后一段，
 *  其余线在分叉点截断。截断线不再画箭头，视觉上接触即连通。 */
function mergeSharedTrunks(edges: Edge[]) {
  type Item = {edge: Edge; data: PathData; points: PathPoint[]};
  const groups = new Map<string, Item[]>();
  edges.forEach(edge => {
    const data = edge.data as PathData | undefined;
    if (!data?.path || !edge.target || !edge.targetHandle) return;
    const points = parseOrthogonalPath(data.path);
    if (!points) return;
    const end = points[points.length - 1]!;
    const entry = `${Math.round(end[0] * 100)},${Math.round(end[1] * 100)}`;
    const key = `${edge.target}|${edge.targetHandle}|${entry}|${data.tone || 'default'}|${data.dashed ? 1 : 0}`;
    const items = groups.get(key);
    if (items) items.push({edge, data, points});
    else groups.set(key, [{edge, data, points}]);
  });

  groups.forEach(items => {
    if (items.length < 2) return;
    const handle = items[0]!.edge.targetHandle;
    const candidates = items.filter(item => item.points.length >= 3);
    if (!candidates.length) return;
    const trunkOf = (item: Item) => item.points[item.points.length - 2]!;
    let carrier: Item;
    if (handle === 'left-in') {
      carrier = candidates.reduce((best, item) =>
        trunkOf(item)[0] <= trunkOf(best)[0] ? item : best);
    } else if (handle === 'right-in') {
      carrier = candidates.reduce((best, item) =>
        trunkOf(item)[0] >= trunkOf(best)[0] ? item : best);
    } else {
      // 顶部入口：选进入段最长的一条，让它的竖线覆盖其他线的分叉点。
      const span = (item: Item) =>
        Math.abs(trunkOf(item)[1] - item.points[item.points.length - 1]![1]);
      carrier = candidates.reduce((best, item) => span(item) >= span(best) ? item : best);
    }
    const [cx, cy] = trunkOf(carrier);
    const [ex, ey] = carrier.points[carrier.points.length - 1]!;
    const covers = (point: PathPoint) => {
      if (handle === 'left-in' || handle === 'right-in') {
        return Math.abs(point[1] - cy) < 0.5
          && point[0] >= Math.min(cx, ex) - 0.5 && point[0] <= Math.max(cx, ex) + 0.5;
      }
      return Math.abs(point[0] - cx) < 0.5
        && point[1] >= Math.min(cy, ey) - 0.5 && point[1] <= Math.max(cy, ey) + 0.5;
    };
    items.forEach(item => {
      if (item === carrier) return;
      const junction = trunkOf(item);
      if (!covers(junction)) return;
      item.points.pop();
      const path = formatOrthogonalPath(item.points);
      if (!path) return;
      item.data.path = path;
      item.edge.markerEnd = undefined;
    });
  });
}

function buildGraph(payload: BlocksResponse, selectedId: number, onSelect: (id: number) => void,
  onEvent: (block: RBlock, target: EventTarget) => void, normalStyle: NormalStyleId) {
  const ctx: Ctx = {memo: new Map(), built: [], nodes: [], edges: [], plans: [],
    style: normalStyle, colors: themeEdges(normalStyle), onSelect, onEvent};
  const byId = new Map<number, RBlock>();
  const collect = (block: RBlock) => {
    byId.set(block.id, block);
    block.branches?.forEach(list => list.steps.forEach(collect));
    block.finally?.forEach(collect);
  };
  payload.config.blocks.forEach(collect);
  const topBlocks = payload.order.map(id => byId.get(id)).filter((b): b is RBlock => !!b);
  const widest = Math.max(...topBlocks.map(block => measure(block, false, ctx.memo).w), 0);
  const centerX = widest / 2;
  let y = 8;
  let pending: Anchor[] = [];
  topBlocks.forEach(block => {
    if (pending.length) mergeEdges(ctx, pending, block, y, centerX);
    const result = layoutBlock(block, centerX, y, [], false, ctx);
    pending = nextMode(block) === 'default' ? result.exits : [];
    y += result.height + TOP_GAP;
  });
  ctx.plans.forEach(plan => routeNext(ctx, plan));
  mergeSharedTrunks(ctx.edges);
  const selectedBlock = selectedId ? byId.get(selectedId) : undefined;
  const selectedKey = selectedBlock ? keyOf(selectedBlock) : '';
  let fanOrder = 0;
  ctx.edges.forEach(edge => {
    const data = edge.data as PathData;
    data.active = !!selectedKey && (edge.source === selectedKey || edge.target === selectedKey);
    // 选中分支点：扇出的每条条件线依次扫光；普通块的上下游只做呼吸。
    if (selectedBlock?.type === 'branch' && edge.source === selectedKey) {
      data.active = true;
      data.fan = true;
      data.fanDelay = fanOrder * 70;
      fanOrder += 1;
    }
  });
  ctx.nodes.forEach(node => { node.data.selected = node.data.block.id === selectedId; });
  return {nodes: ctx.nodes, edges: ctx.edges, byId};
}

function BlockNodeView({data}: NodeProps<BlockNode>) {
  const {block} = data;
  if (block.type === 'branch') {
    const count = block.branches?.length || 0;
    const tone = branchTone(block);
    const BranchIcon = tone === 'try' ? ShieldAlert : tone === 'multi' ? GitFork : GitBranch;
    const label = block.kind === 'try' ? `TRY · ${count} 路`
      : `${block.select === 'single' ? '单选' : '并行'} · ${count}`;
    const semantic = block.on ? 'entry' : block.flow ? 'flow'
      : block.jump ? 'jump' : null;
    return <section className={`branch-node tone-${tone} style-${data.style} ${isNeonStyle(data.style) ? 'neon' : ''} ${semantic ? 'has-semantic' : ''} ${data.selected ? 'selected' : ''}`}
        data-surface={themeSurface(data.style)}>
      <Handle type="target" position={Position.Top} id="top-in" />
      <Handle type="target" position={Position.Top} id="top-in-side" style={{left: '32%'}} />
      <Handle type="source" position={Position.Bottom} id="fan-out" />
      <Handle type="target" position={Position.Left} id="left-in" />
      <Handle type="source" position={Position.Left} id="left-out" />
      <Handle type="target" position={Position.Right} id="right-in" />
      <Handle type="source" position={Position.Right} id="right-out" />
      <span className="branch-id">ID: {String(block.id).padStart(3, '0')}</span>
      <span className={`select-chip ${block.kind === 'try' ? 'try' : block.select}`}>{label}</span>
      <button className="branch-node-button" aria-pressed={data.selected}
          aria-label={`查看分支块：${block.name}`}
          title={`${block.name}\n${block.description}`}
          onClick={event => {event.stopPropagation(); data.onSelect(block.id);}}>
        <span className="branch-icon"><BranchIcon size={18} /></span>
        <span className="branch-copy"><b>{block.name}</b><small>{block.description}</small></span>
      </button>
      {semantic && <span className={`branch-semantic ${semantic}`}
          title={semantic === 'entry' ? `事件入口：${block.on}`
            : semantic === 'flow' ? flowTitle(block) : jumpTitle(block)}>
        {semantic === 'entry' ? <Zap size={11} />
          : semantic === 'flow' ? <ArrowRight size={11} /> : <Link2 size={11} />}
      </span>}
    </section>;
  }
  const role = semanticRole(block);
  const RoleIcon = role === 'end' ? Square
    : role === 'flow' ? ArrowRight
      : role === 'jump' ? Link2 : Zap;
  return <article className={`block-card style-${data.style} ${isNeonStyle(data.style) ? 'neon' : ''} ${role ? `semantic-${role} has-role` : ''} ${data.selected ? 'selected' : ''}`}
      title={`${block.name}\n${block.description}`}>
    <Handle type="target" position={Position.Top} id="top-in" />
    <Handle type="target" position={Position.Top} id="top-in-side" style={{left: '32%'}} />
    <Handle type="source" position={Position.Bottom} id="bottom-out" />
    <Handle type="target" position={Position.Left} id="left-in" />
    <Handle type="source" position={Position.Left} id="left-out" />
    <Handle type="target" position={Position.Right} id="right-in" />
    <Handle type="source" position={Position.Right} id="right-out" />
    <button className="block-card-button" aria-pressed={data.selected}
        aria-label={`查看块：${block.name}`}
        onClick={event => {event.stopPropagation(); data.onSelect(block.id);}}>
      <NormalCardFace sample={block} style={data.style} semantic={role || undefined} />
    </button>
    {role && <span className={`block-role-chip ${role}`} title={semanticTitle(block, role)}>
      <RoleIcon size={9} />{SEMANTIC_LABEL[role]}
    </span>}
  </article>;
}

const blockNodeTypes = {block: BlockNodeView};

function PathEdge({id, markerEnd, style, data}: EdgeProps) {
  const route = data as PathData | undefined;
  if (!route?.path) return null;
  const tone = route.tone || 'default';
  const color = String(style?.stroke || '#7fa8c9');
  const motionStyle = {
    '--edge-color': color,
    '--pulse-delay': `${route.fanDelay ?? 0}ms`,
  } as CSSProperties;
  const motionClass = `edge-motion ${route.active ? 'is-active' : ''} ${route.fan ? 'is-fan' : ''}`;
  return <>
    {route.active && <path className={`edge-glow ${route.fan ? 'is-fan' : ''}`}
        d={route.path} strokeWidth={7} strokeLinecap="round" fill="none" style={motionStyle} />}
    <BaseEdge id={id} path={route.path} markerEnd={markerEnd}
      style={route.dashed && style ? {...style, strokeDasharray: '5 4'} : style} />
    <path className={`${motionClass} edge-motion-tail`} d={route.path} pathLength={1}
      strokeWidth={4.2} strokeLinecap="round" fill="none"
      strokeDasharray="0.07 0.93" style={motionStyle} />
    <path className={`${motionClass} edge-motion-core`} d={route.path} pathLength={1}
      strokeWidth={1.5} strokeLinecap="round" fill="none"
      strokeDasharray="0.016 0.984" style={motionStyle} />
    {route.label && route.labelX !== undefined && route.labelY !== undefined &&
      <EdgeLabelRenderer>
        <div className={`edge-label-chip tone-${tone} ${route.fan ? 'is-fan' : ''}`}
            style={{
              transform: `translate(-50%, -50%) translate(${route.labelX}px, ${route.labelY}px)`,
              '--pulse-delay': `${route.fanDelay ?? 0}ms`,
            } as CSSProperties}>
          {route.label}
        </div>
      </EdgeLabelRenderer>}
  </>;
}

const blockEdgeTypes = {path: PathEdge};

type JumpRequest = {id: number; view: string; token: number};
type EditorDialog =
  | {kind: 'block'; mode: 'create'; afterId?: number}
  | {kind: 'block'; mode: 'edit'; blockId: number}
  | {kind: 'new-view'}
  | {kind: 'view-settings'}
  | {kind: 'view-json'}
  | {kind: 'project-settings'}
  | {kind: 'workspace'; browse?: boolean; tab?: 'open' | 'new'}
  | {kind: 'delete-block'; blockId: number}
  | {kind: 'delete-container'; containerId: string}
  | {kind: 'delete-view'};

function BlockFlow({payload, selectedId, onSelect, onFlow, onJump, onEvent, focusRequest, onJumpError, onJumpDone, normalStyle}: {
  payload: BlocksResponse;
  selectedId: number;
  normalStyle: NormalStyleId;
  onSelect: (id: number) => void;
  onFlow: (block: RBlock) => void;
  onJump: (block: RBlock) => void;
  onEvent: (block: RBlock, target: EventTarget) => void;
  focusRequest: JumpRequest | null;
  onJumpError: (id: number) => void;
  onJumpDone: () => void;
}) {
  const flow = useReactFlow();
  const frameRef = useRef<HTMLDivElement>(null);
  const fitViewRef = useRef(flow.fitView);
  fitViewRef.current = flow.fitView;
  const [zoom, setZoom] = useState(1);
  const graph = useMemo(() => buildGraph(payload, selectedId, onSelect, onEvent, normalStyle),
    [payload, selectedId, onSelect, onEvent, normalStyle]);
  const signature = graph.nodes.map(node => `${node.id}:${node.position.x}:${node.position.y}`).join('|');
  const focusNodeId = focusRequest ? `b${focusRequest.id}` : '';
  const focusReady = !!focusRequest && payload.view?.view_id === focusRequest.view;
  const hasFocusNode = focusReady && graph.nodes.some(node => node.id === focusNodeId);
  const focusActive = useRef(false);
  focusActive.current = !!focusRequest;
  // 自动 fitView 会重试到节点尺寸就绪；用户一旦缩放/拖动/点块，
  // 就立即停止后续重试，避免把用户刚调好的视口又拉回去。
  const autoFitCancelled = useRef(false);
  const cancelAutoFit = useCallback(() => { autoFitCancelled.current = true; }, []);
  const hasTry = graph.nodes.some(node => (node.data as BlockNodeData).block.kind === 'try');
  const viewKey = payload.view?.view_id || payload.config.view.id;
  const [entering, setEntering] = useState(false);
  useEffect(() => {
    setEntering(true);
    const timer = window.setTimeout(() => setEntering(false), 1000);
    return () => window.clearTimeout(timer);
  }, [viewKey]);

  useEffect(() => {
    if (focusActive.current) return;
    autoFitCancelled.current = false;
    let cancelled = false;
    const timers: number[] = [];
    let attempts = 0;
    const fit = async () => {
      if (cancelled || focusActive.current || autoFitCancelled.current) return;
      // 先强制一次布局，让 React Flow 的 ResizeObserver 拿到节点尺寸。
      frameRef.current?.getBoundingClientRect();
      const fitted = await fitViewRef.current({padding: .14, minZoom: .24, maxZoom: 1.1, duration: 0});
      attempts += 1;
      // 只有节点还没测量好（返回 false）才重试；成功一次就停。
      if (!fitted && attempts < 8 && !autoFitCancelled.current) {
        timers.push(window.setTimeout(() => void fit(), 200));
      }
    };
    timers.push(window.setTimeout(() => void fit(), 0));
    return () => { cancelled = true; timers.forEach(clearTimeout); };
  }, [signature]);

  useEffect(() => {
    if (!focusRequest || !focusReady) return;
    if (!hasFocusNode) {
      onJumpError(focusRequest.id);
      return;
    }
    let cancelled = false;
    let timer = 0;
    const focus = async (attempt: number) => {
      const ok = await flow.fitView({
        nodes: [{id: focusNodeId}], padding: .6, minZoom: .4, maxZoom: 1.15, duration: 280,
      });
      if (cancelled) return;
      if (!ok && attempt < 6) {
        timer = window.setTimeout(() => void focus(attempt + 1), 60);
        return;
      }
      onSelect(focusRequest.id);
      onJumpDone();
    };
    const frame = requestAnimationFrame(() => void focus(0));
    return () => { cancelled = true; cancelAnimationFrame(frame); clearTimeout(timer); };
  }, [flow.fitView, focusNodeId, focusReady, focusRequest, hasFocusNode,
      onJumpDone, onJumpError, onSelect]);

  return <div className={`diagram-frame ${entering ? 'entering' : ''}`}
      aria-label="块流程画布" ref={frameRef}
      onPointerDownCapture={cancelAutoFit} onWheelCapture={cancelAutoFit}>
    <ReactFlow nodes={graph.nodes} edges={graph.edges} nodeTypes={blockNodeTypes} edgeTypes={blockEdgeTypes}
      fitView fitViewOptions={{padding: .17, minZoom: .22, maxZoom: 1.1}}
      nodesDraggable={false} nodesConnectable={false} nodesFocusable={false} edgesFocusable={false}
      elementsSelectable zoomOnDoubleClick={false} deleteKeyCode={null} minZoom={.14} maxZoom={1.5}
      onNodeDoubleClick={(_, node) => {
        const block = (node.data as BlockNodeData).block;
        if (block.flow) onFlow(block);
        else if (block.jump) onJump(block);
        else if (block.emit?.length) onEvent(block, block.emit[0]);
      }}
      onMove={(_, viewport) => setZoom(viewport.zoom)} proOptions={{hideAttribution: false}}>
      <Background variant={BackgroundVariant.Dots} gap={24} size={1}
        color={themeCanvasDot(normalStyle)} />
    </ReactFlow>
    <div className="diagram-tools" aria-label="流程图缩放">
      <button aria-label="缩小" onClick={() => void flow.zoomOut({duration: 140})}><ZoomOut size={15} /></button>
      <button aria-label="放大" onClick={() => void flow.zoomIn({duration: 140})}><ZoomIn size={15} /></button>
      <i />
      <button aria-label="适应窗口" onClick={() => void flow.fitView({padding: .17, minZoom: .22, maxZoom: 1.1, duration: 180})}><Maximize2 size={14} /></button>
    </div>
    <div className="diagram-caption"><span className="step-key">方块：普通块</span>
      <span className="branch-key">分支：单选 / 并行 / TRY</span>
      <span className="arrow-key">线条：随主题语义色</span>
      {hasTry && <span className="arrow-key">虚线：异常分支</span>}
      <small>{Math.round(zoom * 100)}%</small></div>
  </div>;
}

export function BlocksApp() {
  const [payload, setPayload] = useState<BlocksResponse>();
  const [index, setIndex] = useState<ViewsIndex>();
  const [initial] = useState(() => {
    const query = new URLSearchParams(window.location.search);
    const config = query.get('config') || '';
    const project = query.get('project') || (config ? '' : query.get('path') || '');
    return {config, project, view: query.get('view') || ''};
  });
  const [viewId, setViewId] = useState(initial.view);
  const [workspacePath, setWorkspacePath] = useState(initial.config || initial.project);
  const [configMode, setConfigMode] = useState(!!initial.config);
  const [homeMode, setHomeMode] = useState(!initial.config && !initial.project && !initial.view);
  const [editing, setEditing] = useState(false);
  const [normalStyle, setNormalStyle] = useState<NormalStyleId>(() => {
    try {
      const saved = window.localStorage.getItem(NORMAL_STYLE_KEY);
      return isNormalStyleId(saved) ? saved : DEFAULT_NORMAL_STYLE;
    } catch {
      return DEFAULT_NORMAL_STYLE;
    }
  });
  const [motion, setMotion] = useState<MotionMode>(() => {
    try {
      const saved = window.localStorage.getItem(MOTION_KEY);
      return isMotionMode(saved) ? saved : DEFAULT_MOTION;
    } catch {
      return DEFAULT_MOTION;
    }
  });
  const [styleGallery, setStyleGallery] = useState(false);
  const [dialog, setDialog] = useState<EditorDialog | null>(null);
  const [saving, setSaving] = useState(false);
  const [editError, setEditError] = useState('');
  const [notice, setNotice] = useState('');
  const [indexError, setIndexError] = useState('');
  const [payloadError, setPayloadError] = useState('');
  const [indexLoading, setIndexLoading] = useState(true);
  const [payloadLoading, setPayloadLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  const [selectedId, setSelectedId] = useState(0);
  const [jumpTarget, setJumpTarget] = useState<JumpRequest | null>(null);
  const [jumpHistory, setJumpHistory] = useState<{view: string; id: number}[]>([]);
  const [jumpError, setJumpError] = useState('');
  const jumpSeq = useRef(0);
  const noticeTimer = useRef<number | undefined>(undefined);
  const loadedView = useRef('');

  const showNotice = useCallback((text: string) => {
    setNotice(text);
    window.clearTimeout(noticeTimer.current);
    noticeTimer.current = window.setTimeout(() => setNotice(''), 2800);
  }, []);
  useEffect(() => () => window.clearTimeout(noticeTimer.current), []);
  useEffect(() => {
    try { window.localStorage.setItem(NORMAL_STYLE_KEY, normalStyle); } catch { /* 本地预览偏好，失败不影响阅读 */ }
  }, [normalStyle]);
  const applyNormalStyle = useCallback((style: NormalStyleId) => {
    setNormalStyle(style);
    setStyleGallery(false);
    showNotice(`整图样式：${normalStyleName(style)}`);
  }, [showNotice]);
  const cycleMotion = useCallback(() => {
    const next: MotionMode = motion === 'off' ? 'subtle' : motion === 'subtle' ? 'flow' : 'off';
    setMotion(next);
    showNotice(`动画：${MOTION_LABEL[next]}`);
  }, [motion, showNotice]);
  useEffect(() => {
    try { window.localStorage.setItem(MOTION_KEY, motion); } catch { /* 本地偏好，失败不影响阅读 */ }
  }, [motion]);

  useEffect(() => {
    if (homeMode) {
      setIndexLoading(false);
      setIndexError('');
      return;
    }
    const controller = new AbortController();
    setIndexLoading(true); setIndexError('');
    const endpoint = '/api/views' + (workspacePath ? '?path=' + encodeURIComponent(workspacePath) : '');
    fetch(endpoint, {signal: controller.signal}).then(async response => {
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '无法读取视图列表');
      return data as ViewsIndex;
    }).then(data => {
      setIndex(data);
      setIndexLoading(false);
    }).catch(reason => {
      if (controller.signal.aborted) return;
      setIndexError(reason instanceof Error ? reason.message : String(reason));
      setIndexLoading(false);
    });
    return () => controller.abort();
  }, [workspacePath, revision, homeMode]);

  const views = index?.views || [];
  const effectiveView = index
    ? (viewId && views.some(view => view.view_id === viewId) ? viewId : index.entry)
    : '';
  const [closedGroups, setClosedGroups] = useState<Set<ViewGroupKey>>(
    () => new Set(['function', 'details']));
  const currentViewKind = views.find(view => view.view_id === effectiveView)?.kind;
  const isContractView = currentViewKind === 'contract'
    || payload?.config.view.kind === 'contract';
  const currentGroup = VIEW_GROUPS.find(group =>
    currentViewKind && group.kinds.includes(currentViewKind))?.key;
  const viewGroups = VIEW_GROUPS.map(group => ({
    ...group,
    items: views.filter(view => group.kinds.includes(view.kind)),
  })).filter(group => group.items.length);
  const toggleGroup = (key: ViewGroupKey) => {
    setClosedGroups(previous => {
      const next = new Set(previous);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  useEffect(() => {
    if (!index || !effectiveView) return;
    const controller = new AbortController();
    setPayloadLoading(true); setPayloadError('');
    const endpoint = '/api/blocks-config?path=' + encodeURIComponent(index.source.path || '')
      + '&view=' + encodeURIComponent(effectiveView);
    fetch(endpoint, {signal: controller.signal}).then(async response => {
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '无法读取视图');
      return data as BlocksResponse;
    }).then(data => {
      setPayload(data);
      const changedView = loadedView.current !== effectiveView;
      loadedView.current = effectiveView;
      setSelectedId(previous => !changedView && hasBlock(data.config.blocks, previous)
        ? previous : (data.order[0] || 0));
      setJumpError('');
      setPayloadLoading(false);
    }).catch(reason => {
      if (controller.signal.aborted) return;
      setPayloadError(reason instanceof Error ? reason.message : String(reason));
      setPayloadLoading(false);
    });
    return () => controller.abort();
  }, [index, effectiveView]);

  useEffect(() => {
    if (!index || !effectiveView || configMode) return;
    const url = new URL(window.location.href);
    url.searchParams.set('view', effectiveView);
    if (workspacePath) url.searchParams.set('project', workspacePath);
    else url.searchParams.delete('project');
    url.searchParams.delete('path');
    url.searchParams.delete('config');
    window.history.replaceState(null, '', url);
  }, [index, effectiveView, configMode, workspacePath]);

  const byId = useMemo(() => {
    const map = new Map<number, RBlock>();
    const collect = (block: RBlock) => {
      map.set(block.id, block);
      block.branches?.forEach(list => list.steps.forEach(collect));
      block.finally?.forEach(collect);
    };
    (payload?.config.blocks || []).forEach(collect);
    return map;
  }, [payload]);
  const selected = selectedId ? byId.get(selectedId) : undefined;
  const selectedContract = selected?.contract;
  const selectedCode = selected?.code_mapping ? payload?.codes[String(selected.id)] : undefined;
  const styleSamples = useMemo<StyleSample[]>(() => {
    const normals: RBlock[] = [];
    const visit = (block: RBlock) => {
      if (block.type === 'normal') normals.push(block);
      block.branches?.forEach(list => list.steps.forEach(visit));
      block.finally?.forEach(visit);
    };
    (payload?.config.blocks || []).forEach(visit);
    const primary = selected?.type === 'normal' ? selected : normals[0];
    const secondary = normals.find(block => block.id !== primary?.id);
    return [primary, secondary]
      .filter((block): block is RBlock => !!block)
      .map(block => ({id: block.id, name: block.name, description: block.description}));
  }, [payload, selected]);
  const select = useCallback((id: number) => setSelectedId(id), []);
  const hasFlow = useMemo(() => [...byId.values()].some(block => block.flow), [byId]);
  const hasJump = useMemo(() => [...byId.values()].some(block => block.jump), [byId]);
  const hasEvent = useMemo(() => [...byId.values()].some(block => block.on || block.emit?.length), [byId]);
  const navigateTo = useCallback((view: string, id: number, sourceId: number) => {
    if (!views.some(item => item.view_id === view)) {
      setJumpError(`跳转视图不存在：${view}`);
      return;
    }
    setJumpHistory(history => [...history, {view: effectiveView, id: sourceId}]);
    setJumpError('');
    setJumpTarget({id, view, token: ++jumpSeq.current});
    if (view !== effectiveView) setViewId(view);
  }, [effectiveView, views]);
  const handleFlow = useCallback((block: RBlock) => {
    const flow = block.flow;
    if (!flow || !flow.view) return;
    navigateTo(flow.view, flow.id, block.id);
  }, [navigateTo]);
  const handleJump = useCallback((block: RBlock) => {
    const jump = block.jump;
    if (!jump) return;
    navigateTo(jump.view || effectiveView, jump.id, block.id);
  }, [effectiveView, navigateTo]);
  const handleEvent = useCallback((block: RBlock, target: EventTarget) => {
    navigateTo(target.view || effectiveView, target.id, block.id);
  }, [effectiveView, navigateTo]);
  const goBack = useCallback(() => {
    const last = jumpHistory[jumpHistory.length - 1];
    if (!last) return;
    setJumpHistory(jumpHistory.slice(0, -1));
    if (!views.some(view => view.view_id === last.view)) {
      setJumpError(`返回目标视图不存在：${last.view}`);
      return;
    }
    setJumpError('');
    setJumpTarget({id: last.id, view: last.view, token: ++jumpSeq.current});
    if (last.view !== effectiveView) setViewId(last.view);
  }, [effectiveView, jumpHistory, views]);
  const handleJumpError = useCallback((id: number) => {
    setJumpTarget(null);
    setJumpError(`跳转目标编号 ${id} 不存在`);
  }, []);
  const handleJumpDone = useCallback(() => setJumpTarget(null), []);
  const refresh = useCallback(() => {
    setJumpTarget(null);
    setJumpError('');
    setEditError('');
    setRevision(value => value + 1);
  }, []);
  const canEdit = payload?.source.kind === 'project' && !configMode;
  const activeEditing = editing && canEdit;
  const selectedIsTop = !!selected && !!payload?.order.includes(selected.id);
  const selectedTopIndex = selected && payload ? payload.order.indexOf(selected.id) : -1;
  const firstHasOn = !!payload?.config.blocks[0]?.on;
  const canMoveUp = selectedIsTop && selectedTopIndex > 0
    && !(selectedTopIndex === 1 && firstHasOn);
  const canMoveDown = selectedIsTop && selectedTopIndex >= 0
    && selectedTopIndex < (payload?.order.length || 0) - 1
    && !(selectedTopIndex === 0 && firstHasOn);

  const applyView = useCallback(async (config: ViewConfig, focusId?: number) => {
    if (!index || index.source.kind !== 'project' || !index.source.path) {
      throw new Error('当前不是可编辑工作区');
    }
    if (saving) throw new Error('正在保存，请稍候');
    setSaving(true);
    try {
      const revision = index.views.find(view => view.view_id === config.view.id)?.revision;
      const result = await saveView(index.source.path, config, revision);
      setIndex(result.index);
      setPayload(result.payload);
      setViewId(result.payload.view?.view_id || result.payload.config.view.id);
      if (focusId !== undefined && hasBlock(result.payload.config.blocks, focusId)) {
        setSelectedId(focusId);
      } else {
        setSelectedId(previous => hasBlock(result.payload.config.blocks, previous)
          ? previous : (result.payload.order[0] || 0));
      }
      setEditError('');
      showNotice(result.warnings.length ? `已保存 · ${result.warnings.length} 条警告` : '已保存');
    } finally {
      setSaving(false);
    }
  }, [index, saving, showNotice]);

  const applyFlatMutation = useCallback(async (
    action: string, data: Record<string, unknown> = {}) => {
    if (!index || index.source.kind !== 'project' || !index.source.path || !payload) {
      throw new Error('当前不是可编辑工作区');
    }
    if (saving) throw new Error('正在保存，请稍候');
    setSaving(true);
    try {
      const result = await mutateView(index.source.path, effectiveView,
        action, data, payload.revision);
      setIndex(result.index);
      setPayload(result.payload);
      const newId = result.result.block_id;
      if (newId !== undefined
          && hasBlock(result.payload.config.blocks, newId)) {
        setSelectedId(newId);
      } else {
        setSelectedId(previous => hasBlock(result.payload.config.blocks, previous)
          ? previous : (result.payload.order[0] || 0));
      }
      setEditError('');
      showNotice(result.warnings.length
        ? `已更新 · ${result.warnings.length} 条警告` : '已更新块结构');
      return result;
    } finally {
      setSaving(false);
    }
  }, [effectiveView, index, payload, saving, showNotice]);

  const runFlatAction = useCallback(async (
    action: string, data: Record<string, unknown> = {}) => {
    try {
      await applyFlatMutation(action, data);
    } catch (reason) {
      setEditError(reason instanceof Error ? reason.message : String(reason));
    }
  }, [applyFlatMutation]);

  const selectedFlatContainer = useMemo(() => {
    if (!payload?.flat || !selectedId) return 'root';
    return payload.flat.containers.find(container =>
      container.blocks.includes(selectedId))?.id || 'root';
  }, [payload, selectedId]);

  const addFlatBlock = useCallback((containerId = selectedFlatContainer,
    afterId: number | undefined = selectedId || undefined) => {
    void runFlatAction('add_block', {container: containerId, after_id: afterId});
  }, [runFlatAction, selectedFlatContainer, selectedId]);

  const addFlatBranchBlock = useCallback(() => {
    void runFlatAction('add_branch_block', {
      container: selectedFlatContainer,
      after_id: selectedId || undefined,
      kind: 'single',
    });
  }, [runFlatAction, selectedFlatContainer, selectedId]);

  const addFlatTryBlock = useCallback(() => {
    void runFlatAction('add_branch_block', {
      container: selectedFlatContainer,
      after_id: selectedId || undefined,
      kind: 'try',
    });
  }, [runFlatAction, selectedFlatContainer, selectedId]);

  const addFlatBranch = useCallback((blockId: number) => {
    const block = payload?.flat?.blocks.find(item => item.id === blockId);
    void runFlatAction('add_branch', {
      block_id: blockId,
      role: block?.kind === 'try' ? 'except' : undefined,
    });
  }, [payload, runFlatAction]);

  const addFlatFinally = useCallback((blockId: number) => {
    void runFlatAction('add_finally', {block_id: blockId});
  }, [runFlatAction]);

  const deleteFlatContainer = useCallback((containerId: string) => {
    void runFlatAction('delete_container', {container_id: containerId});
  }, [runFlatAction]);

  const updateFlatCondition = useCallback((containerId: string,
    condition: string | null) => {
    void runFlatAction('update_container', {container_id: containerId, condition});
  }, [runFlatAction]);

  const applyProjectSettings = useCallback((result: SaveProjectResponse) => {
    // 改入口视图不应该把正在看的视图切走。
    if (payload?.config.view.id) setViewId(payload.config.view.id);
    setIndex(result.index);
    setPayload(previous => previous ? {
      ...previous,
      manifest_revision: result.manifest_revision ?? previous.manifest_revision,
      project: {
        name: result.manifest.project.name,
        description: result.manifest.project.description,
        root: result.manifest.project.root,
        files: result.manifest.files,
      },
    } : previous);
    showNotice('项目设置已保存');
  }, [payload, showNotice]);

  const handleDeleteView = useCallback(async () => {
    if (!index?.source.path || !effectiveView) throw new Error('没有可删除的视图');
    const revision = payload?.view?.view_id === effectiveView
      ? payload.revision
      : index.views.find(view => view.view_id === effectiveView)?.revision;
    const result = await deleteView(index.source.path, effectiveView,
      revision, index.manifest_revision);
    setIndex(result.index);
    setPayload(undefined);
    setPayloadLoading(true);
    setViewId(result.index.entry);
    setSelectedId(0);
    loadedView.current = '';
    setJumpHistory([]);
    setJumpTarget(null);
    setJumpError('');
    setEditError('');
    showNotice('视图已删除');
  }, [index, effectiveView, showNotice]);

  const handleDeleteBlock = useCallback(async (blockId: number) => {
    if (!payload) throw new Error('没有可编辑的视图');
    if (payload.flat && activeEditing) {
      await applyFlatMutation('delete_block', {block_id: blockId, cascade: true});
      return;
    }
    await applyView({...payload.config, blocks: removeBlock(payload.config.blocks, blockId)});
  }, [payload, activeEditing, applyFlatMutation, applyView]);

  const moveBlock = useCallback(async (blockId: number, delta: number) => {
    if (!payload) return;
    const blocks = [...payload.config.blocks];
    const at = blocks.findIndex(block => block.id === blockId);
    const target = at + delta;
    if (at < 0 || target < 0 || target >= blocks.length) return;
    [blocks[at], blocks[target]] = [blocks[target]!, blocks[at]!];
    setEditError('');
    try {
      await applyView({...payload.config, blocks}, blockId);
    } catch (reason) {
      setEditError(reason instanceof Error ? reason.message : String(reason));
    }
  }, [payload, applyView]);

  const openWorkspace = useCallback((path: string) => {
    setWorkspacePath(path);
    setHomeMode(false);
    setConfigMode(false);
    setIndex(undefined);
    setPayload(undefined);
    setIndexLoading(true);
    setPayloadLoading(true);
    setViewId('');
    setSelectedId(0);
    setJumpHistory([]);
    setJumpTarget(null);
    setJumpError('');
    setEditError('');
    setEditing(false);
    loadedView.current = '';
    setDialog(null);
    setRevision(value => value + 1);
  }, []);

  const openFromHome = useCallback(async (path: string) => {
    const result = await openWorkspaceApi(path);
    openWorkspace(result.index.source.path || path);
  }, [openWorkspace]);

  const sourceKind = payload?.source.kind === 'file' ? '本地配置'
    : payload?.source.kind === 'project' ? '项目视图' : '默认示例';
  const booting = !payload && (indexLoading || payloadLoading);
  const fatalError = !payload ? (indexError || payloadError) : '';
  const bannerError = editError || payloadError || jumpError || (payload ? indexError : '');
  const viewLabel = (viewId?: string) =>
    views.find(item => item.view_id === viewId)?.name || viewId || '';
  const projectTitle = index?.project?.name || payload?.project?.name || payload?.config.view.name || '基础块';
  const projectDescription = index?.project?.description || payload?.project?.description || '';
  const editingBlock = dialog?.kind === 'block' && dialog.mode === 'edit'
    ? byId.get(dialog.blockId) : undefined;
  const deletingBlock = dialog?.kind === 'delete-block' ? byId.get(dialog.blockId) : undefined;
  const deletingContainer = dialog?.kind === 'delete-container'
    ? payload?.flat?.containers.find(item => item.id === dialog.containerId)
    : undefined;

  if (homeMode) {
    return <div className="reader-app" data-theme={normalStyle}
        data-surface={themeSurface(normalStyle)} data-motion={motion}
        style={themeVars(normalStyle) as CSSProperties}>
      <HomeScreen onOpen={openFromHome}
        onBrowse={() => setDialog({kind: 'workspace', browse: true})}
        onNew={() => setDialog({kind: 'workspace', tab: 'new'})} />
      {dialog?.kind === 'workspace' && <WorkspaceDialog currentPath={workspacePath}
        initialBrowse={dialog.browse} initialTab={dialog.tab}
        onOpen={openWorkspace} onClose={() => setDialog(null)} />}
    </div>;
  }

  return <div className="reader-app" data-theme={normalStyle}
      data-surface={themeSurface(normalStyle)} data-motion={motion}
      style={themeVars(normalStyle) as CSSProperties}>
    <header className="reader-topbar">
      <a className="reader-brand" href="/" title="返回工作区首页"
          aria-label="Codifold 中文流程阅读器，返回工作区首页">
        <Layers3 size={23} /><b>Codifold</b></a>
      <span className="reader-product-label">BASE BLOCKS</span>
      <span className="topbar-divider" />
      <span className="project-name"><Boxes size={14} />{projectTitle}</span>
      <span className="topbar-spacer" />
      <span className="reader-status"><i />{saving ? '保存中…'
        : indexLoading || payloadLoading ? '读取中…' : '本地运行'}</span>
      {notice && <span className="editor-notice" role="status">{notice}</span>}
      <nav aria-label="项目操作">
        <button aria-label="预览整图样式" onClick={() => setStyleGallery(true)}
            title="预览并切换整图外观（块、分支、标签、连线）">
          <Palette size={15} /><span>样式</span>
        </button>
        <button aria-label="打开或新建工作区" onClick={() => setDialog({kind: 'workspace'})}>
          <FolderOpen size={15} /><span>工作区</span>
        </button>
        <button aria-label={activeEditing ? '退出编辑模式' : '进入编辑模式'}
            aria-pressed={activeEditing}
            onClick={() => setEditing(value => !value)} disabled={!canEdit}
            title={canEdit ? (activeEditing ? '退出编辑模式' : '编辑块和视图')
              : '单文件配置只读；请打开一个工作区'}>
          {activeEditing ? <Eye size={15} /> : <Pencil size={15} />}
          <span>{activeEditing ? '浏览' : '编辑'}</span>
        </button>
        <button aria-label="返回上一个跳转位置" onClick={goBack} disabled={!jumpHistory.length}
            title={jumpHistory.length
              ? `返回 ${jumpHistory[jumpHistory.length - 1].view} · 编号 ${jumpHistory[jumpHistory.length - 1].id}`
              : '没有可返回的跳转'}>
          <ArrowLeft size={15} /><span>返回</span>
        </button>
        <button aria-label="刷新基础块" onClick={refresh}
            disabled={indexLoading || payloadLoading || saving}>
          <RefreshCw size={15} className={indexLoading || payloadLoading || saving ? 'spin' : ''} /><span>刷新</span>
        </button>
        <button aria-label={`动画模式：${MOTION_LABEL[motion]}，点击切换`}
            onClick={cycleMotion}
            title="切换动画强度：关 / 轻 / 流动">
          <Sparkles size={15} /><span>动画 · {MOTION_LABEL[motion]}</span>
        </button>
      </nav>
    </header>
    {booting ? <main className="reader-message" aria-live="polite"><RefreshCw className="spin" size={24} /><h1>正在读取视图…</h1></main>
      : fatalError ? <main className="reader-message" role="alert"><h1>暂时无法打开视图</h1><p>{fatalError}</p>
          <div className="message-actions"><button className="subtle-button" onClick={refresh}>重试</button></div></main>
      : payload && <main className="reader-workspace">
      <aside className="flow-sidebar" aria-label="块列表">
        <div className="sidebar-project">
          <span className="sidebar-project-icon"><Boxes size={16} /></span>
          <div><b>{projectTitle}</b><small title={projectDescription || undefined}>
            {projectDescription || `统一块结构 · ${payload.order.length} 个顶层块`}
          </small></div>
          {activeEditing && <button type="button" className="sidebar-project-settings"
              title="项目设置" aria-label="项目设置"
              onClick={() => setDialog({kind: 'project-settings'})}>
            <Settings2 size={13} />
          </button>}
        </div>
        {(views.length > 1 || activeEditing) && <div className="view-switcher" aria-label="视图列表">
          <div className="flow-list-head"><span>视图</span>
            {activeEditing
              ? <span className="view-head-actions">
                  <button type="button" className="primary" onClick={() => setDialog({kind: 'new-view'})}>
                    <Plus size={11} />新建
                  </button>
                  <button type="button" onClick={() => setDialog({kind: 'view-settings'})}>
                    <Settings2 size={11} />设置
                  </button>
                </span>
              : <small>{views.length}</small>}
          </div>
          <div className="view-groups">
            {viewGroups.map(group => {
              const open = !closedGroups.has(group.key) || currentGroup === group.key;
              return <section className={`view-group ${open ? '' : 'collapsed'}`}
                  key={group.key}>
                <button type="button" className="view-group-head"
                    aria-expanded={open} onClick={() => toggleGroup(group.key)}>
                  {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                  <span>{group.label}</span>
                  <small>{group.items.length}</small>
                </button>
                <div className="view-group-body">
                  {group.items.map(view => <button key={view.view_id}
                      className={`view-row ${view.view_id === effectiveView ? 'active' : ''}`}
                      aria-pressed={view.view_id === effectiveView}
                      title={`${view.name}\n${view.description}\n${view.file}`}
                      onClick={() => {
                        setJumpTarget(null); setJumpError(''); setEditError('');
                        setViewId(view.view_id);
                      }}>
                    <span className="view-mark" />
                    <span className="view-copy"><b>{view.name}</b>
                      <small>{view.description}</small></span>
                    {view.entry && <span className="view-entry-badge">默认</span>}
                  </button>)}
                </div>
              </section>;
            })}
          </div>
        </div>}
        {payload.flat ? (
          isContractView ? <>
            <div className="flow-list-head"><span>契约条目</span>
              <small>{payload.flat.blocks.length} 条 · 视图 JSON 编辑</small>
            </div>
            <div className="flow-case-list">
              {payload.order.map(id => {
                const block = byId.get(id);
                if (!block) return null;
                return <button key={id} className={`flow-case-row ${selectedId === id ? 'active' : ''}`}
                    aria-pressed={selectedId === id} onClick={() => setSelectedId(id)}>
                  <span className="flow-row-icon block-list-ordinal">{id}</span>
                  <span className="flow-row-copy"><b>{block.name}</b>
                    <small>{contractSummary(block) || '契约条目'}</small></span>
                </button>;
              })}
            </div>
          </> : <>
            <div className="flow-list-head"><span>块结构</span>
              <small>{payload.flat.blocks.length} 块 · {payload.flat.containers.length} 容器</small>
            </div>
            <FlatBlockTree flat={payload.flat} selectedId={selectedId}
              editable={activeEditing}
              onSelect={select}
              onAddStep={containerId => addFlatBlock(containerId, undefined)}
              onAddBranch={addFlatBranch}
              onAddFinally={addFlatFinally}
              onDeleteBlock={blockId => setDialog({kind: 'delete-block', blockId})}
              onDeleteContainer={containerId => setDialog({kind: 'delete-container', containerId})}
              onUpdateCondition={updateFlatCondition} />
          </>
        ) : <>
          <div className="flow-list-head"><span>{isContractView ? '契约条目' : '顶层块（顺序）'}</span>
            {activeEditing && !isContractView
              ? <button type="button" className="add-block-button"
                  onClick={() => setDialog({kind: 'block', mode: 'create',
                    afterId: selectedIsTop ? selectedId : undefined})}>
                  <Plus size={11} />添加块
                </button>
              : <small>{isContractView ? '视图 JSON 编辑' : '编号'}</small>}
          </div>
          <div className="flow-case-list">
            {payload.order.map(id => {
              const block = byId.get(id);
              if (!block) return null;
              const mode = nextMode(block);
              const summary = contractSummary(block);
              return <button key={id} className={`flow-case-row ${selectedId === id ? 'active' : ''}`}
                  aria-pressed={selectedId === id} onClick={() => setSelectedId(id)}>
                <span className="flow-row-icon block-list-ordinal">{id}</span>
                <span className="flow-row-copy"><b>{block.name}</b>
                  <small>{summary ?? (block.type === 'branch'
                    ? block.kind === 'try' ? `try · ${block.branches!.length} 路`
                      : `分支 · ${block.select === 'single' ? '单选' : '并行'} · ${block.branches!.length} 条`
                    : mode === 'stop' ? '普通块 · 终止'
                      : mode === 'jump' ? `普通块 · next ${block.next}` : '普通块')}</small></span>
              </button>;
            })}
          </div>
        </>}
        <div className="sidebar-bottom"><i /><span>{sourceKind} · 基础块元素</span></div>
      </aside>
      <section className="flow-column" aria-label="块流程">
        <div className="flow-heading">
          <div className="flow-breadcrumb">
            <button>{projectTitle}</button>
            <span className="flow-breadcrumb-part">{payload.config.view.name}</span>
          </div>
          <div className="flow-title-row">
            <h1>{payload.config.view.name}</h1>
            <span className="flow-status-pill"><i />{isContractView ? '表格契约' : '顺序 + 线条分支'}</span>
          </div>
          <p>{payload.config.view.description}</p>
          <div className="interaction-tip">
            {isContractView ? <>
              <span>单击行 <b>查看详情</b></span>
              <span>来源 / 处理 <b>跳转到原块</b></span>
              <span>编辑用 <b>视图 JSON</b></span>
            </> : <>
              <span>默认 <b>从上到下</b></span><span>分支 <b>线条扇出</b></span>
              <span>列表尾 <b>线条汇合</b></span><span>next <b>线条回指</b></span>
              {hasEvent ? <span>双击 / 事件角标 <b>跳转</b></span>
                : hasFlow ? <span>双击 / 继续角标 <b>进入下一段</b></span>
                  : hasJump && <span>双击 <b>跳转</b></span>}
            </>}
            <span className="keyboard-tip">单击块 查看详情</span></div>
        </div>
        {bannerError && <div className="flow-error" role="alert">
          <span>{bannerError}</span>
          <button className="subtle-button" onClick={refresh}>重试</button>
        </div>}
        {isContractView
          ? <div className="contract-canvas">
              <ContractTables blocks={payload.config.blocks} selectedId={selectedId}
                onSelect={select} onNavigate={navigateTo} />
            </div>
          : <div className="flow-canvas">
              <BlockFlow payload={payload} selectedId={selectedId} onSelect={select}
                normalStyle={normalStyle}
                onFlow={handleFlow} onJump={handleJump} onEvent={handleEvent}
                focusRequest={jumpTarget}
                onJumpError={handleJumpError} onJumpDone={handleJumpDone} />
            </div>}
      </section>
      <aside className="source-column" aria-label="所选块的代码映射">
        <div className="source-scroll" key={selectedId}>
          {selected ? <>
            <div className="source-heading">
              <span className="eyebrow"><Code2 size={14} />{selectedContract
                ? selectedContract.kind === 'type' ? '契约 · 类型' : '契约 · 接口'
                : selected.type === 'branch' ? '条件分支块' : '普通块'}</span>
              <h2>{selected.name}</h2>
              <p>{selected.description}</p>
            </div>
            {selected.contract && <ContractSourceLinks block={selected}
                onNavigate={navigateTo} />}
            {selected.flow && <button type="button" className="flow-continue-button"
                onClick={() => handleFlow(selected)}>
              <ArrowRight size={15} />
              <span>继续主线</span>
              <b>{viewLabel(selected.flow.view)} · 编号 {selected.flow.id}</b>
            </button>}
            {activeEditing && !isContractView && <div className="block-edit-actions">
              <div className="block-edit-row">
                <button type="button" className="subtle-button"
                  onClick={() => setDialog({kind: 'block', mode: 'edit', blockId: selected.id})}>
                  <Pencil size={13} />编辑
                </button>
                {payload.flat ? <>
                  <button type="button" className="subtle-button"
                    title="在当前块所在容器里添加普通块"
                    onClick={() => addFlatBlock()}>
                    <Plus size={13} />添加块
                  </button>
                  <button type="button" className="subtle-button"
                    title="添加一个同级分支块"
                    onClick={addFlatBranchBlock}>
                    <GitBranch size={13} />分支块
                  </button>
                  <button type="button" className="subtle-button"
                    title="添加一个同级 try 结构"
                    onClick={addFlatTryBlock}>
                    <ShieldAlert size={13} />try 块
                  </button>
                  {selected.type === 'branch' && <button type="button" className="subtle-button"
                    title="给这个分支块添加一条分支列表"
                    onClick={() => addFlatBranch(selected.id)}>
                    <Plus size={13} />分支列表
                  </button>}
                  {selected.type === 'branch' && selected.kind === 'try' && !selected.finally
                    && <button type="button" className="subtle-button"
                      onClick={() => addFlatFinally(selected.id)}>
                      <Plus size={13} />finally
                    </button>}
                </> : selectedIsTop && <>
                  <button type="button" className="subtle-button" disabled={!canMoveUp}
                    title={selectedTopIndex === 1 && firstHasOn
                      ? '第一个块带 on，不能把其他块移到它前面' : '上移'}
                    onClick={() => void moveBlock(selected.id, -1)}>
                    <ArrowUp size={13} />上移
                  </button>
                  <button type="button" className="subtle-button" disabled={!canMoveDown}
                    title={selectedTopIndex === 0 && firstHasOn
                      ? '带 on 的首块不能下移' : '下移'}
                    onClick={() => void moveBlock(selected.id, 1)}>
                    <ArrowDown size={13} />下移
                  </button>
                </>}
              </div>
              {/* 删除是不可逆操作，单独一行，避免和增改按钮排在一起被误点。 */}
              <button type="button" className="danger-button block-edit-danger"
                onClick={() => setDialog({kind: 'delete-block', blockId: selected.id})}>
                <Trash2 size={13} />删除
              </button>
            </div>}
            <dl className="block-facts">
              <div><dt>编号</dt><dd>{selected.id}</dd></div>
              <div><dt>类型</dt><dd>{selectedContract
                ? selectedContract.kind === 'type' ? '契约类型 type' : '契约接口 endpoint'
                : selected.type === 'branch' ? '条件分支块 branch' : '普通块 normal'}</dd></div>
              {selectedContract?.kind === 'type'
                && <div><dt>字段</dt><dd>{selectedContract.fields.length} 个</dd></div>}
              {selectedContract?.kind === 'endpoint'
                && <div><dt>接口</dt><dd>{selectedContract.method} {selectedContract.path}</dd></div>}
              {selected.next !== undefined
                && <div><dt>next</dt><dd>{selected.next === null ? '终止（不产生后继）' : `→ ${selected.next}`}</dd></div>}
              {selected.flow
                && <div><dt>主线继续</dt><dd>
                  <button type="button" className="event-target-link"
                    onClick={() => handleFlow(selected)}>
                    {selected.flow.view || '其他视图'} · {selected.flow.id}
                  </button>
                </dd></div>}
              {selected.jump
                && <div><dt>跳转</dt><dd>
                  <button type="button" className="event-target-link"
                    onClick={() => handleJump(selected)}>
                    {selected.jump.view ? `视图 ${selected.jump.view} · ` : '本视图 · '}
                    编号 {selected.jump.id}
                  </button>
                </dd></div>}
              {selected.on && <div><dt>事件入口</dt><dd>{selected.on}</dd></div>}
              {!!selected.emit?.length && <div><dt>事件发出</dt><dd>{selected.emit!.map((item, index) => (
                <span key={`${item.view || 'self'}-${item.id}-${index}`}>
                  {index > 0 && '、'}
                  <button type="button" className="event-target-link"
                    onClick={() => handleEvent(selected, item)}>
                    {item.view || '本视图'} · {item.id}
                  </button>
                </span>
              ))}</dd></div>}
              {selected.type === 'branch' && (selected.kind === 'try' ? <>
                <div><dt>结构</dt><dd>try / except / finally</dd></div>
                <div><dt>try 主体</dt><dd>{selected.branches![0].steps.length} 步</dd></div>
                <div><dt>异常分支</dt><dd>{selected.branches!.slice(1).length} 条
                  {selected.branches!.slice(1).length > 0
                    && (selected.branches!.slice(1).some(list => list.condition)
                      ? '（条件写在扇出线上）' : '（无条件）')}</dd></div>
                <div><dt>finally</dt><dd>{selected.finally?.length ? `${selected.finally.length} 步` : '无'}</dd></div>
              </> : <>
                <div><dt>选择模式</dt><dd>{selected.select === 'single'
                  ? '单选 · 所有分支只进一条' : '多选 · 并行执行'}</dd></div>
                <div><dt>分支列表</dt><dd>{selected.branches!.length} 条
                  {selected.branches!.some(list => list.condition) ? '（含进入条件，写在扇出线上）' : '（无条件直接进入）'}</dd></div>
              </>)}
              {selected.code_mapping
                && <div><dt>代码映射</dt><dd>{selected.code_mapping.file} · {linesLabel(selected.code_mapping.lines)}</dd></div>}
            </dl>
            {selectedCode
              ? selectedCode.ranges.map((range, index) => <div className="block-code-group" key={`${range.start}-${range.end}`}>
                  {index > 0 && <div className="block-code-gap">跳过未映射的行</div>}
                  <div className="reader-source">
                    <div className="source-location"><FileCode2 size={15} /><span>{selectedCode.file}</span>
                      <small>L{range.start}{range.end !== range.start ? `–${range.end}` : ''}</small></div>
                    <CodeLines lines={range.lines.map(row => ({line: row.number, text: row.text}))} />
                  </div>
                </div>)
              : selectedContract
                ? <div className="source-empty"><FileCode2 size={30} /><h3>契约条目不直接附代码</h3>
                    <p>用上方的“来源 / 处理”跳到已有块查看代码。</p></div>
                : <div className="source-empty"><FileCode2 size={30} /><h3>未附代码映射</h3>
                    <p>{selected.type === 'branch' ? '分支块的代码映射由内部步骤提供。' : '这个块没有写 code_mapping 字段。'}</p></div>}
          </> : <div className="source-empty"><FileCode2 size={30} /><h3>未选择块</h3><p>单击左侧列表或图中的块查看详情。</p></div>}
        </div>
      </aside>
    </main>}
    <footer className="reader-footer"><span>{sourceKind}</span>
      <span title={payload?.source.path}>{payload?.source.path?.split('/').pop() || 'blocks.json'}</span>
      <span className="footer-note">{isContractView ? '契约 · 表格视图' : '基础块 · 连线自动生成'}</span></footer>
    {styleGallery && <NormalStyleGallery current={normalStyle} samples={styleSamples}
      onApply={applyNormalStyle} onClose={() => setStyleGallery(false)} />}
    {dialog?.kind === 'project-settings' && index?.source.path
      && <ProjectSettingsDialog workspacePath={index.source.path}
          onApply={applyProjectSettings} onClose={() => setDialog(null)} />}
    {dialog?.kind === 'workspace' && <WorkspaceDialog currentPath={workspacePath}
      onOpen={openWorkspace} onClose={() => setDialog(null)} />}
    {dialog?.kind === 'new-view' && <NewViewDialog views={views}
      onApply={applyView} onClose={() => setDialog(null)} />}
    {dialog?.kind === 'view-settings' && payload && <ViewSettingsDialog
      config={payload.config} file={payload.view?.file}
      entry={index?.entry === payload.config.view.id}
      onApply={applyView} onOpenJson={() => setDialog({kind: 'view-json'})}
      onDelete={() => setDialog({kind: 'delete-view'})}
      onClose={() => setDialog(null)} />}
    {dialog?.kind === 'view-json' && payload && <ViewJsonDialog
      config={payload.config} onApply={applyView} onClose={() => setDialog(null)} />}
    {dialog?.kind === 'block' && payload && (dialog.mode === 'edit'
      ? editingBlock && <BlockEditorDialog mode="edit" config={payload.config}
          block={editingBlock} views={views} files={payload.project?.files || []}
          topLevelIds={payload.order} workspacePath={index?.source.path}
          flatMode={!!payload.flat}
          onApply={applyView}
          onOpenJson={() => setDialog({kind: 'view-json'})}
          onClose={() => setDialog(null)} />
      : <BlockEditorDialog mode="create" config={payload.config}
          afterId={dialog.afterId} views={views} files={payload.project?.files || []}
          topLevelIds={payload.order} workspacePath={index?.source.path}
          onApply={applyView}
          onOpenJson={() => setDialog({kind: 'view-json'})}
          onClose={() => setDialog(null)} />)}
    {dialog?.kind === 'delete-block' && payload && deletingBlock && <ConfirmDialog
      title="删除块"
      message={<>确定删除块 <b>{deletingBlock.id} · {deletingBlock.name}</b>？
        {deletingBlock.type === 'branch' ? ' 它内部的分支步骤也会一起删除。' : ''}
        {payload.flat
          ? ' 被 jump / flow / emit 引用的块会被拒绝；next 会自动接续。'
          : ' 被 next / jump / emit 引用时保存会失败。'}</>}
      confirmLabel="删除块" onConfirm={() => handleDeleteBlock(deletingBlock.id)}
      onClose={() => setDialog(null)} />}
    {dialog?.kind === 'delete-container' && payload && deletingContainer && <ConfirmDialog
      title="删除分支容器"
      message={<>确定删除容器 <b>{deletingContainer.id}</b>？
        它和其中的块会一起删除。分支块至少保留一个分支列表；被引用的块会被服务端拒绝。</>}
      confirmLabel="删除容器" onConfirm={async () => {
        await applyFlatMutation('delete_container',
          {container_id: deletingContainer.id});
      }}
      onClose={() => setDialog(null)} />}
    {dialog?.kind === 'delete-view' && payload && <ConfirmDialog
      title="删除视图"
      message={<>确定删除视图 <b>{payload.config.view.name}（{payload.config.view.id}）</b>？
        {index?.entry === payload.config.view.id ? ' 它是入口视图，删除后入口会自动改为其他视图。' : ''}
        被 jump / emit 引用时保存会失败。</>}
      confirmLabel="删除视图" onConfirm={handleDeleteView}
      onClose={() => setDialog(null)} />}
  </div>;
}
