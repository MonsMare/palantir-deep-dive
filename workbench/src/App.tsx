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

const shortHash = (value: string): string =>
  value.length > 18 ? `${value.slice(0, 18)}…` : value;

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
    <code className="hash-value" title={value}>
      {shortHash(value)}
    </code>
  );
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
  if (snapshotQuery.isPending || !snapshotQuery.data) {
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
          <GatePanel gates={snapshotQuery.data.gate_reviews} />
        </main>
        <aside className="detail-column" aria-label="Release and audit details">
          <ReleaseCandidatePanel
            snapshot={snapshotQuery.data}
            api={api}
            mutation={mutations.createReleaseCandidate}
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
                  <p className="card-kicker">{gate.severity} gate · {gate.validator_version}</p>
                  <h3><code>{gate.gate_id}</code></h3>
                </div>
                <div className="status-cluster">
                  <StatusBadge label={gate.status} />
                  {gate.stale ? <StatusBadge label="stale" tone="stale" /> : null}
                </div>
              </div>
              <dl className="detail-grid gate-facts">
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

function ReleaseCandidatePanel({
  snapshot,
  api,
  mutation,
}: {
  snapshot: WorkspaceSnapshot;
  api: ShipyardApi;
  mutation: ReturnType<typeof useWorkbenchMutations>["createReleaseCandidate"];
}) {
  const blockingGates = useMemo(
    () => snapshot.gate_reviews.filter((gate) => gate.status !== "passed" || gate.stale),
    [snapshot.gate_reviews],
  );
  const releaseAvailable = snapshot.gate_reviews.length > 0 && blockingGates.length === 0;
  const latestCandidate = snapshot.release_candidates
    .slice()
    .sort((left, right) => right.revision - left.revision)[0];

  const requestCandidate = () => {
    if (!api.createReleaseCandidate || !releaseAvailable || mutation.isPending) {
      return;
    }
    mutation.mutate({
      workspaceId: snapshot.workspace.workspace_id,
      input: {
        artifact_ids: snapshot.artifacts.map((artifact) => artifact.artifact_id),
        gate_run_ids: snapshot.gate_reviews.map((gate) => gate.gate_run_id),
      },
    });
  };

  return (
    <Panel eyebrow="Human release boundary" title="Release Candidate" className="release-panel">
      <div className={`release-state ${releaseAvailable ? "is-available" : "is-blocked"}`}>
        <div className="release-state-heading">
          <span className="release-icon" aria-hidden="true">{releaseAvailable ? "↗" : "!"}</span>
          <div>
            <p className="card-kicker">{latestCandidate ? `${latestCandidate.candidate_id} · r${latestCandidate.revision}` : "No candidate manifest"}</p>
            <h3>{releaseAvailable ? "Release Candidate available" : "Release Candidate blocked"}</h3>
          </div>
        </div>

        {releaseAvailable ? (
          <>
            <p className="release-message">All required gates passed</p>
            <p className="release-api-note">Available via authenticated API</p>
          </>
        ) : (
          <>
            <p className="release-message">Blocking reasons</p>
            <ul className="blocking-list">
              {blockingGates.length > 0 ? (
                blockingGates.map((gate) => (
                  <li key={gate.gate_run_id}>
                    <code>{gate.gate_id}</code>
                    <span>{gate.stale ? "stale" : gate.status}</span>
                  </li>
                ))
              ) : (
                <li><span>No required Gate Review is available.</span></li>
              )}
            </ul>
          </>
        )}

        <button
          className="release-button"
          type="button"
          disabled={!releaseAvailable || !api.createReleaseCandidate || mutation.isPending}
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
