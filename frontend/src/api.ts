// The only place that talks to NASQuay's API.
//
// The access token is held in memory, never in storage: the refresh token lives in an
// HTTP-only cookie, so a reload restores the session by asking /api/auth/refresh.

export type Session = {
  access_token: string;
  token_type: string;
  expires_in: number;
  username: string;
  role: string;
  is_admin: boolean;
};

export type User = {
  id: number;
  username: string;
  display_name: string;
  email: string;
  role_id: number;
  role_name: string;
  is_admin: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string | null;
  last_login: string | null;
};

export type Role = {
  id: number;
  name: string;
  description: string;
  is_builtin: boolean;
  is_admin: boolean;
  user_count: number;
  permissions: string[];
  created_at: string;
  updated_at: string | null;
};

export type Action = {
  id: string;
  source: string;
  category: string;
  classification: string;
  description: string;
  long_running: boolean;
  reviewed: boolean;
};

export type AuditRecord = {
  id: number;
  at: string;
  actor_kind: string;
  actor_name: string;
  via: string;
  action_id: string;
  target: string;
  decision: string;
  reason: string;
  outcome: string | null;
  detail: string;
  duration_ms: number | null;
  client_ip: string;
};

export type AuditPage = { records: AuditRecord[]; next_before_id: number | null };

export type Nas = {
  id: number;
  name: string;
  address: string;
  mcp_port: number;
  tls_mode: string;
  tls_fingerprint: string;
  tls_cert_id: number | null;
  tls_cert_name: string | null;
  has_token: boolean;
  ssh_user: string;
  ssh_port: number;
  admin_url: string;
  enabled: boolean;
  last_checked_at: string | null;
  last_check_ok: boolean | null;
  last_check_detail: string;
  created_at: string;
  updated_at: string | null;
};

export type NasCheck = {
  mcp_ok: boolean;
  mcp_detail: string;
  tool_count: number | null;
  server: string;
  ssh_ok: boolean | null;
  ssh_detail: string;
};

export type Tool = {
  action_id: string;
  tool_name: string;
  category: string;
  classification: string;
  description: string;
  reviewed: boolean;
  nas: string[];
};

export type Discovery = { nas: string; found: number; added: number; unreviewed: number };

export type RunResult = {
  tool: string;
  nas: string;
  classification: string;
  text: string;
  json_result: unknown;
  // Entries an administrator's visibility settings kept out of this listing.
  hidden: number;
};

export type HiddenItem = {
  id: number;
  kind: "share" | "path";
  value: string;
  added_at: string;
};

export type Target = {
  id: number;
  nas_id: number;
  nas: string;
  kind: string;
  ref: string;
  label: string;
  parent_ref: string;
  enabled: boolean;
  client_id: number | null;
  first_seen: string;
  last_seen: string;
  last_reading_at: string | null;
};

export type Reading = {
  taken_at: string;
  target_id: number;
  metric: string;
  value: number | null;
  source: string;
  rounded: boolean;
  cached: boolean;
  backfilled: boolean;
};

export type Run = {
  id: number;
  tier: string;
  status: string;
  readings: number;
  detail: string;
  started_at: string;
  finished_at: string | null;
};

export type Flag = {
  id: number;
  raised_at: string;
  rule: string;
  target_id: number | null;
  nas_id: number | null;
  severity: string;
  detail: string;
  value: number | null;
  previous: number | null;
  cleared_at: string | null;
  acknowledged_at: string | null;
  acknowledged_by: string;
};

export type Client = {
  id: number;
  name: string;
  address: string;
  ssh_user: string;
  ssh_port: number;
  enabled: boolean;
  last_checked_at: string | null;
  last_check_ok: boolean | null;
  last_check_detail: string;
  key_name: string;
  mounts: number;
};

export type Key = {
  name: string;
  public: string;
  fingerprint: string;
  comment: string;
  created_at: string;
  public_path: string;
  managed: boolean;
  in_use: number;
};

export type Certificate = {
  id: number;
  name: string;
  pem: string;
  fingerprint: string;
  subject: string;
  issuer: string;
  not_before: string;
  not_after: string;
  is_ca: boolean;
  added_at: string;
  in_use: number;
};

export type Notifications = {
  on_error: boolean;
  on_warning: boolean;
  on_cleared: boolean;
  email_enabled: boolean;
  smtp_host: string;
  smtp_port: number;
  smtp_security: string;
  smtp_user: string;
  mail_from: string;
  mail_to: string;
  ntfy_enabled: boolean;
  ntfy_server: string;
  ntfy_topic: string;
  slack_enabled: boolean;
  has_smtp_password: boolean;
  has_ntfy_token: boolean;
  has_slack_webhook: boolean;
  last_sent_at: string | null;
  last_result: string;
};

export type Provider = {
  id: number;
  name: string;
  kind: "openai" | "anthropic";
  base_url: string;
  model: string;
  timeout_s: number;
  supports_tools: boolean;
  enabled: boolean;
  tls_cert_id: number | null;
  tls_cert_name: string | null;
  has_api_key: boolean;
  last_tested_at: string | null;
  last_result: string;
  tools_ok: boolean | null;
};

export type RoutineStep = { op: string; nas: string; arguments: Record<string, unknown> };

export type Routine = {
  id: number;
  name: string;
  description: string;
  enabled: boolean;
  kind: "fixed" | "ai";
  run_as_user_id: number | null;
  run_as_username: string | null;
  schedule_kind: "manual" | "interval" | "daily" | "weekly";
  interval_minutes: number;
  at_time: string;
  weekday: number;
  provider_id: number | null;
  provider_name: string | null;
  prompt: string;
  steps: RoutineStep[];
  allowed: string[];
  allow_destructive: boolean;
  max_steps: number;
  timeout_s: number;
  alert_on: "never" | "failure" | "always";
  created_at: string;
  updated_at: string | null;
  last_status: string | null;
  last_queued_at: string | null;
  last_finished_at: string | null;
  last_error: string | null;
};

export type RoutineOperation = {
  id: string;
  description: string;
  classification: string;
  needs_nas: boolean;
  nas_names: string[];
  parameters: Record<string, unknown>;
};

export type RoutineRun = {
  id: number;
  trigger: string;
  status: string;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  output: string;
  error: string;
  calls: { op: string; nas: string; arguments: Record<string, unknown>; ok: boolean; detail: string; at: string }[];
  alert: string;
};

export type ApiToken = {
  id: number;
  user_id: number;
  username: string;
  name: string;
  prefix: string;
  access: "read" | "write";
  allow_destructive: boolean;
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
};

export type ResonanceConfig = {
  enabled: boolean;
  base_url: string;
  label: string;
  side: string;
};

export type ResonanceSettings = {
  enabled: boolean;
  base_url: string;
  label: string;
  side: string;
  ca_bundle: string;
  has_key: boolean;
  module_version: string;
  last_used_at: string | null;
  last_result: string;
  updated_at: string | null;
};

export type ResonanceSession = {
  code: string;
  src: string;
  base_url: string;
  code_expires_in: number | null;
  expires_in: number | null;
  parts: unknown;
  cap: unknown;
};

export type AddressChoice = { address: string; label: string };

export type Network = {
  host: string;
  port: number;
  running_host: string;
  running_port: number;
  restart_required: boolean;
  choices: AddressChoice[];
  config_file: string | null;
};

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let token: string | null = null;
export const setToken = (value: string | null) => {
  token = value;
};

type Options = { method?: string; body?: unknown; allowRetry?: boolean };

async function request<T>(path: string, options: Options = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (options.body !== undefined) headers["Content-Type"] = "application/json";

  const response = await fetch(path, {
    method: options.method ?? "GET",
    headers,
    credentials: "same-origin",
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });

  // An expired access token is renewed once, silently, from the refresh cookie.
  if (response.status === 401 && options.allowRetry !== false) {
    const session = await refresh();
    if (session) return request<T>(path, { ...options, allowRetry: false });
  }

  if (!response.ok) {
    let message = response.statusText;
    try {
      const body = await response.json();
      const detail = body?.detail;
      message =
        typeof detail === "string"
          ? detail
          : detail
            ? JSON.stringify(detail)
            : message;
    } catch {
      // no JSON body
    }
    throw new ApiError(response.status, message);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/**
 * A call the assistant asked for. Deliberately narrow, because the request arrives from
 * the frame and the frame is untrusted by definition: only GET, only the operations
 * surface, and never a path that climbs out of it. Everything else the session can reach
 * — the settings, /api/run, the audit log — is unreachable from here.
 */
export async function assistantCall(
  path: string,
): Promise<{ status: number; body: unknown }> {
  const url = new URL(path, window.location.origin);
  if (url.origin !== window.location.origin || !url.pathname.startsWith("/api/resonance/data/")) {
    return { status: 403, body: { error: "That is not an operation this page may perform" } };
  }
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const response = await fetch(url.pathname + url.search, {
    headers,
    credentials: "same-origin",
    cache: "no-store",
  });
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  return { status: response.status, body };
}

export async function refresh(): Promise<Session | null> {
  const response = await fetch("/api/auth/refresh", {
    method: "POST",
    credentials: "same-origin",
  });
  if (!response.ok) {
    token = null;
    return null;
  }
  const session = (await response.json()) as Session;
  token = session.access_token;
  return session;
}

export const api = {
  health: () => request<{ status: string; version: string; timezone: string }>("/api/health"),

  login: async (username: string, password: string) => {
    const session = await request<Session>("/api/auth/login", {
      method: "POST",
      body: { username, password },
      allowRetry: false,
    });
    token = session.access_token;
    return session;
  },
  logout: async () => {
    await request<void>("/api/auth/logout", { method: "POST", allowRetry: false });
    token = null;
  },

  me: () => request<User>("/api/users/me"),
  changeMyPassword: (current_password: string, new_password: string) =>
    request<void>("/api/users/me/password", {
      method: "POST",
      body: { current_password, new_password },
    }),

  users: {
    list: () => request<User[]>("/api/users"),
    create: (body: {
      username: string;
      display_name: string;
      email: string;
      password: string;
      role_id: number;
    }) => request<User>("/api/users", { method: "POST", body }),
    update: (
      id: number,
      body: Partial<{ display_name: string; email: string; role_id: number; is_active: boolean }>,
    ) => request<User>(`/api/users/${id}`, { method: "PATCH", body }),
    resetPassword: (id: number, new_password: string) =>
      request<void>(`/api/users/${id}/password`, { method: "POST", body: { new_password } }),
    remove: (id: number) => request<void>(`/api/users/${id}`, { method: "DELETE" }),
  },

  roles: {
    list: () => request<Role[]>("/api/roles"),
    actions: () => request<Action[]>("/api/roles/actions"),
    create: (body: { name: string; description: string }) =>
      request<Role>("/api/roles", { method: "POST", body }),
    update: (id: number, body: Partial<{ name: string; description: string }>) =>
      request<Role>(`/api/roles/${id}`, { method: "PATCH", body }),
    setPermissions: (id: number, allowed: string[]) =>
      request<Role>(`/api/roles/${id}/permissions`, { method: "PUT", body: { allowed } }),
    remove: (id: number) => request<void>(`/api/roles/${id}`, { method: "DELETE" }),
  },

  audit: (params: {
    limit?: number;
    before_id?: number | null;
    action_id?: string;
    decision?: string;
  }) => {
    const query = new URLSearchParams();
    if (params.limit) query.set("limit", String(params.limit));
    if (params.before_id) query.set("before_id", String(params.before_id));
    if (params.action_id) query.set("action_id", params.action_id);
    if (params.decision) query.set("decision", params.decision);
    return request<AuditPage>(`/api/audit?${query.toString()}`);
  },

  nas: {
    list: () => request<Nas[]>("/api/nas"),
    fingerprint: (address: string, port: number) =>
      request<{ address: string; port: number; fingerprint: string }>("/api/nas/fingerprint", {
        method: "POST",
        body: { address, port },
      }),
    create: (body: {
      name: string;
      address: string;
      mcp_port: number;
      tls_mode: string;
      tls_fingerprint: string;
      tls_cert_id: number | null;
      mcp_token: string;
      ssh_user: string;
      ssh_port: number;
      admin_url: string;
    }) => request<Nas>("/api/nas", { method: "POST", body }),
    update: (id: number, body: Record<string, unknown>) =>
      request<Nas>(`/api/nas/${id}`, { method: "PATCH", body }),
    remove: (id: number) => request<void>(`/api/nas/${id}`, { method: "DELETE" }),
    check: (id: number) => request<NasCheck>(`/api/nas/${id}/check`, { method: "POST" }),
    hidden: (id: number) => request<HiddenItem[]>(`/api/nas/${id}/hidden`),
    hide: (id: number, kind: "share" | "path", value: string) =>
      request<HiddenItem>(`/api/nas/${id}/hidden`, { method: "POST", body: { kind, value } }),
    show: (id: number, itemId: number) =>
      request<void>(`/api/nas/${id}/hidden/${itemId}`, { method: "DELETE" }),
  },

  // The one way a NAS tool is ever called: the server checks the role, the review state
  // and the classification before it contacts a NAS.
  run: (nasId: number, tool: string, args: Record<string, unknown> = {}, confirm = false) =>
    request<RunResult>("/api/run", {
      method: "POST",
      body: { nas_id: nasId, tool, arguments: args, confirm },
    }),

  monitoring: {
    targets: () => request<Target[]>("/api/monitoring/targets"),
    setTarget: (id: number, enabled: boolean) =>
      request<Target>(`/api/monitoring/targets/${id}`, { method: "PATCH", body: { enabled } }),
    discover: (nasId: number) =>
      request<{ nas: string; found: number; added: number; problems: string[] }>(
        `/api/monitoring/discover/${nasId}`,
        { method: "POST" },
      ),
    collect: (nasId: number, tier: string) =>
      request<{ nas: string; tier: string; readings: number; problems: string[] }>(
        "/api/monitoring/collect",
        { method: "POST", body: { nas_id: nasId, tier } },
      ),
    backfill: (nasId: number) =>
      request<{ nas: string; readings: number; windows: Record<string, number>; problems: string[] }>(
        `/api/monitoring/backfill/${nasId}`,
        { method: "POST" },
      ),
    readings: (options: { limit?: number; target_id?: number; metric?: string } = {}) => {
      const query = new URLSearchParams({ limit: String(options.limit ?? 500) });
      if (options.target_id !== undefined) query.set("target_id", String(options.target_id));
      if (options.metric) query.set("metric", options.metric);
      return request<Reading[]>(`/api/monitoring/readings?${query.toString()}`);
    },
    runs: (limit = 20) => request<Run[]>(`/api/monitoring/runs?limit=${limit}`),
    flags: (openOnly = true) =>
      request<Flag[]>(`/api/monitoring/flags?open_only=${openOnly}`),
    acknowledge: (id: number, clear: boolean) =>
      request<Flag>(`/api/monitoring/flags/${id}`, { method: "PATCH", body: { clear } }),
  },

  tools: {
    list: () => request<Tool[]>("/api/tools"),
    discover: (nasId: number) =>
      request<Discovery>(`/api/tools/discover/${nasId}`, { method: "POST" }),
    review: (actionId: string, body: { classification: string; reviewed: boolean }) =>
      request<Tool>(`/api/tools/${actionId}`, { method: "PATCH", body }),
  },

  system: {
    network: () => request<Network>("/api/system/network"),
    setNetwork: (host: string, port: number) =>
      request<Network>("/api/system/network", { method: "PATCH", body: { host, port } }),
    restart: () => request<{ status: string }>("/api/system/restart", { method: "POST" }),
  },

  keys: {
    list: () => request<Key[]>("/api/keys"),
    create: (body: { name: string; comment: string }) =>
      request<Key>("/api/keys", { method: "POST", body }),
    rename: (name: string, newName: string) =>
      request<Key>(`/api/keys/${encodeURIComponent(name)}`, {
        method: "PATCH",
        body: { new_name: newName },
      }),
    remove: (name: string) =>
      request<void>(`/api/keys/${encodeURIComponent(name)}`, { method: "DELETE" }),
  },

  resonance: {
    config: () => request<ResonanceConfig>("/api/resonance/config"),
    // Every mount and every renewal: one short-lived, single-use code, audited.
    code: () => request<ResonanceSession>("/api/resonance/code", { method: "POST" }),
    settings: () => request<ResonanceSettings>("/api/resonance/settings"),
    save: (body: Record<string, unknown>) =>
      request<ResonanceSettings>("/api/resonance/settings", { method: "PATCH", body }),
    test: () => request<ResonanceSession>("/api/resonance/test", { method: "POST" }),
  },

  certificates: {
    list: () => request<Certificate[]>("/api/certificates"),
    add: (body: { name: string; pem: string }) =>
      request<Certificate>("/api/certificates", { method: "POST", body }),
    remove: (id: number) => request<void>(`/api/certificates/${id}`, { method: "DELETE" }),
  },

  clients: {
    list: () => request<Client[]>("/api/clients"),
    create: (body: {
      name: string;
      address: string;
      ssh_user: string;
      ssh_port: number;
      key_name: string;
    }) =>
      request<Client>("/api/clients", { method: "POST", body }),
    update: (id: number, body: Record<string, unknown>) =>
      request<Client>(`/api/clients/${id}`, { method: "PATCH", body }),
    remove: (id: number) => request<void>(`/api/clients/${id}`, { method: "DELETE" }),
    check: (id: number) =>
      request<{ client: string; ok: boolean; detail: string }>(`/api/clients/${id}/check`, {
        method: "POST",
      }),
    discoverMounts: (id: number) =>
      request<{
        client: string;
        mounts: { source: string; path: string; type: string; watched: boolean }[];
      }>(`/api/clients/${id}/mounts/discover`, { method: "POST" }),
    removeMount: (targetId: number) =>
      request<void>(`/api/clients/mounts/${targetId}`, { method: "DELETE" }),
    addMount: (body: { client_id: number; nas_id: number; share: string; path: string }) =>
      request<{ client: string; path: string; share: string }>("/api/clients/mounts", {
        method: "POST",
        body,
      }),
  },

  providers: {
    list: () => request<Provider[]>("/api/providers"),
    create: (body: Record<string, unknown>) =>
      request<Provider>("/api/providers", { method: "POST", body }),
    update: (id: number, body: Record<string, unknown>) =>
      request<Provider>(`/api/providers/${id}`, { method: "PATCH", body }),
    remove: (id: number) => request<void>(`/api/providers/${id}`, { method: "DELETE" }),
    test: (id: number) =>
      request<{ ok: boolean; tools_ok: boolean | null; detail: string }>(
        `/api/providers/${id}/test`,
        { method: "POST" },
      ),
  },

  tokens: {
    list: () => request<ApiToken[]>("/api/tokens"),
    create: (body: {
      name: string;
      access: string;
      allow_destructive: boolean;
      expires_days: number;
    }) => request<ApiToken & { token: string }>("/api/tokens", { method: "POST", body }),
    revoke: (id: number) => request<void>(`/api/tokens/${id}`, { method: "DELETE" }),
  },

  routines: {
    list: () => request<Routine[]>("/api/routines"),
    operations: () => request<RoutineOperation[]>("/api/routines/operations"),
    create: (body: Record<string, unknown>) =>
      request<Routine>("/api/routines", { method: "POST", body }),
    update: (id: number, body: Record<string, unknown>) =>
      request<Routine>(`/api/routines/${id}`, { method: "PATCH", body }),
    remove: (id: number) => request<void>(`/api/routines/${id}`, { method: "DELETE" }),
    run: (id: number) =>
      request<{ run_id: number }>(`/api/routines/${id}/run`, { method: "POST" }),
    runs: (id: number) => request<RoutineRun[]>(`/api/routines/${id}/runs`),
  },

  notifications: {
    read: () => request<Notifications>("/api/notifications"),
    update: (body: Record<string, unknown>) =>
      request<Notifications>("/api/notifications", { method: "PATCH", body }),
    test: () =>
      request<{ ok: boolean; detail: string }>("/api/notifications/test", { method: "POST" }),
  },

  settings: {
    read: () => request<Record<string, unknown>>("/api/settings"),
    update: (body: Record<string, unknown>) =>
      request<Record<string, unknown>>("/api/settings", { method: "PATCH", body }),
  },
};
