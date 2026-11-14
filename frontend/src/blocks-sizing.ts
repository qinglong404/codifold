/** Shared sizing rules for every normal block and branch decision node.
 *
 * 统一规则：
 * - 高度固定 88，所有层级一致，不再因为嵌套而缩小。
 * - 宽度按标题/描述长度分 300 / 340 / 400 三档。
 * - 标题最多 1 行、描述最多 2 行，超出用省略号，完整内容在右侧详情。
 */
export const BLOCK_H = 88;
export const BLOCK_MIN_W = 300;
export const BLOCK_MID_W = 340;
export const BLOCK_MAX_W = 400;
/** 分支列之间的空隙同时是 next 回指线的走廊。
 *  TARGET_LANE 是 30，所以空隙必须明显大于它，并给霓虹光晕留余量；
 *  否则回指线会贴着或钻进相邻块，被卡片遮住。 */
export const LIST_GAP = 64;

const WIDE_CHAR = /[\u2e80-\u9fff\uf900-\ufaff\u3000-\u303f]/;

function textUnits(text: string): number {
  let units = 0;
  for (const char of text) units += WIDE_CHAR.test(char) ? 1 : 0.55;
  return units;
}

/** 标题一行 + 描述两行大致需要的内容宽度。 */
function widthScore(name: string, description: string): number {
  return Math.max(textUnits(name) * 16, textUnits(description) * 5);
}

export function blockWidth(name: string, description: string): number {
  const score = widthScore(name, description);
  if (score > 260) return BLOCK_MAX_W;
  if (score > 180) return BLOCK_MID_W;
  return BLOCK_MIN_W;
}

/** 分支点右侧还要放“单选/并行/TRY”标签，阈值略高。 */
export function branchWidth(name: string, description: string): number {
  const score = widthScore(name, description) + 40;
  if (score > 260) return BLOCK_MAX_W;
  if (score > 180) return BLOCK_MID_W;
  return BLOCK_MIN_W;
}
