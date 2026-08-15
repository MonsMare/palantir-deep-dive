import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { App } from "./App";
import type { ShipyardApi } from "./api";
import type {
  AgentProposal,
  Artifact,
  AuditEvent,
  DecisionCase,
  GateReviewSnapshot,
  ProjectWorkspace,
  ReleaseCandidate,
  WorkspaceSnapshot,
} from "./types";

const timestamp = "2026-08-15T08:00:00.000Z";
const hash = (character: string): string => character.repeat(64);

const workspace: ProjectWorkspace = {
  workspace_id: "ws-1",
  project_id: "project-1",
  name: "Delivery Control Room",
  domain_pack: "software_delivery",
  owner: "alice",
  status: "active",
  current_phase: "build",
  revision: 3,
  decision_case_ids: ["case-1"],
  artifact_ids: ["artifact-1"],
  proposal_ids: ["proposal-1"],
  gate_review_ids: ["gate-run-1"],
  release_candidate_ids: ["candidate-1"],
  created_at: timestamp,
  updated_at: timestamp,
};

const decisionCase: DecisionCase = {
  case_id: "case-1",
  workspace_id: "ws-1",
  name: "软件需求对齐与工期预测",
  objective: "让交付负责人基于已验证证据预测工期。",
  decision_owner: "alice",
  users: ["delivery-lead"],
  trigger: "需求评审完成",
  inputs: ["需求文档", "历史工期证据"],
  actions: ["确认范围", "生成工期预测"],
  constraints: ["必须保留证据引用"],
  kpis: ["预测偏差"],
  baseline: "当前依赖人工汇总",
  success_definition: "预测可追溯且能被 Gate Review 验证",
  failure_definition: "缺少证据或语义完整性校验失败",
  status: "active",
};

const artifact: Artifact = {
  artifact_id: "artifact-1",
  project_id: "project-1",
  kind: "delivery-spec",
  version: "1.2.0",
  status: "review",
  owner: "alice",
  content: { summary: "可审阅的交付规格" },
  depends_on: [],
  evidence_refs: ["evidence:req-1"],
  metadata: { source: "agent-proposal" },
  parent_artifact_ids: [],
  producer: "agent:shipyard",
  created_at: timestamp,
  validation_results: [],
  content_hash: hash("a"),
};

const proposal: AgentProposal = {
  proposal_id: "proposal-1",
  revision: 1,
  workspace_id: "ws-1",
  task_packet_id: "packet-1",
  producer: "agent:shipyard",
  producer_kind: "agent",
  proposed_changes: { artifact: "artifact-1" },
  affected_artifact_ids: ["artifact-1"],
  evidence_refs: ["evidence:req-1"],
  validation_results: [{ name: "schema", status: "passed" }],
  confidence: 0.82,
  risks: ["范围仍需人工确认"],
  open_questions: ["是否纳入外部依赖？"],
  next_step: "request human review",
  base_revision: 3,
  status: "proposed",
  created_at: timestamp,
  content_hash: hash("b"),
};

const blockedGate: GateReviewSnapshot = {
  gate_run_id: "gate-run-1",
  revision: 1,
  workspace_id: "ws-1",
  gate_id: "semantic.integrity",
  severity: "hard",
  status: "blocked",
  artifact_hashes: { "artifact-1": hash("a") },
  validator_version: "semantic-gate@1.4.0",
  violations: ["缺少一条依赖证据"],
  warnings: ["历史样本较少"],
  evidence_refs: ["evidence:req-1"],
  stale: false,
  created_at: timestamp,
  content_hash: hash("c"),
};

const releaseCandidate: ReleaseCandidate = {
  candidate_id: "candidate-1",
  revision: 1,
  workspace_id: "ws-1",
  artifact_ids: ["artifact-1"],
  gate_run_ids: ["gate-run-1"],
  manifest: {
    artifact_hashes: { "artifact-1": hash("a") },
    manifest_digest: hash("d"),
  },
  status: "blocked",
  created_at: timestamp,
  created_by: "alice",
  content_hash: hash("e"),
};

const auditEvent: AuditEvent = {
  event_id: "audit-1",
  workspace_id: "ws-1",
  event_type: "proposal.submitted",
  actor: "agent:shipyard",
  actor_kind: "agent",
  payload: { proposal_id: "proposal-1" },
  created_at: timestamp,
  predecessor_hash: hash("f"),
  event_hash: hash("0"),
};

const blockedSnapshot: WorkspaceSnapshot = {
  workspace,
  decision_cases: [decisionCase],
  artifacts: [artifact],
  proposals: [proposal],
  gate_reviews: [blockedGate],
  release_candidates: [releaseCandidate],
  audit_events: [auditEvent],
};

export const fakeApiWithBlockedGate = {
  listWorkspaces: () => Promise.resolve([workspace]),
  getSnapshot: () => Promise.resolve(blockedSnapshot),
  createDecisionCase: () => Promise.resolve(decisionCase),
  decideProposal: () => Promise.resolve(proposal),
  createReleaseCandidate: () => Promise.resolve(releaseCandidate),
} satisfies ShipyardApi;

export const fakeApiWithPassedGates: ShipyardApi = {
  ...fakeApiWithBlockedGate,
  getSnapshot: () =>
    Promise.resolve({
      ...blockedSnapshot,
      gate_reviews: [
        {
          ...blockedGate,
          status: "passed",
          violations: [],
          warnings: [],
        },
      ],
      release_candidates: [{ ...releaseCandidate, status: "ready" }],
    }),
};

afterEach(() => cleanup());

describe("Shipyard Workbench", () => {
  it("renders the workspace decision and blocks release when a gate is blocked", async () => {
    render(<App api={fakeApiWithBlockedGate} />);

    expect(await screen.findByText("软件需求对齐与工期预测")).toBeVisible();
    expect(screen.getByText("Release Candidate blocked")).toBeVisible();
    expect(screen.getAllByText("semantic.integrity")[0]).toBeVisible();
  });

  it("does not expose agent approval or production action controls", async () => {
    render(<App api={fakeApiWithBlockedGate} />);

    await screen.findByText("软件需求对齐与工期预测");

    expect(
      screen.queryByRole("button", { name: /approve|批准|审批|同意/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: /production action|生产 action|执行生产|生产操作/i,
      }),
    ).not.toBeInTheDocument();
  });

  it("shows release availability only after all required gates pass", async () => {
    render(<App api={fakeApiWithPassedGates} />);

    expect(await screen.findByText("All required gates passed")).toBeVisible();
    expect(screen.getByText("Release Candidate available")).toBeVisible();
    expect(
      screen.getByText("Available via authenticated API"),
    ).toBeVisible();
  });

  it("shows a user-visible state when the Workbench API fails", async () => {
    const failingApi: ShipyardApi = {
      ...fakeApiWithBlockedGate,
      listWorkspaces: () => Promise.reject(new Error("API unavailable")),
    };

    render(<App api={failingApi} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Unable to load Workbench",
    );
  });

  it("shows a user-visible state when the workspace snapshot API fails", async () => {
    const failingApi: ShipyardApi = {
      ...fakeApiWithBlockedGate,
      getSnapshot: () => Promise.reject(new Error("Snapshot unavailable")),
    };

    render(<App api={failingApi} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Unable to load workspace snapshot",
    );
  });
});
