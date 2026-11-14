/** Shared API/config types for the base-block reader and editor. */

export type CodeMapping = {file: string; lines: (number | string)[]};
export type EventTarget = {id: number; view?: string};
export type BranchList = {condition?: string; role?: 'body' | 'except'; steps: RBlock[]};
export type ViewKind = 'main' | 'flow' | 'entry' | 'contract' | 'function'
  | 'struct' | 'toolbox';

export type ContractField = {
  name: string;
  type: string;
  required?: boolean;
  values?: string[];
  description?: string;
};
export type ContractType = {kind: 'type'; fields: ContractField[]};
export type ContractError = {status: number; when: string};
export type ContractEndpoint = {
  kind: 'endpoint';
  method: string;
  path: string;
  auth?: boolean;
  request?: string;
  response?: string;
  status?: number;
  errors?: ContractError[];
  handler?: EventTarget;
  external?: boolean;
};
export type ContractPayload = ContractType | ContractEndpoint;

export type RBlock = {
  id: number;
  type: 'normal' | 'branch';
  kind?: 'try';
  name: string;
  description: string;
  code_mapping?: CodeMapping;
  next?: number | null;
  jump?: EventTarget;
  flow?: EventTarget;
  emit?: EventTarget[];
  on?: string;
  select?: 'single' | 'multi';
  branches?: BranchList[];
  finally?: RBlock[];
  contract?: ContractPayload;
  evidence?: EventTarget[];
};

export type CodeRange = {start: number; end: number; lines: {number: number; text: string}[]};
export type ProjectMeta = {name?: string; description?: string; root?: string; files?: string[]};
export type ProjectManifest = {
  project: {name: string; description: string; root: string};
  files: string[];
  views: {suffix?: string; entry?: string | null};
  [key: string]: unknown;
};
export type ViewMeta = {
  view_id: string;
  name: string;
  description: string;
  kind: ViewKind;
  file: string;
  entry?: boolean;
  revision?: string;
};
export type ViewsIndex = {
  source: {kind: 'default' | 'file' | 'project'; path?: string};
  project?: ProjectMeta;
  entry: string;
  manifest_revision?: string | null;
  views: ViewMeta[];
};
export type ViewInfo = {id: string; name: string; description: string; kind?: ViewKind};
export type ViewConfig = {view: ViewInfo; blocks: RBlock[]};

export type FlatContainer = {
  id: string;
  kind: 'root' | 'branch' | 'finally';
  parent?: number;
  condition?: string;
  role?: 'body' | 'except';
  blocks: number[];
};
export type FlatBlock = Omit<RBlock, 'branches' | 'finally'> & {
  branches?: string[];
  finally?: string;
};
export type FlatViewConfig = {
  view: ViewInfo;
  containers: FlatContainer[];
  blocks: FlatBlock[];
};
export type BlocksResponse = {
  config: ViewConfig;
  project?: ProjectMeta;
  source: {kind: 'default' | 'file' | 'project'; path?: string};
  view?: {view_id: string; file: string; name?: string; description?: string};
  order: number[];
  codes: Record<string, {file: string; ranges: CodeRange[]}>;
  schema?: 'flat' | 'nested';
  flat?: FlatViewConfig | null;
  revision?: string;
  manifest_revision?: string | null;
};

export type BlockMutationResponse = {
  payload: BlocksResponse;
  index: ViewsIndex;
  warnings: string[];
  result: {block_id?: number; container_id?: string};
  revision?: string;
  manifest_revision?: string | null;
};

export type SaveViewResponse = {
  payload: BlocksResponse;
  index: ViewsIndex;
  warnings: string[];
  created: boolean;
  revision?: string;
  manifest_revision?: string | null;
};
export type DeleteViewResponse = {
  index: ViewsIndex;
  entry: string;
  manifest_revision?: string | null;
};
export type CreateWorkspaceResponse = {index: ViewsIndex; payload: BlocksResponse};

export type ProjectSettingsResponse = {
  manifest: ProjectManifest;
  revision: string;
  index: ViewsIndex;
};
export type SaveProjectResponse = {
  manifest: ProjectManifest;
  index: ViewsIndex;
  revision: string;
  manifest_revision?: string | null;
};

export type RecentWorkspace = {
  path: string;
  name: string;
  description: string;
  opened_at?: string | null;
  exists: boolean;
};
export type ExampleWorkspace = {
  path: string;
  name: string;
  description: string;
  views: number;
  entry: string;
};
export type RecentWorkspacesResponse = {
  recent: RecentWorkspace[];
  examples: ExampleWorkspace[];
};
export type BrowseEntry = {name: string; path: string; is_workspace: boolean};
export type BrowseShortcut = {name: string; path: string};
export type BrowseResponse = {
  path: string;
  parent: string | null;
  is_workspace: boolean;
  entries: BrowseEntry[];
  truncated: boolean;
  shortcuts: BrowseShortcut[];
};
export type OpenWorkspaceResponse = {index: ViewsIndex; manifest: ProjectManifest};
export type DeleteWorkspaceResponse = {deleted: string; recent: RecentWorkspace[]};
export type ForgetWorkspaceResponse = {recent: RecentWorkspace[]};
export type CreateWorkspaceInput = {
  directory: string;
  name: string;
  description: string;
  view_id?: string;
  view_name?: string;
  view_description?: string;
};
