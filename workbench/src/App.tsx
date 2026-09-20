import { useEffect, useMemo, useState } from "react";
import {
  QueryClient,
  QueryClientProvider,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import type {
  DecisionCaseInput,
  ProposalDecision,
  ReleaseCandidateInput,
  ShipyardApi,
} from "./api";
import type {
  AgentProposal,
  Artifact,
  DecisionCase,
  GateReviewSnapshot,
  ProjectWorkspace,
  ReleaseCandidate,
  WorkspaceSnapshot,
} from "./types";

export interface AppProps {
  api: ShipyardApi;
}

const snapshotQueryKey = (workspaceId: string) =>
  ["shipyard", "workspace", workspaceId, "snapshot"] as const;

const errorMessage = (error: unknown): string =>
  error instanceof Error ? error.message : "Unknown API error";

const DEFAULT_SOFTWARE_DELIVERY_REQUIRED_GATES = [
  "semantic.integrity",
  "release.governance",
] as const;

const configuredRequiredGateIds = (): string[] =>
  (import.meta.env.VITE_SHIPYARD_REQUIRED_GATES ?? "")
    .split(",")
    .map((gateId: string) => gateId.trim())
    .filter(Boolean);

export function requiredGateIdsForWorkspace(workspace: ProjectWorkspace): string[] {
  const configured = configuredRequiredGateIds();
  if (configured.length > 0) {
    return [...new Set(configured)];
  }
  if (workspace.domain_pack === "software_delivery") {
    return [...DEFAULT_SOFTWARE_DELIVERY_REQUIRED_GATES];
  }
  return [];
}

const formatDate = (value: string): string => {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
};

const statusTone = (
  value: string,
): "neutral" | "success" | "danger" | "warning" | "stale" => {
  if (value === "passed" || value === "ready" || value === "active") {
    return "success";
  }
  if (value === "blocked" || value === "failed" || value === "rejected") {
    return "danger";
  }
  if (value === "pending" || value === "proposed" || value === "draft") {
    return "warning";
  }
  if (value === "stale") {
    return "stale";
  }
  return "neutral";
};

function StatusBadge({ label, tone }: { label: string; tone?: string }) {
  const resolvedTone = tone ?? statusTone(label);
  return (
    <span className={`status-badge status-${resolvedTone}`}>
      <span aria-hidden="true" className="status-dot" />
      {label}
    </span>
  );
}

function HashValue({ value }: { value: string }) {
  return (
    <code className="hash-value" title={value} aria-label={`SHA-256 ${value}`}>
      {value}
    </code>
  );
}

interface IndexedGateReview {
  review: GateReviewSnapshot;
  index: number;
}

export interface ReleaseBlocker {
  gateId: string | null;
  reason: string;
}

export interface ReleaseReadiness {
  available: boolean;
  requiredGateIds: string[];
  currentGateReviews: GateReviewSnapshot[];
  currentRequiredGates: GateReviewSnapshot[];
  currentArtifactIds: string[];
  currentGateRunIds: string[];
  blockingReasons: ReleaseBlocker[];
}

function isNewerGateReview(candidate: IndexedGateReview, current: IndexedGateReview): boolean {
  if (candidate.review.revision !== current.review.revision) {
    return candidate.review.revision > current.review.revision;
  }

  const candidateTime = Date.parse(candidate.review.created_at);
  const currentTime = Date.parse(current.review.created_at);
  if (Number.isFinite(candidateTime) && Number.isFinite(currentTime) && candidateTime !== currentTime) {
    return candidateTime > currentTime;
  }
  if (candidate.review.created_at !== current.review.created_at) {
    return candidate.review.created_at > current.review.created_at;
  }
  return candidate.index > current.index;
}

function latestGateReviews(reviews: GateReviewSnapshot[]): GateReviewSnapshot[] {
  const latestByGate = new Map<string, IndexedGateReview>();
  reviews.forEach((review, index) => {
    const candidate = { review, index };
    const current = latestByGate.get(review.gate_id);
    if (!current || isNewerGateReview(candidate, current)) {
      latestByGate.set(review.gate_id, candidate);
    }
  });
  return [...latestByGate.values()]
    .sort((left, right) => left.review.gate_id.localeCompare(right.review.gate_id))
    .map(({ review }) => review);
}

function hashesMatch(
  actual: Record<string, string>,
  expected: Record<string, string>,
): boolean {
  const actualIds = Object.keys(actual).sort();
  const expectedIds = Object.keys(expected).sort();
  return (
    actualIds.length === expectedIds.length &&
    actualIds.every(
      (artifactId, index) =>
        artifactId === expectedIds[index] && actual[artifactId] === expected[artifactId],
    )
  );
}

export function evaluateReleaseReadiness(
  snapshot: WorkspaceSnapshot,
  requiredGateIds: string[],
): ReleaseReadiness {
  const normalizedRequiredGateIds = [...new Set(
    requiredGateIds.map((gateId) => gateId.trim()).filter(Boolean),
  )];
  const currentGateReviews = latestGateReviews(snapshot.gate_reviews);
  const currentByGateId = new Map(
    currentGateReviews.map((review) => [review.gate_id, review]),
  );
  const currentArtifactIds = snapshot.artifacts.map((artifact) => artifact.artifact_id);
  const expectedArtifactHashes = Object.fromEntries(
    snapshot.artifacts.map((artifact) => [artifact.artifact_id, artifact.content_hash]),
  );
  const blockingReasons: ReleaseBlocker[] = [];

  if (normalizedRequiredGateIds.length === 0) {
    blockingReasons.push({
      gateId: null,
      reason: "No required Gate Review policy is configured",
    });
  }
  if (currentArtifactIds.length === 0) {
    blockingReasons.push({
      gateId: null,
      reason: "No current Artifact is available",
    });
  }

  const currentRequiredGates: GateReviewSnapshot[] = [];
  for (const requiredGateId of normalizedRequiredGateIds) {
    const review = currentByGateId.get(requiredGateId);
    if (!review) {
      blockingReasons.push({
        gateId: requiredGateId,
        reason: "missing required gate",
      });
      continue;
    }

    currentRequiredGates.push(review);
    if (review.status !== "passed") {
      blockingReasons.push({
        gateId: requiredGateId,
        reason: review.status,
      });
    }
    if (review.stale) {
      blockingReasons.push({
        gateId: requiredGateId,
        reason: "stale",
      });
    }
    if (!hashesMatch(review.artifact_hashes, expectedArtifactHashes)) {
      blockingReasons.push({
        gateId: requiredGateId,
        reason: "Gate Review artifact hashes do not match current Artifacts",
      });
    }
  }

  return {
    available: blockingReasons.length === 0,
    requiredGateIds: normalizedRequiredGateIds,
    currentGateReviews,
    currentRequiredGates,
    currentArtifactIds,
    currentGateRunIds: currentRequiredGates.map((review) => review.gate_run_id),
    blockingReasons,
  };
}

function StringList({ values, empty = "—" }: { values: string[]; empty?: string }) {
  if (values.length === 0) {
    return <span className="muted">{empty}</span>;
  }
  return (
    <ul className="inline-list">
      {values.map((value) => (
        <li key={value}>{value}</li>
      ))}
    </ul>
  );
}

function Panel({
  eyebrow,
  title,
  count,
  children,
  className = "",
}: {
  eyebrow?: string;
  title: string;
  count?: number;
  children: React.ReactNode;
  className?: string;
}) {
  const titleId = `panel-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  return (
    <section className={`panel ${className}`} aria-labelledby={titleId}>
      <div className="panel-heading">
        <div>
          {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
          <h2 id={titleId}>{title}</h2>
        </div>
        {typeof count === "number" ? (
          <span className="panel-count">{count}</span>
        ) : null}
      </div>
      {children}
    </section>
  );
}

function StatusPanel({
  title,
  detail,
  tone = "neutral",
}: {
  title: string;
  detail?: string;
  tone?: "neutral" | "danger";
}) {
  return (
    <main className="status-screen">
      <section
        className={`status-panel status-panel-${tone}`}
        role={tone === "danger" ? "alert" : "status"}
        aria-live="polite"
      >
        <p className="eyebrow">Shipyard Workbench</p>
        <h1>{title}</h1>
        {detail ? <p>{detail}</p> : null}
      </section>
    </main>
  );
}

interface MutationScope {
  workspaceId: string;
}

interface CreateDecisionCaseVariables extends MutationScope {
  input: DecisionCaseInput;
}

interface DecideProposalVariables extends MutationScope {
  proposalId: string;
  decision: ProposalDecision;
}

interface CreateReleaseCandidateVariables extends MutationScope {
  input: ReleaseCandidateInput;
}

function useWorkbenchMutations(api: ShipyardApi) {
  const queryClient = useQueryClient();
  const invalidateSnapshot = async (workspaceId: string) => {
    await queryClient.invalidateQueries({
      queryKey: snapshotQueryKey(workspaceId),
      exact: true,
    });
  };

  const createDecisionCase = useMutation({
    mutationFn: ({ workspaceId, input }: CreateDecisionCaseVariables) =>
      api.createDecisionCase(workspaceId, input),
    onSuccess: async (_case, variables) => {
      await invalidateSnapshot(variables.workspaceId);
    },
  });

  const decideProposal = useMutation({
    mutationFn: ({ proposalId, decision }: DecideProposalVariables) =>
      api.decideProposal(proposalId, decision),
    onSuccess: async (_proposal, variables) => {
      await invalidateSnapshot(variables.workspaceId);
    },
  });

  const createReleaseCandidate = useMutation({
    mutationFn: ({ workspaceId, input }: CreateReleaseCandidateVariables) => {
      if (!api.createReleaseCandidate) {
        throw new Error("Release Candidate API is not configured");
      }
      return api.createReleaseCandidate(workspaceId, input);
    },
    onSuccess: async (_candidate, variables) => {
      await invalidateSnapshot(variables.workspaceId);
    },
  });

  return { createDecisionCase, decideProposal, createReleaseCandidate };
}

function WorkbenchScreen({ api }: AppProps) {
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string>();
  const workspacesQuery = useQuery({
    queryKey: ["shipyard", "workspaces"],
    queryFn: () => api.listWorkspaces(),
    retry: false,
    refetchOnWindowFocus: false,
  });
  const workspaces = workspacesQuery.data ?? [];

  useEffect(() => {
    if (workspaces.length === 0) {
      return;
    }
    if (
      !selectedWorkspaceId ||
      !workspaces.some((workspace) => workspace.workspace_id === selectedWorkspaceId)
    ) {
      setSelectedWorkspaceId(workspaces[0].workspace_id);
    }
  }, [selectedWorkspaceId, workspaces]);

  const activeWorkspaceId =
    selectedWorkspaceId ?? workspaces[0]?.workspace_id ?? "";
  const snapshotQuery = useQuery({
    queryKey: snapshotQueryKey(activeWorkspaceId),
    queryFn: () => api.getSnapshot(activeWorkspaceId),
    enabled: Boolean(activeWorkspaceId),
    retry: false,
    refetchOnWindowFocus: false,
  });
  const mutations = useWorkbenchMutations(api);
  const readiness = useMemo(() => {
    if (!snapshotQuery.data) {
      return null;
    }
    return evaluateReleaseReadiness(
      snapshotQuery.data,
      requiredGateIdsForWorkspace(snapshotQuery.data.workspace),
    );
  }, [snapshotQuery.data]);

  if (workspacesQuery.isPending) {
    return <StatusPanel title="Loading Workbench" detail="Loading workspace catalog…" />;
  }
  if (workspacesQuery.isError) {
    return (
      <StatusPanel
        title="Unable to load Workbench"
        detail={errorMessage(workspacesQuery.error)}
        tone="danger"
      />
    );
  }
  if (workspaces.length === 0) {
    return (
      <StatusPanel
        title="No workspaces available"
        detail="The authenticated Workbench API returned an empty workspace catalog."
      />
    );
  }
  if (snapshotQuery.isError) {
    return (
      <StatusPanel
        title="Unable to load workspace snapshot"
        detail={errorMessage(snapshotQuery.error)}
        tone="danger"
      />
    );
  }
  if (snapshotQuery.isPending || !snapshotQuery.data || !readiness) {
    return <StatusPanel title="Loading workspace snapshot" detail="Syncing review state…" />;
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">
            ◈
          </span>
          <div>
            <p className="brand-name">Shipyard</p>
            <p className="brand-subtitle">Workbench / review control plane</p>
          </div>
        </div>
        <div className="topbar-meta">
          <span className="mode-chip">REVIEW-FIRST</span>
          <span className="identity-chip">Authenticated API boundary</span>
        </div>
      </header>

      <div className="workbench-grid">
        <WorkspaceSidebar
          workspaces={workspaces}
          activeWorkspaceId={activeWorkspaceId}
          onSelect={setSelectedWorkspaceId}
          snapshot={snapshotQuery.data}
        />
        <main className="review-column">
          <WorkspaceHeader workspace={snapshotQuery.data.workspace} />
          <DecisionCasePanel cases={snapshotQuery.data.decision_cases} />
          <ArtifactPanel artifacts={snapshotQuery.data.artifacts} />
          <ProposalPanel proposals={snapshotQuery.data.proposals} />
          <GatePanel gates={readiness.currentGateReviews} />
        </main>
        <aside className="detail-column" aria-label="Release and audit details">
          <ReleaseCandidatePanel
            snapshot={snapshotQuery.data}
            api={api}
            mutation={mutations.createReleaseCandidate}
            readiness={readiness}
          />
          <AuditPanel events={snapshotQuery.data.audit_events} />
          <div className="guardrail-note">
            <span className="guardrail-icon" aria-hidden="true">
              ⛨
            </span>
            <div>
              <strong>Human control required</strong>
              <p>Agent proposals remain reviewable records. No approval or production action is exposed here.</p>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

function WorkspaceSidebar({
  workspaces,
  activeWorkspaceId,
  onSelect,
  snapshot,
}: {
  workspaces: ProjectWorkspace[];
  activeWorkspaceId: string;
  onSelect: (workspaceId: string) => void;
  snapshot: WorkspaceSnapshot;
}) {
  return (
    <aside className="workspace-sidebar" aria-label="Workspace navigation">
      <nav>
        <div className="sidebar-section-heading">
          <p className="eyebrow">Project Home</p>
          <span className="sidebar-count">{workspaces.length}</span>
        </div>
        <div className="workspace-list">
          {workspaces.map((workspace) => {
            const isActive = workspace.workspace_id === activeWorkspaceId;
            return (
              <button
                className={`workspace-nav-item ${isActive ? "is-active" : ""}`}
                key={workspace.workspace_id}
                type="button"
                aria-current={isActive ? "page" : undefined}
                onClick={() => onSelect(workspace.workspace_id)}
              >
                <span className="workspace-nav-name">{workspace.name}</span>
                <span className="workspace-nav-meta">
                  <span>{workspace.current_phase}</span>
                  <span>rev {workspace.revision}</span>
                </span>
              </button>
            );
          })}
        </div>
      </nav>

      <div className="sidebar-footer">
        <p className="eyebrow">Selected workspace</p>
        <p className="sidebar-project-name">{snapshot.workspace.project_id}</p>
        <dl className="sidebar-facts">
          <div>
            <dt>Owner</dt>
            <dd>{snapshot.workspace.owner}</dd>
          </div>
          <div>
            <dt>Domain pack</dt>
            <dd>{snapshot.workspace.domain_pack}</dd>
          </div>
        </dl>
      </div>
    </aside>
  );
}

function WorkspaceHeader({ workspace }: { workspace: ProjectWorkspace }) {
  return (
    <section className="workspace-header" aria-labelledby="workspace-title">
      <div>
        <p className="eyebrow">Workspace / {workspace.workspace_id}</p>
        <h1 id="workspace-title">{workspace.name}</h1>
        <p className="workspace-description">
          Review current evidence, gate decisions, and release readiness before any downstream action.
        </p>
      </div>
      <div className="workspace-header-facts">
        <div>
          <span className="fact-label">Phase</span>
          <strong>{workspace.current_phase}</strong>
        </div>
        <div>
          <span className="fact-label">Revision</span>
          <strong>r{workspace.revision}</strong>
        </div>
        <div>
          <span className="fact-label">Workspace status</span>
          <StatusBadge label={workspace.status} />
        </div>
      </div>
    </section>
  );
}

function DecisionCasePanel({ cases }: { cases: DecisionCase[] }) {
  const decisionCase = cases[0];
  return (
    <Panel eyebrow="Decision Case" title="Decision Case summary" count={cases.length}>
      {decisionCase ? (
        <div className="decision-case-layout">
          <div>
            <div className="card-title-row">
              <h3>{decisionCase.name}</h3>
              <StatusBadge label={decisionCase.status} />
            </div>
            <p className="lead-copy">{decisionCase.objective}</p>
            <dl className="detail-grid">
              <div>
                <dt>Decision owner</dt>
                <dd>{decisionCase.decision_owner}</dd>
              </div>
              <div>
                <dt>Trigger</dt>
                <dd>{decisionCase.trigger}</dd>
              </div>
              <div>
                <dt>Baseline</dt>
                <dd>{decisionCase.baseline}</dd>
              </div>
              <div>
                <dt>Users</dt>
                <dd><StringList values={decisionCase.users} /></dd>
              </div>
            </dl>
          </div>
          <div className="decision-definition-stack">
            <div>
              <span className="fact-label">Inputs</span>
              <StringList values={decisionCase.inputs} />
            </div>
            <div>
              <span className="fact-label">Actions in scope</span>
              <StringList values={decisionCase.actions} />
            </div>
            <div>
              <span className="fact-label">Success definition</span>
              <p>{decisionCase.success_definition}</p>
            </div>
          </div>
        </div>
      ) : (
        <EmptyInline text="No Decision Case has been registered for this workspace." />
      )}
    </Panel>
  );
}

function ArtifactPanel({ artifacts }: { artifacts: Artifact[] }) {
  return (
    <Panel eyebrow="Evidence surface" title="Artifact Review" count={artifacts.length}>
      {artifacts.length > 0 ? (
        <div className="artifact-list">
          {artifacts.map((artifact) => (
            <article className="artifact-card" key={artifact.artifact_id}>
              <div className="card-title-row">
                <div>
                  <p className="card-kicker">{artifact.kind}</p>
                  <h3>{artifact.artifact_id}</h3>
                </div>
                <StatusBadge label={artifact.status} />
              </div>
              <dl className="detail-grid artifact-facts">
                <div>
                  <dt>Version</dt>
                  <dd><strong>v{artifact.version}</strong></dd>
                </div>
                <div>
                  <dt>Owner / producer</dt>
                  <dd>{artifact.owner} / {artifact.producer ?? "—"}</dd>
                </div>
                <div className="wide-fact">
                  <dt>Content hash</dt>
                  <dd><HashValue value={artifact.content_hash} /></dd>
                </div>
                <div className="wide-fact">
                  <dt>Evidence references</dt>
                  <dd><StringList values={artifact.evidence_refs} /></dd>
                </div>
              </dl>
            </article>
          ))}
        </div>
      ) : (
        <EmptyInline text="No artifact versions are attached to this snapshot." />
      )}
    </Panel>
  );
}

function ProposalPanel({ proposals }: { proposals: AgentProposal[] }) {
  return (
    <Panel eyebrow="Agent output" title="Proposal history" count={proposals.length}>
      {proposals.length > 0 ? (
        <div className="proposal-list">
          {proposals.map((proposal) => (
            <article className="proposal-card" key={`${proposal.proposal_id}-${proposal.revision}`}>
              <div className="card-title-row">
                <div>
                  <p className="card-kicker">{proposal.producer_kind} / {proposal.producer}</p>
                  <h3>{proposal.proposal_id} · r{proposal.revision}</h3>
                </div>
                <StatusBadge label={proposal.status} />
              </div>
              <div className="proposal-meta-row">
                <span>confidence {Math.round(proposal.confidence * 100)}%</span>
                <span>base revision r{proposal.base_revision}</span>
                <span>next step: {proposal.next_step}</span>
              </div>
              <dl className="detail-grid">
                <div>
                  <dt>Content hash</dt>
                  <dd><HashValue value={proposal.content_hash} /></dd>
                </div>
                <div>
                  <dt>Evidence</dt>
                  <dd><StringList values={proposal.evidence_refs} /></dd>
                </div>
                <div>
                  <dt>Risks</dt>
                  <dd><StringList values={proposal.risks} /></dd>
                </div>
                <div>
                  <dt>Open questions</dt>
                  <dd><StringList values={proposal.open_questions} /></dd>
                </div>
              </dl>
              <p className="human-review-note">Human review required · no agent approval control</p>
            </article>
          ))}
        </div>
      ) : (
        <EmptyInline text="No agent proposals are attached to this snapshot." />
      )}
    </Panel>
  );
}

function GatePanel({ gates }: { gates: GateReviewSnapshot[] }) {
  return (
    <Panel eyebrow="Governance checks" title="Gate Review" count={gates.length}>
      {gates.length > 0 ? (
        <div className="gate-list">
          {gates.map((gate) => (
            <article className={`gate-card ${gate.stale ? "is-stale" : ""}`} key={`${gate.gate_run_id}-${gate.revision}`}>
              <div className="card-title-row">
                <div>
                  <p className="card-kicker">{gate.severity} gate · {gate.validator_version} · run {gate.gate_run_id}</p>
                  <h3><code>{gate.gate_id}</code></h3>
                </div>
                <div className="status-cluster">
                  <StatusBadge label={gate.status} />
                  {gate.stale ? <StatusBadge label="stale" tone="stale" /> : null}
                </div>
              </div>
              <dl className="detail-grid gate-facts">
                <div>
                  <dt>Revision</dt>
                  <dd>r{gate.revision}</dd>
                </div>
                <div>
                  <dt>Created at</dt>
                  <dd><time dateTime={gate.created_at}>{formatDate(gate.created_at)}</time></dd>
                </div>
                <div className="wide-fact">
                  <dt>Gate Review content hash</dt>
                  <dd><HashValue value={gate.content_hash} /></dd>
                </div>
                <div>
                  <dt>Violations</dt>
                  <dd><StringList values={gate.violations} empty="None" /></dd>
                </div>
                <div>
                  <dt>Warnings</dt>
                  <dd><StringList values={gate.warnings} empty="None" /></dd>
                </div>
                <div>
                  <dt>Artifact hashes</dt>
                  <dd>
                    <ul className="hash-list">
                      {Object.entries(gate.artifact_hashes).map(([artifactId, artifactHash]) => (
                        <li key={artifactId}><span>{artifactId}</span><HashValue value={artifactHash} /></li>
                      ))}
                    </ul>
                  </dd>
                </div>
                <div>
                  <dt>Evidence references</dt>
                  <dd><StringList values={gate.evidence_refs} /></dd>
                </div>
              </dl>
            </article>
          ))}
        </div>
      ) : (
        <EmptyInline text="No Gate Review has been recorded; release remains blocked." />
      )}
    </Panel>
  );
}

function stringRecord(value: unknown): Record<string, string> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return {};
  }
  return Object.fromEntries(
    Object.entries(value).filter(([, item]) => typeof item === "string"),
  ) as Record<string, string>;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function ReleaseCandidateEvidence({ candidate }: { candidate: ReleaseCandidate }) {
  const manifestArtifactHashes = stringRecord(candidate.manifest.artifact_hashes);
  const manifestGateRunIds = stringArray(candidate.manifest.gate_run_ids);
  const manifestDigest = candidate.manifest.manifest_digest;

  return (
    <dl className="detail-grid release-facts">
      <div>
        <dt>Candidate status</dt>
        <dd><StatusBadge label={candidate.status} /></dd>
      </div>
      <div>
        <dt>Created by</dt>
        <dd>{candidate.created_by}</dd>
      </div>
      <div>
        <dt>Created at</dt>
        <dd><time dateTime={candidate.created_at}>{formatDate(candidate.created_at)}</time></dd>
      </div>
      <div>
        <dt>Content hash</dt>
        <dd><HashValue value={candidate.content_hash} /></dd>
      </div>
      <div>
        <dt>Artifact references</dt>
        <dd><StringList values={candidate.artifact_ids} /></dd>
      </div>
      <div>
        <dt>Gate references</dt>
        <dd><StringList values={candidate.gate_run_ids} /></dd>
      </div>
      <div className="wide-fact">
        <dt>Manifest artifact hashes</dt>
        <dd>
          <ul className="hash-list">
            {Object.entries(manifestArtifactHashes).map(([artifactId, artifactHash]) => (
              <li key={artifactId}><span>{artifactId}</span><HashValue value={artifactHash} /></li>
            ))}
          </ul>
        </dd>
      </div>
      <div>
        <dt>Manifest gate run IDs</dt>
        <dd><StringList values={manifestGateRunIds} /></dd>
      </div>
      <div>
        <dt>Manifest digest</dt>
        <dd>
          {typeof manifestDigest === "string" ? <HashValue value={manifestDigest} /> : <span className="muted">—</span>}
        </dd>
      </div>
    </dl>
  );
}

function ReleaseCandidatePanel({
  snapshot,
  api,
  mutation,
  readiness,
}: {
  snapshot: WorkspaceSnapshot;
  api: ShipyardApi;
  mutation: ReturnType<typeof useWorkbenchMutations>["createReleaseCandidate"];
  readiness: ReleaseReadiness;
}) {
  const latestCandidate = snapshot.release_candidates
    .slice()
    .sort((left, right) => right.revision - left.revision)[0];

  const requestCandidate = () => {
    if (!api.createReleaseCandidate || !readiness.available || mutation.isPending) {
      return;
    }
    mutation.mutate({
      workspaceId: snapshot.workspace.workspace_id,
      input: {
        artifact_ids: readiness.currentArtifactIds,
        gate_run_ids: readiness.currentGateRunIds,
      },
    });
  };

  return (
    <Panel eyebrow="Human release boundary" title="Release Candidate" className="release-panel">
      <div className={`release-state ${readiness.available ? "is-available" : "is-blocked"}`}>
        <div className="release-state-heading">
          <span className="release-icon" aria-hidden="true">{readiness.available ? "↗" : "!"}</span>
          <div>
            <p className="card-kicker">{latestCandidate ? `${latestCandidate.candidate_id} · r${latestCandidate.revision}` : "No candidate manifest"}</p>
            <h3>{readiness.available ? "Release Candidate available" : "Release Candidate blocked"}</h3>
          </div>
        </div>

        <div className="release-policy">
          <span className="fact-label">Required gates</span>
          <StringList values={readiness.requiredGateIds} empty="No policy configured" />
        </div>

        {readiness.available ? (
          <>
            <p className="release-message">All required gates passed</p>
            <p className="release-api-note">Available via authenticated API</p>
          </>
        ) : (
          <>
            <p className="release-message">Blocking reasons</p>
            <ul className="blocking-list">
              {readiness.blockingReasons.map((blocker, index) => (
                  <li key={`${blocker.gateId ?? "release"}-${blocker.reason}-${index}`}>
                    {blocker.gateId ? <code>{blocker.gateId}</code> : <code>release.guard</code>}
                    <span>{blocker.reason}</span>
                  </li>
              ))}
            </ul>
          </>
        )}

        {latestCandidate ? <ReleaseCandidateEvidence candidate={latestCandidate} /> : null}

        <button
          className="release-button"
          type="button"
          disabled={!readiness.available || !api.createReleaseCandidate || mutation.isPending}
          onClick={requestCandidate}
        >
          {mutation.isPending ? "Requesting authenticated API…" : "Create Release Candidate"}
        </button>
        {mutation.isError ? (
          <p className="inline-error" role="alert">
            Release Candidate API request failed: {errorMessage(mutation.error)}
          </p>
        ) : null}
      </div>
      <p className="release-footnote">
        This surface never performs a customer production action. The button delegates to the authenticated Workbench API only.
      </p>
    </Panel>
  );
}

function AuditPanel({ events }: { events: WorkspaceSnapshot["audit_events"] }) {
  const tail = events.slice(-4).reverse();
  return (
    <Panel eyebrow="Traceability" title="Audit tail" count={events.length} className="audit-panel">
      {tail.length > 0 ? (
        <ol className="audit-list">
          {tail.map((event) => (
            <li key={event.event_id}>
              <div className="audit-marker" aria-hidden="true" />
              <div>
                <strong>{event.event_type}</strong>
                <span>{event.actor} · {formatDate(event.created_at)}</span>
                <HashValue value={event.event_hash} />
              </div>
            </li>
          ))}
        </ol>
      ) : (
        <EmptyInline text="No audit events in this snapshot." />
      )}
    </Panel>
  );
}

function EmptyInline({ text }: { text: string }) {
  return <p className="empty-inline">{text}</p>;
}

export function App({ api }: AppProps) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: false,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <WorkbenchScreen api={api} />
    </QueryClientProvider>
  );
}
