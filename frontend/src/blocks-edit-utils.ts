import type {CodeMapping, RBlock} from './blocks-types';

export function collectIds(blocks: RBlock[], into: number[] = []): number[] {
  for (const block of blocks) {
    into.push(block.id);
    block.branches?.forEach(list => collectIds(list.steps, into));
    if (block.finally) collectIds(block.finally, into);
  }
  return into;
}

export function maxBlockId(blocks: RBlock[]): number {
  return collectIds(blocks).reduce((max, id) => Math.max(max, id), 0);
}

export function hasBlock(blocks: RBlock[], id: number): boolean {
  if (id <= 0) return false;
  return collectIds(blocks).includes(id);
}

export function replaceBlock(blocks: RBlock[], id: number, next: RBlock): RBlock[] {
  return blocks.map(block => {
    if (block.id === id) return next;
    return {
      ...block,
      ...(block.branches
        ? {branches: block.branches.map(list => ({
            ...list, steps: replaceBlock(list.steps, id, next),
          }))}
        : {}),
      ...(block.finally ? {finally: replaceBlock(block.finally, id, next)} : {}),
    };
  });
}

export function removeBlock(blocks: RBlock[], id: number): RBlock[] {
  return blocks
    .filter(block => block.id !== id)
    .map(block => ({
      ...block,
      ...(block.branches
        ? {branches: block.branches.map(list => ({
            ...list, steps: removeBlock(list.steps, id),
          }))}
        : {}),
      ...(block.finally ? {finally: removeBlock(block.finally, id)} : {}),
    }));
}

export function linesText(mapping?: CodeMapping): string {
  return mapping ? mapping.lines.map(item => String(item)).join(', ') : '';
}

export function parseLineText(text: string): (number | string)[] {
  return text.split(/[\s,，]+/).filter(Boolean).map(token =>
    /^\d+$/.test(token) ? Number(token) : token);
}
