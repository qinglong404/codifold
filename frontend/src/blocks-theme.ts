/** Whole-canvas themes keyed by the normal-block style.
 *
 * 样式不再只作用于普通块：分支点、条件标签、事件/结束角标和连线都从
 * 同一份配色表取色。CSS 侧读自定义属性，SVG 连线在 JS 里直接取色。
 * app 背景也由这里驱动：纯黑底 + 主题色星云/星点，面板使用半透明玻璃。
 */
import type {NormalStyleId} from './blocks-styles';

export type EdgeTone = 'default' | 'single' | 'multi' | 'try' | 'except' | 'finally' | 'next';
export type ThemeSurface = 'dark' | 'light';

type ThemeSpec = {
  surface: ThemeSurface;
  single: string;
  single2: string;
  multi: string;
  multi2: string;
  tryBranch: string;
  tryBranch2: string;
  tryEdge: string;
  except: string;
  finally: string;
  next: string;
  entry: string;
  emit: string;
  jump: string;
  end: string;
  edgeDefault: string;
  branchBg: string;
  branchInk: string;
  branchMuted: string;
  branchChipBg: string;
  labelBg: string;
  canvasDot: string;
  accent: string;
  nebula: string;
  star: string;
  chromeBg: string;
  chromeBorder: string;
  canvasBg: string;
};

const THEMES: Record<NormalStyleId, ThemeSpec> = {
  cyber: {
    surface: 'dark',
    single: '#f4c95d', single2: '#ff9f43',
    multi: '#56d9ff', multi2: '#4f7cff',
    tryBranch: '#ff6f8a', tryBranch2: '#ff9f43',
    tryEdge: '#5ce1c4', except: '#ff6f8a',
    finally: '#c39bff', next: '#b39cff',
    entry: '#6ef0c8', emit: '#b99cff', jump: '#7fbfff', end: '#ff7b93',
    edgeDefault: '#7fa8c9',
    branchBg: 'linear-gradient(145deg, #0b1524f2, #131a31f2 55%, #170a2bf2)',
    branchInk: '#f2f8ff', branchMuted: '#9fb9d6',
    branchChipBg: '#06101d', labelBg: '#0c1422', canvasDot: '#30364e',
    accent: '#7fe9ff', nebula: 'rgba(46, 230, 200, .14)', star: '#d7fbff',
    chromeBg: 'rgba(3, 8, 15, .78)', chromeBorder: 'rgba(110, 240, 220, .2)',
    canvasBg: 'rgba(2, 6, 12, .62)',
  },
  aurora: {
    surface: 'dark',
    single: '#ffd37a', single2: '#ffb35c',
    multi: '#66e6ff', multi2: '#6c8bff',
    tryBranch: '#ff86c8', tryBranch2: '#ffb37a',
    tryEdge: '#6ff0d0', except: '#ff86c8',
    finally: '#a8a0ff', next: '#9fb4ff',
    entry: '#7df2c0', emit: '#b8a7ff', jump: '#86c6ff', end: '#ff93b1',
    edgeDefault: '#8cc7cf',
    branchBg: 'linear-gradient(145deg, #041b1ff2, #061a2ef2 52%, #10102af2)',
    branchInk: '#effff9', branchMuted: '#9fd9cc',
    branchChipBg: '#04161a', labelBg: '#071a21', canvasDot: '#2c4a4c',
    accent: '#8ff7d0', nebula: 'rgba(92, 242, 180, .13)', star: '#e0fff8',
    chromeBg: 'rgba(2, 9, 10, .78)', chromeBorder: 'rgba(120, 240, 210, .2)',
    canvasBg: 'rgba(2, 8, 10, .62)',
  },
  plasma: {
    surface: 'dark',
    single: '#ffc46b', single2: '#ff8a5c',
    multi: '#7fe0ff', multi2: '#8b5cf6',
    tryBranch: '#ff5fa2', tryBranch2: '#ff8a5c',
    tryEdge: '#5ce1c4', except: '#ff5fa2',
    finally: '#c39bff', next: '#a78bfa',
    entry: '#6ef0c8', emit: '#d2a8ff', jump: '#86bfff', end: '#ff7b93',
    edgeDefault: '#a08fb8',
    branchBg: 'linear-gradient(145deg, #13051ff2, #1a0729f2 55%, #0b0618f2)',
    branchInk: '#fff2fc', branchMuted: '#d9a6d6',
    branchChipBg: '#11051c', labelBg: '#150a24', canvasDot: '#3a2c4e',
    accent: '#ff9ae8', nebula: 'rgba(255, 90, 210, .13)', star: '#ffe6fb',
    chromeBg: 'rgba(9, 3, 14, .78)', chromeBorder: 'rgba(255, 120, 210, .2)',
    canvasBg: 'rgba(8, 2, 12, .62)',
  },
  cosmos: {
    surface: 'dark',
    single: '#ffd166', single2: '#ff9f43',
    multi: '#6fd8ff', multi2: '#4f7cff',
    tryBranch: '#ff7ab6', tryBranch2: '#a06bff',
    tryEdge: '#5ce1c4', except: '#ff7ab6',
    finally: '#9c8bff', next: '#8ea8ff',
    entry: '#6ef0c8', emit: '#b09cff', jump: '#7fbfff', end: '#ff88a3',
    edgeDefault: '#7fa8c9',
    branchBg: 'linear-gradient(145deg, #02040af2, #050814f2 55%, #080414f2)',
    branchInk: '#eef9ff', branchMuted: '#9dbdd9',
    branchChipBg: '#02040a', labelBg: '#03060e', canvasDot: '#080c16',
    accent: '#9fdcff', nebula: 'rgba(70, 120, 255, .2)', star: '#eaf6ff',
    chromeBg: 'rgba(0, 2, 8, .6)', chromeBorder: 'rgba(120, 170, 255, .24)',
    canvasBg: 'rgba(0, 1, 5, .34)',
  },
  holo: {
    surface: 'dark',
    single: '#d8ff6e', single2: '#7df9ff',
    multi: '#7df9ff', multi2: '#ff6ad5',
    tryBranch: '#ff6ad5', tryBranch2: '#ff9f6e',
    tryEdge: '#b6ff6a', except: '#ff6ad5',
    finally: '#a78bfa', next: '#ffb86b',
    entry: '#b6ff6a', emit: '#ff8de0', jump: '#7df9ff', end: '#ff7b93',
    edgeDefault: '#8fb8c9',
    branchBg: 'linear-gradient(145deg, #08111ff2, #0c1626f2)',
    branchInk: '#f5ffff', branchMuted: '#a7c4cf',
    branchChipBg: '#061019', labelBg: '#0a1622', canvasDot: '#2b4650',
    accent: '#9ffff4', nebula: 'rgba(125, 249, 255, .12)', star: '#eaffff',
    chromeBg: 'rgba(2, 7, 11, .78)', chromeBorder: 'rgba(125, 249, 255, .2)',
    canvasBg: 'rgba(1, 5, 9, .62)',
  },
  synth: {
    surface: 'dark',
    single: '#ffc36b', single2: '#ff9a62',
    multi: '#7fe3ff', multi2: '#4f7cff',
    tryBranch: '#ff5f8f', tryBranch2: '#ff9a62',
    tryEdge: '#5ce1c4', except: '#ff5f8f',
    finally: '#b99cff', next: '#c39bff',
    entry: '#6ef0c8', emit: '#ff8de0', jump: '#86bfff', end: '#ff7b93',
    edgeDefault: '#c9a0a8',
    branchBg: 'linear-gradient(145deg, #17050ff2, #20081ff2 55%, #0a0618f2)',
    branchInk: '#fff4ec', branchMuted: '#d9a6b8',
    branchChipBg: '#160810', labelBg: '#180a16', canvasDot: '#402a3a',
    accent: '#ffb88a', nebula: 'rgba(255, 80, 160, .13)', star: '#ffe9db',
    chromeBg: 'rgba(10, 3, 8, .8)', chromeBorder: 'rgba(255, 140, 160, .2)',
    canvasBg: 'rgba(8, 2, 6, .62)',
  },
  paper: {
    surface: 'light',
    single: '#8a5d12', single2: '#b9821f',
    multi: '#1f5f82', multi2: '#357fa6',
    tryBranch: '#9c3249', tryBranch2: '#b95a45',
    tryEdge: '#1f6e5a', except: '#9c3249',
    finally: '#5b4a96', next: '#5a4f8c',
    entry: '#1f6e50', emit: '#5b4290', jump: '#2b5c8a', end: '#9c3249',
    edgeDefault: '#6b7785',
    branchBg: 'linear-gradient(145deg, #fdf8ec, #f1e6d1)',
    branchInk: '#3b3529', branchMuted: '#7f745f',
    branchChipBg: '#fffdf6', labelBg: '#fdf8ec', canvasDot: '#30364e',
    accent: '#e6bd7f', nebula: 'rgba(200, 150, 80, .1)', star: '#fff4d8',
    chromeBg: 'rgba(7, 6, 4, .82)', chromeBorder: 'rgba(220, 190, 140, .18)',
    canvasBg: 'rgba(6, 5, 3, .6)',
  },
  ink: {
    surface: 'dark',
    single: '#e8c46a', single2: '#d9a24a',
    multi: '#7fd7c4', multi2: '#4fa8c9',
    tryBranch: '#e98a9c', tryBranch2: '#d96a7a',
    tryEdge: '#7fd7c4', except: '#e98a9c',
    finally: '#a99be8', next: '#9aa8e8',
    entry: '#7fd7c4', emit: '#b3a4f3', jump: '#86c6ff', end: '#e98a9c',
    edgeDefault: '#7e93ad',
    branchBg: 'linear-gradient(150deg, #131d2e, #0e1624)',
    branchInk: '#e9f0fa', branchMuted: '#8597b0',
    branchChipBg: '#0a1220', labelBg: '#0d1624', canvasDot: '#30364e',
    accent: '#8fe0cd', nebula: 'rgba(80, 160, 150, .1)', star: '#e6fff9',
    chromeBg: 'rgba(3, 6, 10, .82)', chromeBorder: 'rgba(120, 180, 170, .18)',
    canvasBg: 'rgba(2, 4, 7, .62)',
  },
  glass: {
    surface: 'dark',
    single: '#ffd479', single2: '#ffb35c',
    multi: '#8bc5ff', multi2: '#5f9dff',
    tryBranch: '#ff8fa8', tryBranch2: '#ffb37a',
    tryEdge: '#6fe0c8', except: '#ff8fa8',
    finally: '#b9a8ff', next: '#a8b8ff',
    entry: '#7fe8c8', emit: '#b9a8ff', jump: '#8bc5ff', end: '#ff8fa8',
    edgeDefault: '#9db8d4',
    branchBg: 'linear-gradient(135deg, #2b3d5fd9, #192844cc)',
    branchInk: '#f1f7ff', branchMuted: '#a9bed9',
    branchChipBg: '#12203a', labelBg: '#13203a', canvasDot: '#30364e',
    accent: '#a8d4ff', nebula: 'rgba(90, 150, 255, .12)', star: '#eaf5ff',
    chromeBg: 'rgba(4, 8, 16, .74)', chromeBorder: 'rgba(140, 190, 255, .2)',
    canvasBg: 'rgba(3, 7, 14, .58)',
  },
  sticky: {
    surface: 'light',
    single: '#8f5e0e', single2: '#b77a13',
    multi: '#2b6f8a', multi2: '#3d8fb5',
    tryBranch: '#a63f36', tryBranch2: '#c25a3f',
    tryEdge: '#2a7d5c', except: '#a63f36',
    finally: '#6b5aa8', next: '#6a5f9c',
    entry: '#2a7d5c', emit: '#6b4fa0', jump: '#336a9c', end: '#a63f36',
    edgeDefault: '#8a7a52',
    branchBg: 'linear-gradient(140deg, #ffedb0, #ffdc78)',
    branchInk: '#4c3a10', branchMuted: '#7c672a',
    branchChipBg: '#fff3c8', labelBg: '#fff3c8', canvasDot: '#30364e',
    accent: '#ffd98a', nebula: 'rgba(220, 170, 60, .1)', star: '#fff2c8',
    chromeBg: 'rgba(10, 8, 3, .82)', chromeBorder: 'rgba(230, 200, 130, .18)',
    canvasBg: 'rgba(8, 6, 2, .62)',
  },
  minimal: {
    surface: 'dark',
    single: '#e8c46a', single2: '#c9a24a',
    multi: '#7fd7ff', multi2: '#5fa8d9',
    tryBranch: '#ff8fa8', tryBranch2: '#d96a7a',
    tryEdge: '#7fe8c8', except: '#ff8fa8',
    finally: '#b3a4f3', next: '#b3a4f3',
    entry: '#8fe8c8', emit: '#c3b3ff', jump: '#9cc8ff', end: '#ff9db0',
    edgeDefault: '#8a9ab2',
    branchBg: 'linear-gradient(145deg, #111a29d9, #0c1320d9)',
    branchInk: '#e1e8f5', branchMuted: '#8593aa',
    branchChipBg: '#0a101c', labelBg: '#101827', canvasDot: '#30364e',
    accent: '#c9bcff', nebula: 'rgba(140, 120, 255, .11)', star: '#f0ecff',
    chromeBg: 'rgba(3, 4, 8, .82)', chromeBorder: 'rgba(170, 160, 230, .16)',
    canvasBg: 'rgba(2, 3, 6, .64)',
  },
  terminal: {
    surface: 'dark',
    single: '#d9b45a', single2: '#c99a3a',
    multi: '#5fd7ff', multi2: '#3fa8d9',
    tryBranch: '#ff6b6b', tryBranch2: '#ff9a5c',
    tryEdge: '#6ee7a8', except: '#ff6b6b',
    finally: '#b39cff', next: '#9fd7a8',
    entry: '#6ee7a8', emit: '#b39cff', jump: '#6fc8ff', end: '#ff7b7b',
    edgeDefault: '#7ea48e',
    branchBg: 'linear-gradient(180deg, #0b1310, #09100d)',
    branchInk: '#d9f8e5', branchMuted: '#7ea48e',
    branchChipBg: '#06100b', labelBg: '#08110e', canvasDot: '#263a32',
    accent: '#7ff0b0', nebula: 'rgba(60, 200, 120, .1)', star: '#e4ffec',
    chromeBg: 'rgba(2, 6, 3, .84)', chromeBorder: 'rgba(110, 230, 168, .18)',
    canvasBg: 'rgba(1, 4, 2, .64)',
  },
  blueprint: {
    surface: 'dark',
    single: '#f0c96a', single2: '#d9a84a',
    multi: '#67b6f0', multi2: '#3d8fd9',
    tryBranch: '#ff8a8a', tryBranch2: '#ffb36b',
    tryEdge: '#6fd9c0', except: '#ff8a8a',
    finally: '#a8b8ff', next: '#8fa8d9',
    entry: '#6fd9c0', emit: '#a8b8ff', jump: '#67b6f0', end: '#ff8a8a',
    edgeDefault: '#82a8c7',
    branchBg: 'linear-gradient(160deg, #0d1b2d, #0a1626)',
    branchInk: '#dcefff', branchMuted: '#82a8c7',
    branchChipBg: '#081321', labelBg: '#0a1626', canvasDot: '#29425c',
    accent: '#8fcfff', nebula: 'rgba(60, 140, 255, .12)', star: '#e6f4ff',
    chromeBg: 'rgba(2, 5, 10, .8)', chromeBorder: 'rgba(110, 180, 240, .2)',
    canvasBg: 'rgba(1, 4, 8, .6)',
  },
};

const theme = (id: NormalStyleId): ThemeSpec => THEMES[id] || THEMES.cyber;

export const themeSurface = (id: NormalStyleId): ThemeSurface => theme(id).surface;

export const themeCanvasDot = (id: NormalStyleId): string => theme(id).canvasDot;

export function themeEdges(id: NormalStyleId): Record<EdgeTone, string> {
  const spec = theme(id);
  return {
    default: spec.edgeDefault,
    single: spec.single,
    multi: spec.multi,
    try: spec.tryEdge,
    except: spec.except,
    finally: spec.finally,
    next: spec.next,
  };
}

/** 挂到画布根节点，让 CSS 与 SVG 标签共用同一套配色。 */
export function themeVars(id: NormalStyleId): Record<string, string> {
  const spec = theme(id);
  return {
    '--tone-single': spec.single,
    '--tone-single-2': spec.single2,
    '--tone-multi': spec.multi,
    '--tone-multi-2': spec.multi2,
    '--tone-try': spec.tryBranch,
    '--tone-try-2': spec.tryBranch2,
    '--edge-default': spec.edgeDefault,
    '--edge-try': spec.tryEdge,
    '--edge-except': spec.except,
    '--edge-finally': spec.finally,
    '--edge-next': spec.next,
    '--role-entry': spec.entry,
    '--role-emit': spec.emit,
    '--role-jump': spec.jump,
    '--role-flow': spec.next,
    '--role-end': spec.end,
    '--branch-bg': spec.branchBg,
    '--branch-ink': spec.branchInk,
    '--branch-muted': spec.branchMuted,
    '--branch-chip-bg': spec.branchChipBg,
    '--label-bg': spec.labelBg,
    '--canvas-dot': spec.canvasDot,
    '--theme-accent': spec.accent,
    '--app-nebula': spec.nebula,
    '--app-star': spec.star,
    '--chrome-bg': spec.chromeBg,
    '--chrome-border': spec.chromeBorder,
    '--canvas-bg': spec.canvasBg,
    '--violet': spec.accent,
  };
}
