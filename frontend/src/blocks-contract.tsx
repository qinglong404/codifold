import {useEffect, useRef} from 'react';
import {ArrowUpRight, Link2} from 'lucide-react';
import type {
  ContractEndpoint, ContractType, EventTarget, RBlock,
} from './blocks-types';

type Navigate = (view: string, id: number, sourceId: number) => void;

const isTypeBlock = (block: RBlock): block is RBlock & {contract: ContractType} =>
  block.contract?.kind === 'type';

const isEndpointBlock = (block: RBlock): block is RBlock & {contract: ContractEndpoint} =>
  block.contract?.kind === 'endpoint';

export function ContractSourceLinks({block, onNavigate}: {
  block: RBlock;
  onNavigate: Navigate;
}) {
  const endpoint = block.contract?.kind === 'endpoint' ? block.contract : null;
  const refs: {label: string; ref: EventTarget}[] = [
    ...(block.evidence || []).map(ref => ({label: '来源', ref})),
    ...(endpoint?.handler ? [{label: '处理', ref: endpoint.handler}] : []),
  ].filter(item => !!item.ref.view);
  if (!refs.length) return null;
  return (
    <div className="contract-source-links">
      {refs.map((item, index) => (
        <button key={`${item.label}-${item.ref.view}-${item.ref.id}-${index}`}
          type="button" className="contract-link"
          onClick={event => {
            event.stopPropagation();
            if (item.ref.view) onNavigate(item.ref.view, item.ref.id, block.id);
          }}>
          <Link2 size={11} />{item.label} {item.ref.view}:{item.ref.id}
        </button>
      ))}
    </div>
  );
}

function TypeRef({name, typeByName, onSelect}: {
  name: string;
  typeByName: Map<string, number>;
  onSelect: (id: number) => void;
}) {
  const targetId = typeByName.get(name.replace(/\[\]$/, ''));
  if (targetId === undefined) return <span>{name}</span>;
  return (
    <button type="button" className="contract-ref"
      onClick={event => {
        event.stopPropagation();
        onSelect(targetId);
      }}>
      {name}
    </button>
  );
}

export function ContractTables({blocks, selectedId, onSelect, onNavigate}: {
  blocks: RBlock[];
  selectedId: number;
  onSelect: (id: number) => void;
  onNavigate: Navigate;
}) {
  const types = blocks.filter(isTypeBlock);
  const endpoints = blocks.filter(isEndpointBlock);
  const typeByName = new Map<string, number>(
    types.map(block => [block.name, block.id]));
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const target = container.current?.querySelector(
      `[data-contract-id="${selectedId}"]`);
    target?.scrollIntoView({block: 'nearest', behavior: 'smooth'});
  }, [selectedId]);

  return (
    <div className="contract-sheet" ref={container}>
      {types.length > 0 && <section className="contract-section">
        <div className="contract-section-head">
          <h2>类型</h2><small>{types.length} 个</small>
        </div>
        <div className="contract-type-grid">
          {types.map(block => (
            <article key={block.id} data-contract-id={block.id}
              className={`contract-type-card ${selectedId === block.id ? 'active' : ''}`}
              onClick={() => onSelect(block.id)}>
              <header>
                <div>
                  <h3>{block.name}<span className="contract-id">#{block.id}</span></h3>
                  <p>{block.description}</p>
                </div>
                <ContractSourceLinks block={block} onNavigate={onNavigate} />
              </header>
              <table className="contract-table">
                <thead><tr>
                  <th>字段</th><th>类型/取值</th><th>必填</th><th>说明</th>
                </tr></thead>
                <tbody>
                  {block.contract.fields.map(field => (
                    <tr key={field.name}>
                      <td><code>{field.name}</code></td>
                      <td>{field.type === 'enum' && field.values?.length
                        ? <span className="contract-enum">{field.values.join(' / ')}</span>
                        : <TypeRef name={field.type} typeByName={typeByName}
                            onSelect={onSelect} />}</td>
                      <td>{field.required ? '是' : ''}</td>
                      <td>{field.description || ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </article>
          ))}
        </div>
      </section>}
      {endpoints.length > 0 && <section className="contract-section">
        <div className="contract-section-head">
          <h2>接口</h2><small>{endpoints.length} 条</small>
        </div>
        <div className="contract-table-wrap">
          <table className="contract-table contract-endpoints">
            <thead><tr>
              <th>名称</th><th>方法</th><th>路径</th><th>鉴权</th>
              <th>请求</th><th>响应</th><th>错误</th><th>处理</th>
            </tr></thead>
            <tbody>
              {endpoints.map(block => {
                const endpoint = block.contract;
                return (
                  <tr key={block.id} data-contract-id={block.id}
                    className={selectedId === block.id ? 'active' : ''}
                    onClick={() => onSelect(block.id)}>
                    <td className="contract-name-cell">
                      <b>{block.name}</b><span className="contract-id">#{block.id}</span>
                      <p>{block.description}</p>
                    </td>
                    <td><span className={`contract-method method-${endpoint.method.toLowerCase()}`}>
                      {endpoint.method}</span></td>
                    <td><code>{endpoint.path}</code></td>
                    <td>{endpoint.auth ? '是' : ''}</td>
                    <td>{endpoint.request
                      ? <TypeRef name={endpoint.request} typeByName={typeByName}
                          onSelect={onSelect} />
                      : ''}</td>
                    <td>
                      {endpoint.response
                        ? <TypeRef name={endpoint.response} typeByName={typeByName}
                            onSelect={onSelect} />
                        : null}
                      {endpoint.status
                        ? <span className="contract-status">{endpoint.status}</span>
                        : null}
                    </td>
                    <td>{endpoint.errors?.length
                      ? <ul className="contract-errors">
                          {endpoint.errors.map(item => (
                            <li key={item.status}><b>{item.status}</b> {item.when}</li>
                          ))}
                        </ul>
                      : ''}</td>
                    <td>{endpoint.handler?.view
                      ? <button type="button" className="contract-link"
                          onClick={event => {
                            event.stopPropagation();
                            if (endpoint.handler?.view) {
                              onNavigate(endpoint.handler.view, endpoint.handler.id,
                                block.id);
                            }
                          }}>
                          <ArrowUpRight size={11} />
                          {endpoint.handler.view}:{endpoint.handler.id}
                        </button>
                      : endpoint.external ? '外部接口' : ''}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>}
    </div>
  );
}
