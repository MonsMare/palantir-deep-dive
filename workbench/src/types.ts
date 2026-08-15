export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

export interface ProjectWorkspace {
  workspace_id: string;
  project_id: string;
  name: string;
  domain_pack: string;
  owner: string;
  status: "draft" | "active" | "archived";
  current_phase: string;
  revision: number;
  decision_case_ids: string[];
  artifact_ids: string[];
  proposal_ids: string[];
  gate_review_ids: string[];
  release_candidate_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface DecisionCase {
  case_id: string;
  workspace_id: string;
  name: string;
  objective: string;
  decision_owner: string;
  users: string[];
  trigger: string;
  inputs: string[];
  actions: string[];
  constraints: string[];
  kpis: string[];
  baseline: string;
  success_definition: string;
  failure_definition: string;
  status: "draft" | "active" | "completed" | "archived";
}

export interface Artifact {
  artifact_id: string;
  project_id: string;
  kind: string;
  version: string;
  status: string;
  owner: string;
  content: JsonValue;
  depends_on: string[];
  evidence_refs: string[];
  metadata: Record<string, unknown>;
  parent_artifact_ids: string[];
  producer: string | null;
  created_at: string;
  validation_results: JsonValue[];
  content_hash: string;
}

export interface AgentProposal {
  proposal_id: string;
  revision: number;
  workspace_id: string;
  task_packet_id: string;
  producer: string;
  producer_kind: "agent";
  proposed_changes: Record<string, JsonValue>;
  affected_artifact_ids: string[];
  evidence_refs: string[];
  validation_results: JsonValue[];
  confidence: number;
  risks: string[];
  open_questions: string[];
  next_step: string;
  base_revision: number;
  status: "proposed" | "accepted" | "rejected" | "returned" | "stale";
  created_at: string;
  content_hash: string;
}

export interface GateReviewSnapshot {
  gate_run_id: string;
  revision: number;
  workspace_id: string;
  gate_id: string;
  severity: "hard" | "soft";
  status: "pending" | "passed" | "failed" | "blocked";
  artifact_hashes: Record<string, string>;
  validator_version: string;
  violations: string[];
  warnings: string[];
  evidence_refs: string[];
  stale: boolean;
  created_at: string;
  content_hash: string;
}

export interface ReleaseCandidate {
  candidate_id: string;
  revision: number;
  workspace_id: string;
  artifact_ids: string[];
  gate_run_ids: string[];
  manifest: Record<string, JsonValue>;
  status: "draft" | "ready" | "blocked" | "released";
  created_at: string;
  created_by: string;
  content_hash: string;
}

export interface AuditEvent {
  event_id: string;
  workspace_id: string;
  event_type: string;
  actor: string;
  actor_kind: "human" | "agent" | "system";
  payload: JsonValue;
  created_at: string;
  predecessor_hash: string;
  event_hash: string;
}

export interface WorkspaceSnapshot {
  workspace: ProjectWorkspace;
  decision_cases: DecisionCase[];
  artifacts: Artifact[];
  proposals: AgentProposal[];
  gate_reviews: GateReviewSnapshot[];
  release_candidates: ReleaseCandidate[];
  audit_events: AuditEvent[];
}
