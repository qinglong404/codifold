import type {
  BlockMutationResponse, BlocksResponse, BrowseResponse, CreateWorkspaceInput,
  CreateWorkspaceResponse, DeleteViewResponse,
  ForgetWorkspaceResponse,
  OpenWorkspaceResponse, ProjectManifest, ProjectSettingsResponse,
  RecentWorkspacesResponse, SaveProjectResponse, SaveViewResponse,
  ViewConfig, ViewsIndex,
} from './blocks-types';

export class RevisionConflictError extends Error {
  readonly code = 'revision_conflict';
  readonly currentRevision?: string;

  constructor(message: string, currentRevision?: string) {
    super(message);
    this.name = 'RevisionConflictError';
    this.currentRevision = currentRevision;
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  let data: unknown = {};
  try {
    data = await response.json();
  } catch {
    // Keep the empty object; the status still carries the failure.
  }
  if (!response.ok) {
    const payload = data && typeof data === 'object'
      ? data as {error?: unknown; code?: unknown; current_revision?: unknown}
      : {};
    const message = payload.error
      ? String(payload.error)
      : `请求失败（HTTP ${response.status}）`;
    if (response.status === 409 && payload.code === 'revision_conflict') {
      throw new RevisionConflictError(message,
        typeof payload.current_revision === 'string' ? payload.current_revision : undefined);
    }
    throw new Error(message);
  }
  return data as T;
}

export function fetchViews(path?: string): Promise<ViewsIndex> {
  const query = path ? '?path=' + encodeURIComponent(path) : '';
  return request<ViewsIndex>('/api/views' + query);
}

export function fetchView(path: string, view: string): Promise<BlocksResponse> {
  return request<BlocksResponse>('/api/blocks-config?path=' + encodeURIComponent(path)
    + '&view=' + encodeURIComponent(view));
}

export function fetchEvents(path: string): Promise<{events: string[]}> {
  return request<{events: string[]}>('/api/events?path=' + encodeURIComponent(path));
}

export function mutateView(path: string, view: string, action: string,
  payload: Record<string, unknown> = {}, revision?: string): Promise<BlockMutationResponse> {
  return request<BlockMutationResponse>('/api/blocks', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({path, view, action, ...payload,
      ...(revision === undefined ? {} : {revision})}),
  });
}

export function saveView(path: string, config: ViewConfig,
  revision?: string): Promise<SaveViewResponse> {
  return request<SaveViewResponse>('/api/views', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({path, config, ...(revision === undefined ? {} : {revision})}),
  });
}

export function deleteView(path: string, view: string,
  revision?: string, manifestRevision?: string | null): Promise<DeleteViewResponse> {
  const query = new URLSearchParams({path, view});
  if (revision !== undefined) query.set('revision', revision);
  if (manifestRevision) query.set('manifest_revision', manifestRevision);
  return request<DeleteViewResponse>('/api/views?' + query.toString(),
    {method: 'DELETE'});
}

export function createWorkspace(input: CreateWorkspaceInput): Promise<CreateWorkspaceResponse> {
  return request<CreateWorkspaceResponse>('/api/workspaces', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(input),
  });
}

export function fetchProject(path: string): Promise<ProjectSettingsResponse> {
  return request<ProjectSettingsResponse>('/api/project?path=' + encodeURIComponent(path));
}

export function saveProject(path: string, config: ProjectManifest,
  revision?: string): Promise<SaveProjectResponse> {
  return request<SaveProjectResponse>('/api/project', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({path, config, ...(revision === undefined ? {} : {revision})}),
  });
}

export function fetchRecentWorkspaces(): Promise<RecentWorkspacesResponse> {
  return request<RecentWorkspacesResponse>('/api/workspaces');
}

export function browseDirectory(path?: string): Promise<BrowseResponse> {
  const query = path ? '?path=' + encodeURIComponent(path) : '';
  return request<BrowseResponse>('/api/browse' + query);
}

export function openWorkspace(path: string): Promise<OpenWorkspaceResponse> {
  return request<OpenWorkspaceResponse>('/api/workspaces/open', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({path}),
  });
}

export function forgetWorkspace(path: string): Promise<ForgetWorkspaceResponse> {
  return request<ForgetWorkspaceResponse>(
    '/api/workspaces/recent?path=' + encodeURIComponent(path),
    {method: 'DELETE'});
}
