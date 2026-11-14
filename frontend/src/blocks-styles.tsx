import {Fragment, useEffect} from 'react';
import type {CSSProperties} from 'react';
import {
  ArrowRight, Box, Calculator, Check, CornerUpLeft, Download, GitBranch, Monitor,
  Pencil, Play,
  Save, ShieldCheck, Square, Trash2, X, Zap,
} from 'lucide-react';
import {BLOCK_H, blockWidth} from './blocks-sizing';
import {themeSurface, themeVars} from './blocks-theme';

export type NormalStyleId =
  | 'cyber'
  | 'aurora'
  | 'plasma'
  | 'cosmos'
  | 'holo'
  | 'synth'
  | 'paper'
  | 'ink'
  | 'glass'
  | 'sticky'
  | 'minimal'
  | 'terminal'
  | 'blueprint';

export type StyleSample = {id: number; name: string; description: string};
export type BlockSemantic = 'entry' | 'emit' | 'flow' | 'jump' | 'end';

type StyleGroup = 'neon' | 'clean';
type StyleDefinition = {
  id: NormalStyleId;
  group: StyleGroup;
  name: string;
  tagline: string;
  note: string;
  recommended?: boolean;
};

export const NORMAL_STYLES: StyleDefinition[] = [
  {
    id: 'cyber',
    group: 'neon',
    name: '赛博玻璃',
    tagline: '青色 → 紫罗兰 → 洋红的渐变边，深色玻璃底，带发光端口。',
    note: '最接近参考图：ID 徽章、图标、发光节点和画布边缘的霓虹层次。',
    recommended: true,
  },
  {
    id: 'aurora',
    group: 'neon',
    name: '极光',
    tagline: '青绿 → 冰蓝 → 紫的极光带，边缘泛光。',
    note: '比赛博玻璃更冷、更通透，适合数据流和处理步骤。',
  },
  {
    id: 'plasma',
    group: 'neon',
    name: '等离子',
    tagline: '洋红与紫罗兰的脉冲光，最强烈的霓虹感。',
    note: '视觉冲击最大；块多时建议只把关键块用这个色系。',
  },
  {
    id: 'cosmos',
    group: 'neon',
    name: '星海',
    tagline: '纯黑星空、青色星点与蓝色光边。',
    note: '整页背景会变成纯黑星海；最适合配合 2560×1600 大屏阅读。',
  },
  {
    id: 'holo',
    group: 'neon',
    name: '全息',
    tagline: '青、洋红、荧光绿的全息边，带扫描线。',
    note: '最“未来界面”的一套，颜色变化最多。',
  },
  {
    id: 'synth',
    group: 'neon',
    name: '合成波',
    tagline: '橙红 → 洋红 → 紫的落日渐变，复古未来感。',
    note: '给冷色画布加一点暖色，适合强调入口和出口。',
  },
  {
    id: 'paper',
    group: 'clean',
    name: '纸卡',
    tagline: '暖色纸张、衬线标题，阅读感最柔和。',
    note: '接近原来的浅色卡片，但去掉了 next / 代码映射等小标签。',
  },
  {
    id: 'ink',
    group: 'clean',
    name: '墨线',
    tagline: '深色底、细边角标，冷静克制。',
    note: '和右侧深色面板最统一，长时间阅读不刺眼。',
  },
  {
    id: 'glass',
    group: 'clean',
    name: '玻璃',
    tagline: '半透明渐变、高光与柔和光晕。',
    note: '层次感强，放在点阵画布上会比较轻。',
  },
  {
    id: 'sticky',
    group: 'clean',
    name: '便签',
    tagline: '黄色便签与折角，轻松、有记忆点。',
    note: '最像“人写给自己的步骤”，适合非技术读者。',
  },
  {
    id: 'minimal',
    group: 'clean',
    name: '极简',
    tagline: '去掉卡片容器，只留编号、标题和一条竖线。',
    note: '信息密度最低，画面最安静，但对背景对比要求高。',
  },
  {
    id: 'terminal',
    group: 'clean',
    name: '终端',
    tagline: '等宽字体、绿色提示符，技术感最强。',
    note: '适合开发者；和“流程阅读器”的气质稍微偏硬。',
  },
  {
    id: 'blueprint',
    group: 'clean',
    name: '蓝图',
    tagline: '网格底、工程角标，像一张结构图。',
    note: '介于墨线和终端之间，结构感强，不抢正文。',
  },
];

const IDS = new Set<string>(NORMAL_STYLES.map(style => style.id));
const NEON_IDS = new Set<NormalStyleId>(
  NORMAL_STYLES.filter(style => style.group === 'neon').map(style => style.id));

export const isNormalStyleId = (value: string | null): value is NormalStyleId =>
  !!value && IDS.has(value);

export const isNeonStyle = (id: NormalStyleId): boolean => NEON_IDS.has(id);

export const normalStyleName = (id: NormalStyleId): string =>
  NORMAL_STYLES.find(style => style.id === id)?.name || id;

const GROUPS: {id: StyleGroup; title: string; note: string}[] = [
  {
    id: 'neon',
    title: '炫酷 · NEON',
    note: '深色玻璃 + 霓虹渐变边 + 发光端口，参考你给的工作流节点库。',
  },
  {
    id: 'clean',
    title: '克制 · CLEAN',
    note: '上一轮的七套基础方案，保留对比。',
  },
];

function StepIcon({name, semantic}: {name: string; semantic?: BlockSemantic}) {
  const props = {size: 18, strokeWidth: 2};
  if (semantic === 'end') return <Square {...props} />;
  if (semantic === 'flow') return <ArrowRight {...props} />;
  if (semantic === 'emit' || semantic === 'entry') return <Zap {...props} />;
  if (semantic === 'jump') return <CornerUpLeft {...props} />;
  if (name.includes('开始') || name.includes('启动')) return <Play {...props} />;
  if (name.includes('结束') || name.includes('终止')) return <Square {...props} />;
  if (name.includes('读取') || name.includes('加载') || name.includes('输入')) {
    return <Download {...props} />;
  }
  if (name.includes('保存') || name.includes('写入') || name.includes('存盘')) {
    return <Save {...props} />;
  }
  if (name.includes('检查') || name.includes('校验') || name.includes('验证')) {
    return <ShieldCheck {...props} />;
  }
  if (name.includes('删除')) return <Trash2 {...props} />;
  if (name.includes('修改') || name.includes('更新')) return <Pencil {...props} />;
  if (name.includes('显示') || name.includes('打印') || name.includes('输出')) {
    return <Monitor {...props} />;
  }
  if (name.includes('统计') || name.includes('计算')) return <Calculator {...props} />;
  if (name.includes('返回') || name.includes('跳转') || name.includes('跳出')) {
    return <CornerUpLeft {...props} />;
  }
  return <Box {...props} />;
}

/** 炫酷组：ID 徽章 + 右上角省略号 + 图标 + 名称/描述。 */
function NeonCardFace({sample, semantic}: {sample: StyleSample; semantic?: BlockSemantic}) {
  return <>
    <span className="block-id-badge">ID: {String(sample.id).padStart(3, '0')}</span>
    <span className="block-dots" aria-hidden="true">•••</span>
    <span className="block-icon"><StepIcon name={sample.name} semantic={semantic} /></span>
    <span className="block-copy">
      <b>{sample.name}</b>
      <small>{sample.description}</small>
    </span>
  </>;
}

/** 普通块真正展示的内容：编号 + 名称 + 描述；炫酷组额外带图标和 ID 徽章。 */
export function NormalCardFace({sample, style, semantic}: {
  sample: StyleSample;
  style?: NormalStyleId;
  semantic?: BlockSemantic;
}) {
  if (style && isNeonStyle(style)) return <NeonCardFace sample={sample} semantic={semantic} />;
  return <>
    <span className="block-ordinal">{sample.id}</span>
    <span className="block-copy">
      <b>{sample.name}</b>
      <small>{sample.description}</small>
    </span>
  </>;
}

const FALLBACK_SAMPLES: StyleSample[] = [
  {
    id: 1,
    name: '读取并校验用户输入',
    description: '读取终端输入，解析编号，并检查它是否在合法范围内。',
  },
  {
    id: 15,
    name: '检查输入',
    description: '确认编号有效。',
  },
];

export function NormalStyleGallery({current, samples, onApply, onClose}: {
  current: NormalStyleId;
  samples: StyleSample[];
  onApply: (style: NormalStyleId) => void;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const top = samples[0] || FALLBACK_SAMPLES[0]!;
  const nested = samples[1] || FALLBACK_SAMPLES[1]!;
  const topWidth = blockWidth(top.name, top.description);
  const nestedWidth = blockWidth(nested.name, nested.description);

  return <div className="dialog-overlay style-gallery-overlay"
      onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="style-gallery" role="dialog" aria-modal="true"
        aria-labelledby="style-gallery-title">
      <header className="style-gallery-head">
        <div>
          <span className="eyebrow">BLOCK THEME · STYLE LAB</span>
          <h2 id="style-gallery-title">整图外观方案 · 普通块 / 分支 / 线条</h2>
          <p>切换后普通块、分支点、条件标签、事件与结束角标、连线一起换色；统一尺寸规则不变：高 88，宽度按内容在 300 / 340 / 400 之间自适应，标题 1 行、描述 2 行。</p>
          <div className="semantic-legend" aria-label="流程图语义色板">
            <span className="semantic-legend-title">语义色</span>
            <span className="semantic-key single">单选分支</span>
            <span className="semantic-key multi">并行分支</span>
            <span className="semantic-key try">TRY / 异常</span>
            <span className="semantic-key entry">事件入口</span>
            <span className="semantic-key flow">主线继续</span>
            <span className="semantic-key emit">事件发出</span>
            <span className="semantic-key end">结束</span>
            <span className="semantic-key next">next 回指</span>
          </div>
        </div>
        <button type="button" className="editor-close" aria-label="关闭样式预览" onClick={onClose}>
          <X size={18} />
        </button>
      </header>
      <div className="style-gallery-grid">
        {GROUPS.map(group => <Fragment key={group.id}>
          <div className="style-group-head">
            <b>{group.title}</b><span>{group.note}</span>
          </div>
          {NORMAL_STYLES.filter(style => style.group === group.id).map(style => <article
              key={style.id} data-surface={themeSurface(style.id)}
              style={themeVars(style.id) as CSSProperties}
              className={`style-swatch ${current === style.id ? 'current' : ''}`}>
            <div className="style-swatch-head">
              <div className="style-swatch-title">
                <b>{style.name}</b>
                <code>{style.id}</code>
                {style.recommended && <em>推荐</em>}
              </div>
              {current === style.id
                ? <span className="style-current"><Check size={12} />当前使用</span>
                : <button type="button" className="style-apply"
                    onClick={() => onApply(style.id)}>在流程中使用</button>}
            </div>
            <p>{style.tagline}</p>
            <div className="style-swatch-stage">
              <span className="style-stage-label">普通块 · 顶层 <small>{topWidth} × {BLOCK_H}</small></span>
              <article className={`block-card style-${style.id} ${style.group === 'neon' ? 'neon' : ''}`}
                  style={{width: topWidth, height: BLOCK_H}}>
                <div className="block-card-button"><NormalCardFace sample={top} style={style.id} /></div>
              </article>
              <span className="style-stage-label">普通块 · 分支内 <small>{nestedWidth} × {BLOCK_H}</small></span>
              <article className={`block-card style-${style.id} ${style.group === 'neon' ? 'neon' : ''}`}
                  style={{width: nestedWidth, height: BLOCK_H}}>
                <div className="block-card-button"><NormalCardFace sample={nested} style={style.id} /></div>
              </article>
              <span className="style-stage-label">分支点 <small>同主题 · {BLOCK_H} 高</small></span>
              <article className={`branch-node tone-single style-${style.id} ${style.group === 'neon' ? 'neon' : ''} style-preview-branch`}
                  data-surface={themeSurface(style.id)}
                  style={{width: Math.min(topWidth, 340), height: BLOCK_H}}>
                <span className="branch-id">ID: 002</span>
                <span className="select-chip single">单选 · 2</span>
                <div className="branch-node-button">
                  <span className="branch-icon"><GitBranch size={18} /></span>
                  <span className="branch-copy"><b>检查输入</b><small>条件决定进入哪条分支</small></span>
                </div>
              </article>
              <span className="style-stage-label">条件标签与语义角标</span>
              <div className="style-stage-chips">
                <span className="edge-label-chip tone-single">条件 A</span>
                <span className="edge-label-chip tone-except">异常</span>
                <span className="edge-label-chip tone-next">next</span>
              </div>
              <div className="style-stage-roles">
                <span className="block-role-chip entry"><Zap size={9} />入口</span>
                <span className="block-role-chip emit"><Zap size={9} />发出</span>
                <span className="block-role-chip jump"><CornerUpLeft size={9} />跳转</span>
                <span className="block-role-chip end"><Square size={9} />结束</span>
              </div>
              <span className="style-stage-label">连线</span>
              <div className="style-stage-lines" aria-hidden="true">
                <i className="line-default" /><i className="line-single" /><i className="line-multi" />
                <i className="line-try" /><i className="line-except" /><i className="line-next" />
              </div>
            </div>
            <p className="style-swatch-note">{style.note}</p>
          </article>)}
        </Fragment>)}
      </div>
      <footer className="style-gallery-foot">
        <span>样式会同时作用于普通块、分支点、条件标签、事件/结束角标和全部连线。</span>
        <button type="button" className="subtle-button" onClick={onClose}>关闭预览</button>
      </footer>
    </section>
  </div>;
}
