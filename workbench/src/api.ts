import type {
  AgentProposal,
  DecisionCase,
  GateReviewSnapshot,
  JsonValue,
  ProjectWorkspace,
  ReleaseCandidate,
  WorkspaceSnapshot,
} from "./types";

export interface DecisionCaseInput {
  case_id: string;
  name: string;
  objective: string;
  decision_owner: string;
  users: string[];
  trigger: string;
  inputs: string[];
  actions: string[];
  constraints?: string[];
  kpis?: string[];
  baseline: string;
  success_definition: string;
  failure_definition: string;
  status?: DecisionCase["status"];
}

export type ProposalDecision = "accept" | "reject" | "return";

export interface ReleaseCandidateInput {
  artifact_ids: string[];
  gate_run_ids: string[];
}

export interface ShipyardApi {
  listWorkspaces(): Promise<ProjectWorkspace[]>;
  getSnapshot(workspaceId: string): Promise<WorkspaceSnapshot>;
  createDecisionCase(
    workspaceId: string,
    input: DecisionCaseInput,
  ): Promise<DecisionCase>;
  decideProposal(
    proposalId: string,
    decision: ProposalDecision,
  ): Promise<AgentProposal>;
  /** Optional for older consumers; the concrete client calls the authenticated API. */
  createReleaseCandidate?: (
    workspaceId: string,
    input: ReleaseCandidateInput,
  ) => Promise<ReleaseCandidate>;
}

export interface ShipyardApiClientOptions {
  apiBaseUrl?: string;
  identity?: string;
}

export class ShipyardApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ShipyardApiError";
    this.status = status;
  }
}

const errorMessageFrom = (body: unknown, status: number): string => {
  if (typeof body === "object" && body !== null && "detail" in body) {
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.trim()) {
      return detail;
    }
  }
  return `Shipyard API request failed (${status})`;
};

export class ShipyardApiClient implements ShipyardApi {
  private readonly apiBaseUrl: string;

  private readonly identity: string;

  constructor(options: ShipyardApiClientOptions = {}) {
    this.apiBaseUrl = (
      options.apiBaseUrl ?? import.meta.env.VITE_SHIPYARD_API_URL ?? ""
    ).replace(/\/+$/, "");
    this.identity =
      options.identity ?? import.meta.env.VITE_SHIPYARD_IDENTITY ?? "";
  }

  async listWorkspaces(): Promise<ProjectWorkspace[]> {
    return this.request<ProjectWorkspace[]>("/workspaces");
  }

  async getSnapshot(workspaceId: string): Promise<WorkspaceSnapshot> {
    return this.request<WorkspaceSnapshot>(
      `/workspaces/${encodeURIComponent(workspaceId)}/snapshot`,
    );
  }

  async createDecisionCase(
    workspaceId: string,
    input: DecisionCaseInput,
  ): Promise<DecisionCase> {
    return this.request<DecisionCase>(
      `/workspaces/${encodeURIComponent(workspaceId)}/decision-cases`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    );
  }

  async decideProposal(
    proposalId: string,
    decision: ProposalDecision,
  ): Promise<AgentProposal> {
    return this.request<AgentProposal>(
      `/proposals/${encodeURIComponent(proposalId)}/decision`,
      {
        method: "POST",
        body: JSON.stringify({ decision }),
      },
    );
  }

  async createReleaseCandidate(
    workspaceId: string,
    input: ReleaseCandidateInput,
  ): Promise<ReleaseCandidate> {
    return this.request<ReleaseCandidate>(
      `/workspaces/${encodeURIComponent(workspaceId)}/release-candidates`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    );
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    if (!this.identity.trim()) {
      throw new Error("Shipyard runtime identity is required");
    }

    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    headers.set("Content-Type", "application/json");
    headers.set("X-Shipyard-Identity", this.identity);

    const response = await fetch(`${this.apiBaseUrl}${path}`, {
      ...init,
      headers,
    });
    const body = (await response.json().catch(() => null)) as JsonValue;

    if (!response.ok) {
      throw new ShipyardApiError(
        response.status,
        errorMessageFrom(body, response.status),
      );
    }

    return body as T;
  }
}
