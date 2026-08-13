# Software Requirements Alignment and Delivery Forecasting Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Build a simulated Ontology project that traces software requirements, change requests, delivery events, duration forecasts, feasible sprint plans, mock Actions, and feedback through the AI FDE Builder gates.

**Architecture:** Use a deterministic synthetic event generator with hidden causal truth, conformed data products, a versioned RDFS/SHACL model, time-correct analytics and features, baseline-plus-ML delivery forecasts, OR-Tools candidate plans, and a business-facing Streamlit/API surface. The project consumes the platform contracts from the AI FDE Builder plan and never writes to a real project-management system.

**Tech Stack:** Python 3.12, Pydantic v2, DuckDB, Polars, RDFLib, pySHACL, scikit-learn, OR-Tools, FastAPI, Streamlit, pytest, pandas-compatible Parquet fixtures, the AI FDE Builder Gate Engine and Action Broker.

## Global Constraints

- The project is local/private and uses deterministic seeded simulation data.
- The first release uses only Mock Actions.
- Requirement, ChangeRequest, WorkItem, Sprint, Dependency, Prediction, CandidatePlan, ActionOutcome, and Feedback remain distinct objects.
- Current state is a derived view; state events remain immutable facts.
- Every prediction includes entity, as_of_time, horizon, label definition, feature snapshot, model version, and evidence.
- Features may use only data available at or before as_of_time, subject to declared availability lag.
- No ML model is released unless it is compared with a baseline on a temporal holdout.
- No plan is released unless all hard constraints are satisfied or the plan is explicitly marked infeasible.
- No business conclusion is promoted from assumption to fact without an evidence reference and a responsible reviewer.
- All stage transitions use the platform Gate Engine.
- User overrides, approvals, rejections, Action outcomes, and actual completion results are recorded as Feedback.
- The sample project must still produce a useful baseline and rule-based analysis when model data is insufficient.

## File and module map

    projects/software-delivery-demo/
      config/project.yaml
      ontology/domain.ttl
      ontology/shapes.ttl
      sources/
      data_products/
      analytics/
      features/
      models/
      decisions/
      actions/
      evaluations/
      fixtures/

    src/software_delivery_demo/
      domain.py             project object and event models
      generator.py          seeded causal data generator
      ontology.py           RDF graph and SHACL integration
      data_products.py      conformed tables and quality checks
      analytics.py          historical metrics and snapshots
      features.py           point-in-time feature construction
      labels.py             time-safe label construction
      models.py             baselines, ML models, and evaluation
      decisions.py          feasible candidate plans and optimization
      actions.py            sample Action registrations
      app.py                sample API/application adapter

    tests/demo/
      test_domain.py
      test_generator.py
      test_ontology.py
      test_data_products.py
      test_features.py
      test_models.py
      test_decisions.py
      test_actions.py
      test_end_to_end.py

## Task 1: Create the sample project configuration and domain contracts

**Files:**
- Create: projects/software-delivery-demo/config/project.yaml
- Create: src/software_delivery_demo/__init__.py
- Create: src/software_delivery_demo/domain.py
- Create: tests/demo/test_domain.py

**Interfaces:**
- ProjectConfig has seed, team_count, people_count, module_count, sprint_count, requirement_count, work_item_count, change_request_count, start_date, and sprint_length_days.
- ProjectConfig.load(path: Path) -> ProjectConfig
- generate_id(prefix: str, seed: int, ordinal: int) -> str
- DomainEvent with event_id, entity_type, entity_id, event_type, event_time, observed_time, actor_id, and payload.
- Requirement, ChangeRequest, WorkItem, Sprint, Dependency, Person, Team, CapacitySnapshot, and Feedback are Pydantic models.
- Draft domain models allow nullable business fields until the Ontology and SHACL stage; status fields default to their initial lifecycle state.
- RequirementStatus, ChangeRequestStatus, WorkItemStatus, and ActionStatus are enums.

- [ ] Step 1: Write tests for distinct object identity, event time fields, and configuration defaults.

~~~python
def test_requirement_and_change_request_have_distinct_ids():
    requirement = Requirement(requirement_id="req-001", title="Export report")
    change = ChangeRequest(change_id="chg-001", requirement_id="req-001")
    assert requirement.requirement_id != change.change_id


def test_domain_event_requires_event_and_observed_time():
    with pytest.raises(ValidationError):
        DomainEvent(
            event_id="evt-1",
            entity_type="WorkItem",
            entity_id="wi-1",
            event_type="WorkItemStarted",
        )


def test_project_config_has_seed_and_sprint_count():
    config = ProjectConfig.load(Path("projects/software-delivery-demo/config/project.yaml"))
    assert config.seed == 20260811
    assert config.sprint_count == 8
~~~

- [ ] Step 2: Run the focused tests and verify they fail.

Run: pytest tests/demo/test_domain.py -q
Expected: FAIL because the sample package and configuration are absent.

- [ ] Step 3: Implement the Pydantic domain models and configuration loader.

Set these concrete defaults in project.yaml:
  - seed: 20260811
  - teams: 3
  - people: 12
  - modules: 5
  - sprints: 8
  - requirements: 80
  - work_items: 160
  - change_requests: 40
  - start_date: 2026-01-05
  - sprint_length_days: 14

- [ ] Step 4: Run the focused tests.

Run: pytest tests/demo/test_domain.py -q
Expected: all tests pass.

- [ ] Step 5: Commit the domain contract.

Run:
    git add projects/software-delivery-demo/config/project.yaml src/software_delivery_demo/__init__.py src/software_delivery_demo/domain.py tests/demo/test_domain.py
    git commit -m "feat: define software delivery demo domain"

## Task 2: Build the deterministic causal data generator

**Files:**
- Create: src/software_delivery_demo/generator.py
- Create: projects/software-delivery-demo/fixtures/generator_config.yaml
- Create: tests/demo/test_generator.py

**Interfaces:**
- DatasetBundle with requirements, changes, work_items, events, dependencies, sprints, people, teams, capacities, feedback, and hidden_truth.
- DatasetBundle stores public Polars DataFrames separately from hidden_truth and exposes only public columns through write_dataset.
- generate_dataset(config: ProjectConfig) -> DatasetBundle
- write_dataset(bundle: DatasetBundle, root: Path) -> None
- load_dataset(root: Path) -> DatasetBundle

- [ ] Step 1: Write invariant tests for counts, foreign keys, event order, and causal relationships.

~~~python
def test_generator_is_deterministic(project_config):
    first = generate_dataset(project_config)
    second = generate_dataset(project_config)
    assert first.work_items.equals(second.work_items)
    assert first.events.equals(second.events)


def test_every_work_item_has_requirement_module_and_team(bundle):
    assert bundle.work_items["requirement_id"].notna().all()
    assert bundle.work_items["module_id"].notna().all()
    assert bundle.work_items["team_id"].notna().all()


def test_change_request_increases_scope_or_changes_acceptance(bundle):
    changed = bundle.changes.filter(pl.col("change_id").is_not_null())
    assert ((changed["added_scope_hours"] > 0) | (changed["acceptance_delta"] != "")).all()


def test_hidden_truth_is_not_in_public_event_columns(bundle):
    assert "true_delay_days" not in bundle.events.columns
    assert "causal_risk_score" not in bundle.events.columns
~~~

- [ ] Step 2: Run the generator tests and verify they fail.

Run: pytest tests/demo/test_generator.py -q
Expected: FAIL because DatasetBundle and generator functions are absent.

- [ ] Step 3: Implement seeded entity generation.

Generate stable IDs from seed and ordinal. Generate teams with skills, people with availability, modules, projects, requirements, WorkItems, Sprints, dependencies, and capacity snapshots.

- [ ] Step 4: Implement causal event generation.

Apply these rules:
  - missing acceptance criteria increases clarification duration;
  - ChangeRequest adds scope hours or acceptance changes;
  - unresolved dependencies add waiting time;
  - capacity shortage adds queue time;
  - extra review rounds add cycle time;
  - BlockerEvent contributes to actual duration;
  - hidden_truth stores causal contributors and actual latent delay.

Generate state events in event_time order and set observed_time to event_time plus a configured ingestion delay.

- [ ] Step 5: Write Parquet or CSV fixtures and keep hidden_truth in a separate protected fixture.

The public dataset must never include hidden_truth columns. Evaluation code may read hidden_truth only after feature construction and prediction.

- [ ] Step 6: Run the tests.

Run: pytest tests/demo/test_generator.py -q
Expected: all tests pass.

- [ ] Step 7: Commit the generator.

Run:
    git add src/software_delivery_demo/generator.py projects/software-delivery-demo/fixtures tests/demo/test_generator.py
    git commit -m "feat: generate causal software delivery fixtures"

## Task 3: Build the RDFS model and SHACL shapes

**Files:**
- Create: src/software_delivery_demo/ontology.py
- Create: projects/software-delivery-demo/ontology/domain.ttl
- Create: projects/software-delivery-demo/ontology/shapes.ttl
- Create: tests/demo/test_ontology.py

**Interfaces:**
- build_domain_graph(bundle: DatasetBundle) -> OntologyDocument
- load_domain_graph(path: Path) -> OntologyDocument
- validate_domain_graph(document: OntologyDocument) -> ValidationResult
- project_objects_to_graph(bundle: DatasetBundle) -> OntologyDocument
- OntologyDocument.add_type(subject: str, class_name: str) -> None
- OntologyDocument.remove_link(subject: str, predicate: str, object_id: str) -> None

- [ ] Step 1: Write valid and invalid graph tests.

~~~python
def test_valid_requirement_has_owner_and_goal(bundle):
    document = project_objects_to_graph(bundle)
    result = validate_domain_graph(document)
    assert result.passed is True


def test_change_request_without_requirement_is_blocked(bundle):
    document = project_objects_to_graph(bundle)
    document.remove_link("ChangeRequest/chg-001", "changes", "Requirement/req-001")
    result = validate_domain_graph(document)
    assert result.passed is False
    assert "changes" in result.message


def test_prediction_shape_requires_as_of_time(bundle):
    document = project_objects_to_graph(bundle)
    document.add_type("DeliveryPrediction/pred-001", "DeliveryPrediction")
    result = validate_domain_graph(document)
    assert result.passed is False
    assert "as_of_time" in result.message
~~~

- [ ] Step 2: Run the ontology tests and verify they fail.

Run: pytest tests/demo/test_ontology.py -q
Expected: FAIL because the RDF graph and Shape files are absent.

- [ ] Step 3: Define domain classes and properties.

Classes:
  Project, Requirement, RequirementVersion, ChangeRequest, AcceptanceCriterion, Stakeholder, Module, WorkItem, Dependency, Sprint, Team, Person, CapacitySnapshot, BlockerEvent, Estimate, DeliveryPrediction, DeliveryRisk, CandidatePlan, PlanChange, ActionRequest, ActionOutcome, Feedback.

Properties must express:
  - Requirement hasVersion RequirementVersion;
  - ChangeRequest changes Requirement;
  - Requirement decomposedInto WorkItem;
  - WorkItem dependsOn WorkItem;
  - WorkItem plannedIn Sprint;
  - DeliveryPrediction predicts WorkItem;
  - CandidatePlan addresses ChangeRequest;
  - CandidatePlan usesPrediction DeliveryPrediction;
  - ActionRequest produces ActionOutcome.

- [ ] Step 4: Define SHACL shapes.

Hard constraints:
  - Requirement requires requirement_id, goal, owner, status;
  - ChangeRequest requires change_id, requested_at, requester, and an affected Requirement or explicit new scope;
  - WorkItem requires work_item_id, requirement, module, status, and team;
  - Dependency requires predecessor, successor, dependency_type, and status;
  - DeliveryPrediction requires target, as_of_time, horizon, model_version, feature_snapshot_id, and evidence_refs;
  - CandidatePlan requires objective_value, constraints, feasibility, and addresses;
  - ActionRequest requires action_type, target_id, idempotency_key, and approval_state.

- [ ] Step 5: Run the tests.

Run: pytest tests/demo/test_ontology.py -q
Expected: all tests pass.

- [ ] Step 6: Commit the Ontology and shapes.

Run:
    git add src/software_delivery_demo/ontology.py projects/software-delivery-demo/ontology tests/demo/test_ontology.py
    git commit -m "feat: model software delivery ontology"

## Task 4: Build conformed data products and data-quality gates

**Files:**
- Create: src/software_delivery_demo/data_products.py
- Create: projects/software-delivery-demo/data_products/contracts.yaml
- Create: tests/demo/test_data_products.py

**Interfaces:**
- build_requirements_product(bundle: DatasetBundle) -> pl.DataFrame
- build_change_events_product(bundle: DatasetBundle) -> pl.DataFrame
- build_work_item_lifecycle_product(bundle: DatasetBundle) -> pl.DataFrame
- build_capacity_product(bundle: DatasetBundle) -> pl.DataFrame
- DataProductBundle has requirements, change_events, work_item_lifecycle, capacity, and dependencies.
- QualityReport has passed, failed_rule_ids, issue_count, and evidence_refs.
- run_quality_checks(products: DataProductBundle) -> QualityReport
- build_data_products(bundle: DatasetBundle) -> DataProductBundle

- [ ] Step 1: Write tests for conformed grains, foreign keys, event intervals, and failures.

~~~python
def test_work_item_lifecycle_has_one_row_per_state_interval(products):
    lifecycle = products.work_item_lifecycle
    assert lifecycle.select(["work_item_id", "state_entered_at"]).unique().height == lifecycle.height


def test_actual_completion_is_after_start(products):
    completed = products.work_item_lifecycle.filter(pl.col("state") == "done")
    assert (completed["state_exited_at"] >= completed["state_entered_at"]).all()


def test_invalid_dependency_cycle_fails_quality(bundle_with_dependency_cycle):
    products = build_data_products(bundle_with_dependency_cycle)
    report = run_quality_checks(products)
    assert report.failed_rule_ids == ["dependency.no-cycle"]
~~~

- [ ] Step 2: Run the tests and verify they fail.

Run: pytest tests/demo/test_data_products.py -q
Expected: FAIL because data product builders are absent.

- [ ] Step 3: Implement conformed products with declared grain.

Required grains:
  - requirements: one row per RequirementVersion;
  - change_events: one row per ChangeRequest event;
  - work_item_lifecycle: one row per WorkItem state interval;
  - capacity: one row per Team and Sprint capacity snapshot;
  - dependencies: one row per dependency edge.

- [ ] Step 4: Implement quality rules.

Rules:
  - primary keys are unique;
  - foreign keys resolve;
  - event_time is not after observed_time except within allowed late-arrival configuration;
  - complete intervals have non-negative duration;
  - dependency graph has no cycle;
  - capacity_hours is non-negative;
  - a completed WorkItem has start and completion events;
  - ChangeRequest requested_at is not after observed_at;
  - current status can be reconstructed from the latest event.

- [ ] Step 5: Emit DataIssue records for failed rows and a QualityReport for the product.

A failed hard rule must be usable by the platform Data Gate and must block the sample project's data-product stage.

- [ ] Step 6: Run the tests.

Run: pytest tests/demo/test_data_products.py -q
Expected: all tests pass.

- [ ] Step 7: Commit the data products.

Run:
    git add src/software_delivery_demo/data_products.py projects/software-delivery-demo/data_products tests/demo/test_data_products.py
    git commit -m "feat: build conformed software delivery data products"

## Task 5: Add historical snapshots and analytical metrics

**Files:**
- Create: src/software_delivery_demo/analytics.py
- Create: projects/software-delivery-demo/analytics/metric_definitions.yaml
- Create: tests/demo/test_analytics.py

**Interfaces:**
- build_project_snapshot(products: DataProductBundle, as_of_time: datetime) -> ProjectSnapshot
- ProjectSnapshot has as_of_time, evidence_snapshot_id, source_watermark, requirements, work_items, events, dependencies, capacity, and metrics.
- calculate_requirement_metrics(snapshot: ProjectSnapshot) -> pl.DataFrame
- calculate_delivery_metrics(snapshot: ProjectSnapshot) -> pl.DataFrame
- calculate_capacity_metrics(snapshot: ProjectSnapshot) -> pl.DataFrame
- calculate_dependency_metrics(snapshot: ProjectSnapshot) -> pl.DataFrame

- [ ] Step 1: Write tests proving snapshots exclude future events.

~~~python
def test_snapshot_excludes_events_after_observation(products):
    as_of = datetime(2026, 3, 1, tzinfo=timezone.utc)
    snapshot = build_project_snapshot(products, as_of)
    assert snapshot.events.filter(pl.col("event_time") > as_of).height == 0


def test_delivery_metrics_have_required_baseline_columns(snapshot):
    metrics = calculate_delivery_metrics(snapshot)
    assert {"team_id", "completed_count", "median_cycle_days"} <= set(metrics.columns)
~~~

- [ ] Step 2: Run the tests and verify they fail.

Run: pytest tests/demo/test_analytics.py -q
Expected: FAIL because snapshot and metric functions are absent.

- [ ] Step 3: Implement point-in-time project snapshots.

A snapshot includes only records with observed_time less than or equal to as_of_time, applies the configured availability lag, and records evidence_snapshot_id and source_watermark.

- [ ] Step 4: Implement metric definitions.

Required metrics:
  - requirement clarification duration;
  - change count and added scope hours;
  - WorkItem lead and cycle time;
  - blocked duration;
  - review rounds and review duration;
  - test duration;
  - Sprint completion rate;
  - team throughput;
  - remaining capacity;
  - unresolved dependency count.

- [ ] Step 5: Run the tests.

Run: pytest tests/demo/test_analytics.py -q
Expected: all tests pass.

- [ ] Step 6: Commit snapshots and analytics.

Run:
    git add src/software_delivery_demo/analytics.py projects/software-delivery-demo/analytics tests/demo/test_analytics.py
    git commit -m "feat: add point-in-time delivery analytics"

## Task 6: Construct time-safe labels, features, and leakage checks

**Files:**
- Create: src/software_delivery_demo/labels.py
- Create: src/software_delivery_demo/features.py
- Create: projects/software-delivery-demo/features/definitions.yaml
- Create: tests/demo/test_features.py

**Interfaces:**
- LabelDefinition with label_id, entity_type, as_of_time, horizon, and outcome_field.
- FeatureDefinition with feature_id, entity_type, grain, window, as_of_time, availability_lag, missing_policy, version, and lineage.
- LeakageReport has passed, leaked_columns, violations, and evidence_refs.
- load_feature_definitions() -> list[FeatureDefinition]
- build_labels(products: DataProductBundle, observation_times: list[datetime]) -> pl.DataFrame
- build_features(products: DataProductBundle, observation_times: list[datetime]) -> pl.DataFrame
- build_features_with_intentional_leak(products: DataProductBundle) -> pl.DataFrame
- check_no_leakage(features: pl.DataFrame, labels: pl.DataFrame, definitions: list[FeatureDefinition]) -> LeakageReport

- [ ] Step 1: Write tests for required feature metadata, point-in-time behavior, missing semantics, and intentional leakage detection.

~~~python
def test_feature_definition_contains_time_and_lineage_fields():
    definition = load_feature_definitions()[0]
    assert definition.entity_type
    assert definition.grain
    assert definition.as_of_time
    assert definition.availability_lag
    assert definition.lineage


def test_features_do_not_include_future_events(products):
    as_of_times = [datetime(2026, 3, 1, tzinfo=timezone.utc)]
    features = build_features(products, as_of_times)
    assert features.filter(pl.col("source_event_time") > pl.col("as_of_time")).height == 0


def test_leakage_check_catches_actual_completion_date(products):
    features = build_features_with_intentional_leak(products)
    observation_times = [datetime(2026, 3, 1, tzinfo=timezone.utc)]
    labels = build_labels(products, observation_times)
    report = check_no_leakage(features, labels, load_feature_definitions())
    assert report.passed is False
    assert "actual_complete_at" in report.leaked_columns
~~~

- [ ] Step 2: Run the tests and verify they fail.

Run: pytest tests/demo/test_features.py -q
Expected: FAIL because label, feature, and leakage modules are absent.

- [ ] Step 3: Define the feature catalog.

Implement:
  - team historical median cycle time over the preceding five sprints;
  - requirement change count before as_of_time;
  - added scope hours before as_of_time;
  - unresolved dependency count at as_of_time;
  - dependency graph centrality at as_of_time;
  - team blocked ratio over the preceding 30 days;
  - current review queue;
  - acceptance criterion completeness;
  - available capacity;
  - historical estimate calibration;
  - task type and priority.

Each definition must include lineage, missing_policy, version, and leakage_policy.

- [ ] Step 4: Build labels from future outcomes.

Labels:
  - WorkItem remaining_duration_days;
  - WorkItem probability_late against committed_date;
  - Requirement delay_days;
  - Sprint commitment completion rate.

Exclude cancelled and reopened records according to explicit label policy rather than dropping them silently.

- [ ] Step 5: Implement leakage checks.

Reject any feature derived from:
  - actual_complete_at;
  - post-observation status;
  - future blockers;
  - future review results;
  - future capacity;
  - future ChangeRequests;
  - any field derived from the future label.

- [ ] Step 6: Run the tests.

Run: pytest tests/demo/test_features.py -q
Expected: all tests pass.

- [ ] Step 7: Commit labels and features.

Run:
    git add src/software_delivery_demo/labels.py src/software_delivery_demo/features.py projects/software-delivery-demo/features tests/demo/test_features.py
    git commit -m "feat: add time-safe delivery features and labels"

## Task 7: Implement baselines, ML forecasts, evaluation, and replay

**Files:**
- Create: src/software_delivery_demo/models.py
- Create: projects/software-delivery-demo/models/model_policy.yaml
- Create: tests/demo/test_models.py

**Interfaces:**
- BaselineModel.fit(features: pl.DataFrame, labels: pl.DataFrame) -> BaselineModel
- BaselineModel.predict(features: pl.DataFrame) -> PredictionFrame
- DeliveryModel.fit(features: pl.DataFrame, labels: pl.DataFrame) -> ModelVersion
- PredictionFrame has entity_id, as_of_time, p50_days, p80_days, late_probability, model_version, and feature_snapshot_id.
- ModelVersion has model_version, feature_definition_version, training_snapshot_id, code_version, and artifact_uri.
- EvaluationReport has baseline_mae, model_mae, p80_coverage, calibration, group_metrics, leakage_passed, and temporal_windows.
- ModelReleaseDecision has released, selected_model_version, reason, and fallback_model_version.
- evaluate_model(predictions: PredictionFrame, labels: pl.DataFrame, baseline: PredictionFrame) -> EvaluationReport
- run_replay(model_version: ModelVersion, products: DataProductBundle, observation_times: list[datetime]) -> ReplayReport
- release_model(report: EvaluationReport) -> ModelReleaseDecision

- [ ] Step 1: Write tests for temporal splits, baseline comparison, calibration, and no-release behavior.

~~~python
def test_temporal_split_has_no_future_training_rows(feature_frame):
    train, test = temporal_split(feature_frame, cutoff=datetime(2026, 5, 1))
    assert train["as_of_time"].max() < test["as_of_time"].min()


def test_evaluation_records_baseline_comparison(predictions, labels, baseline):
    report = evaluate_model(predictions, labels, baseline)
    assert report.baseline_mae is not None
    assert report.model_mae is not None
    assert report.p80_coverage is not None


def test_model_not_released_when_worse_than_baseline(bad_report):
    decision = release_model(bad_report)
    assert decision.released is False
    assert decision.reason == "MODEL_NOT_BETTER_THAN_BASELINE"
~~~

- [ ] Step 2: Run the model tests and verify they fail.

Run: pytest tests/demo/test_models.py -q
Expected: FAIL because model and evaluation modules are absent.

- [ ] Step 3: Implement baselines.

Use:
  - historical median cycle time by team and task type;
  - estimate multiplied by historical team calibration;
  - a simple quantile baseline for P50 and P80.

The baseline must always be available even when ML training is skipped.

- [ ] Step 4: Implement temporal training and evaluation.

Use chronological train/validation/test splits. Evaluate:
  - MAE and RMSE;
  - P50 absolute error;
  - P80 coverage;
  - probability calibration;
  - late-classification Precision, Recall, and Brier score;
  - group metrics by team, task type, and priority.

- [ ] Step 5: Implement one transparent candidate model.

Use GradientBoostingRegressor or HistGradientBoostingRegressor for duration and a calibrated classifier for late probability. Store feature_definition_version, training_snapshot_id, model_version, code_version, and evaluation_report_id.

- [ ] Step 6: Implement release policy.

Default policy:
  - model MAE must be less than or equal to baseline MAE;
  - P80 coverage must be at least 0.80;
  - leakage report must pass;
  - group performance cannot be worse than baseline by more than configured tolerance;
  - evaluation must include at least one temporal test window.

If the policy fails, release the baseline and a ModelDataIssue rather than an ML model.

- [ ] Step 7: Implement replay.

For each selected historical as_of_time:
  - build a snapshot;
  - build features;
  - run baseline and candidate model;
  - build predicted outcome;
  - compare to the later observed result;
  - store evidence and errors.

- [ ] Step 8: Run the tests.

Run: pytest tests/demo/test_models.py -q
Expected: all tests pass.

- [ ] Step 9: Commit models and evaluation.

Run:
    git add src/software_delivery_demo/models.py projects/software-delivery-demo/models tests/demo/test_models.py
    git commit -m "feat: add time-split delivery forecasts and replay"

## Task 8: Implement feasible candidate plans and optimization

**Files:**
- Create: src/software_delivery_demo/decisions.py
- Create: projects/software-delivery-demo/decisions/problem.yaml
- Create: tests/demo/test_decisions.py

**Interfaces:**
- DecisionProblem.load(path: Path) -> DecisionProblem
- CandidatePlan has plan_id, objective_value, changed_items, resource_delta, completion_distribution, constraints, assumptions, feasible, and infeasibility_reasons.
- FeasibilityReport has feasible, failed_constraints, constraint_slack, and evidence_refs.
- build_candidate_plans(snapshot: ProjectSnapshot, prediction: PredictionFrame, change: ChangeRequest) -> list[CandidatePlan]
- validate_plan(plan: CandidatePlan, snapshot: ProjectSnapshot) -> FeasibilityReport
- choose_plan(plans: list[CandidatePlan]) -> CandidatePlan
- explain_plan(plan: CandidatePlan) -> PlanExplanation

- [ ] Step 1: Write tests for hard constraints, alternatives, infeasible plans, and explanation.

~~~python
def test_candidate_plan_respects_team_capacity(snapshot, change_request):
    plans = build_candidate_plans(snapshot, predictions, change_request)
    assert all(validate_plan(plan, snapshot).feasible for plan in plans)


def test_dependency_order_is_preserved(plans, snapshot):
    for plan in plans:
        report = validate_plan(plan, snapshot)
        assert "dependency_order" not in report.failed_constraints


def test_infeasible_capacity_is_reported_not_hidden(overloaded_snapshot, change_request):
    plans = build_candidate_plans(overloaded_snapshot, predictions, change_request)
    assert any(validate_plan(plan, overloaded_snapshot).feasible is False for plan in plans)
    assert all(plan.infeasibility_reasons for plan in plans if not plan.feasible)
~~~

- [ ] Step 2: Run the decision tests and verify they fail.

Run: pytest tests/demo/test_decisions.py -q
Expected: FAIL because the decision module is absent.

- [ ] Step 3: Define the decision problem.

Variables:
  - accept_change;
  - split_requirement;
  - defer_low_priority_work_items;
  - move_work_item_to_sprint;
  - add_team_capacity;
  - adjust_commitment_date.

Objective:
  - minimize delay cost;
  - minimize high-priority unfinished work;
  - minimize added resource cost;
  - minimize plan-change cost;
  - minimize scope-split penalty.

Hard constraints:
  - no dependency order violation;
  - no capacity over-allocation;
  - required skills available;
  - immutable approved items remain;
  - test and acceptance tasks remain;
  - cancelled items are not scheduled;
  - permissions for plan changes are satisfied.

- [ ] Step 4: Generate at least five candidates.

Candidates:
  1. reject change and keep plan;
  2. accept and defer low-priority items;
  3. accept and split scope;
  4. accept and add capacity;
  5. accept and adjust commitment date.

Each candidate includes objective_value, changed_items, resource_delta, completion_distribution, constraints, assumptions, feasibility, and infeasibility_reasons.

- [ ] Step 5: Implement OR-Tools or deterministic enumeration for the fixture scale.

Use deterministic enumeration for small candidate sets if it produces transparent explanations. Keep the DecisionProblem interface independent of the solver.

- [ ] Step 6: Implement plan explanations.

Every explanation must identify:
  - objective contribution;
  - binding constraints;
  - slack;
  - impacted requirements;
  - predicted dates;
  - evidence and assumptions.

- [ ] Step 7: Run the tests.

Run: pytest tests/demo/test_decisions.py -q
Expected: all tests pass.

- [ ] Step 8: Commit the decision layer.

Run:
    git add src/software_delivery_demo/decisions.py projects/software-delivery-demo/decisions tests/demo/test_decisions.py
    git commit -m "feat: generate constraint-aware delivery plans"

## Task 9: Register sample Mock Actions and expose the business application

**Files:**
- Create: src/software_delivery_demo/actions.py
- Create: src/software_delivery_demo/app.py
- Create: tests/demo/test_actions.py
- Create: tests/demo/test_endpoints.py

**Interfaces:**
- register_demo_actions(action_broker: ActionBroker) -> None
- DemoContext has registry, gate_engine, action_broker, snapshot_provider, and project_root.
- create_change_request(payload: dict, actor: str) -> ActionOutcome
- request_clarification(payload: dict, actor: str) -> ActionOutcome
- approve_requirement(payload: dict, actor: str) -> ActionOutcome
- replan_sprint(payload: dict, actor: str) -> ActionOutcome
- create_demo_app(context: DemoContext) -> FastAPI

- [ ] Step 1: Write tests for Mock Action registration, approval, idempotency, and feedback.

~~~python
def test_replan_action_requires_project_manager_approval(demo_action_broker):
    request = make_replan_request()
    with pytest.raises(PermissionError):
        demo_action_broker.execute(request, actor="developer")


def test_replan_action_writes_plan_change_and_feedback(
    demo_action_broker, approved_replan_request
):
    outcome = demo_action_broker.execute(
        approved_replan_request,
        actor="project-manager",
    )
    assert outcome.success is True
    assert outcome.feedback_id is not None


def test_demo_endpoint_exposes_change_impact(client):
    response = client.post(
        "/demo/change-requests/chg-001/impact",
        json={"as_of_time": "2026-05-01T09:00:00Z"},
    )
    assert response.status_code == 200
    assert "candidate_plans" in response.json()
~~~

- [ ] Step 2: Run the tests and verify they fail.

Run: pytest tests/demo/test_actions.py tests/demo/test_endpoints.py -q
Expected: FAIL because the sample Action and API adapters are absent.

- [ ] Step 3: Register Actions with the platform ActionBroker.

Actions:
  - CreateChangeRequest;
  - RequestClarification;
  - ApproveRequirement;
  - ReplanSprint;
  - ReassignWorkItem;
  - AdjustCommitmentDate;
  - EscalateRisk;
  - RejectChangeRequest.

Every action must include parameter validation, approval policy, idempotency key construction, Mock adapter, outcome, and feedback creation.

- [ ] Step 4: Implement demo API routes.

Required routes:
  - GET /demo/requirements;
  - GET /demo/requirements/{requirement_id};
  - POST /demo/change-requests;
  - POST /demo/change-requests/{change_id}/impact;
  - GET /demo/work-items/{work_item_id}/forecast;
  - POST /demo/plans/{plan_id}/approve;
  - POST /demo/actions/{action_id}/execute;
  - GET /demo/feedback.

All routes use the platform Gate Engine and ActionBroker. No route writes directly to the sample tables.

- [ ] Step 5: Run the tests.

Run: pytest tests/demo/test_actions.py tests/demo/test_endpoints.py -q
Expected: all tests pass.

- [ ] Step 6: Commit sample Actions and API.

Run:
    git add src/software_delivery_demo/actions.py src/software_delivery_demo/app.py tests/demo/test_actions.py tests/demo/test_endpoints.py
    git commit -m "feat: expose software delivery mock actions"

## Task 10: Build the Streamlit business views and replay laboratory

**Files:**
- Create: src/software_delivery_demo/ui.py
- Create: tests/demo/test_ui_contract.py
- Modify: src/software_delivery_demo/app.py

**Interfaces:**
- render_requirement_inbox(api_client) -> None
- render_requirement_detail(api_client, requirement_id: str) -> None
- render_change_impact(api_client, change_id: str) -> None
- render_plan_comparison(api_client, change_id: str) -> None
- render_replay_lab(api_client, as_of_time: datetime) -> None

- [ ] Step 1: Write UI data-contract tests against API payloads.

~~~python
def test_change_impact_payload_contains_evidence_and_gate_status(api_client):
    payload = api_client.get_change_impact("chg-001")
    assert payload["evidence_refs"]
    assert payload["gate_status"]
    assert payload["candidate_plans"]


def test_forecast_payload_contains_baseline_and_model_versions(api_client):
    payload = api_client.get_forecast("wi-001")
    assert payload["baseline_version"]
    assert payload["feature_snapshot_id"]
    assert payload["model_version"]
~~~

- [ ] Step 2: Run the tests and verify they fail.

Run: pytest tests/demo/test_ui_contract.py -q
Expected: FAIL because the view functions and payload adapters are absent.

- [ ] Step 3: Implement the requirement inbox and detail views.

The inbox must separate:
  - new;
  - awaiting clarification;
  - high delivery risk;
  - pending approval;
  - completed with feedback.

The detail view must expose evidence, versions, lifecycle events, dependencies, predictions, and open questions.

- [ ] Step 4: Implement change impact and plan comparison.

The plan comparison view must show:
  - current plan;
  - candidate plans;
  - objective value;
  - completion P50/P80;
  - capacity and dependency constraints;
  - changes from baseline;
  - assumptions;
  - approval control.

- [ ] Step 5: Implement replay laboratory.

Allow the user to select an as_of_time, inject a ChangeRequest, adjust capacity or priority, rerun features and predictions, compare plans, and create a Mock Action request. The UI must display that replay data is historical and must not contain future fields.

- [ ] Step 6: Run the tests.

Run: pytest tests/demo/test_ui_contract.py -q
Expected: all tests pass.

- [ ] Step 7: Commit the UI and replay laboratory.

Run:
    git add src/software_delivery_demo/ui.py src/software_delivery_demo/app.py tests/demo/test_ui_contract.py
    git commit -m "feat: add delivery planning views and replay lab"

## Task 11: Wire the project stages into AI FDE gates and run the end-to-end scenario

**Files:**
- Create: projects/software-delivery-demo/config/stages.yaml
- Create: projects/software-delivery-demo/config/gates.yaml
- Create: tests/demo/test_end_to_end.py
- Create: tests/demo/test_gate_scenarios.py
- Create: projects/software-delivery-demo/evaluations/README.md

**Interfaces:**
- StageConfig has stage_id, input_artifact_kinds, output_artifact_kinds, hard_gate_ids, soft_gate_ids, and approver_role.
- DemoRunReport has stage_states, candidate_plan_count, feedback_count, and artifact_ids.
- GateScenarioReport has scenarios, gate_run_ids, and evidence_refs.
- build_demo_stage_config() -> StageConfig
- run_demo_pipeline(project_root: Path) -> DemoRunReport
- run_gate_scenarios(project_root: Path) -> GateScenarioReport

- [ ] Step 1: Write end-to-end tests before wiring the pipeline.

~~~python
def test_complete_demo_path_from_change_to_feedback(demo_project):
    report = run_demo_pipeline(demo_project)
    assert report.stage_states["ontology.design"] == "approved"
    assert report.stage_states["prediction.validation"] in {"approved", "blocked"}
    assert report.candidate_plan_count >= 3
    assert report.feedback_count >= 1


def test_future_completion_field_blocks_prediction_gate(demo_project):
    report = run_gate_scenarios(demo_project)
    assert report.scenarios["future_completion_leak"] == "blocked"


def test_infeasible_plan_is_not_released(demo_project):
    report = run_gate_scenarios(demo_project)
    assert report.scenarios["capacity_overload"] == "blocked"
~~~

- [ ] Step 2: Run the end-to-end tests and verify they fail.

Run: pytest tests/demo/test_end_to_end.py tests/demo/test_gate_scenarios.py -q
Expected: FAIL because stage configuration and pipeline wiring are absent.

- [ ] Step 3: Define project stages and gate bindings.

Required stage sequence:
  - project.charter;
  - requirements.alignment;
  - ontology.design;
  - data_product.build;
  - analytics.snapshot;
  - prediction.validation;
  - decision.optimization;
  - application.acceptance;
  - feedback.operation.

Each stage lists input artifact kinds, output artifact kinds, hard gates, soft gates, and required approver role.

- [ ] Step 4: Wire the pipeline.

The pipeline must:
  1. load the deterministic bundle;
  2. register evidence;
  3. build and validate the Ontology;
  4. build data products and run quality checks;
  5. build snapshots, labels, and features;
  6. run leakage checks;
  7. evaluate baseline and candidate models;
  8. build and validate candidate plans;
  9. expose and approve a Mock Action;
  10. record ActionOutcome and Feedback;
  11. emit a complete DemoRunReport.

- [ ] Step 5: Add adversarial gate fixtures.

Scenarios:
  - missing Requirement owner;
  - conflicting Stakeholder descriptions;
  - future actual_complete_at injected as a feature;
  - dependency cycle;
  - negative capacity;
  - no label history;
  - infeasible capacity plan;
  - Action without approval;
  - repeated Action idempotency;
  - user rejection with a reason.

- [ ] Step 6: Run the tests.

Run:
    pytest tests/demo/test_end_to_end.py tests/demo/test_gate_scenarios.py -q
Expected: all tests pass and every blocked scenario is explicitly recorded.

- [ ] Step 7: Run the complete repository test suite.

Run:
    pytest -q
    python -m compileall src
Expected: all tests pass and compileall exits 0.

- [ ] Step 8: Write the evaluation guide and commit the complete sample.

The guide must explain how to:
  - generate the fixture;
  - run the data products;
  - launch the API and Streamlit app;
  - run a change impact analysis;
  - view a forecast;
  - compare plans;
  - approve a Mock Action;
  - inspect Feedback;
  - reproduce every blocked gate scenario.

Run:
    git add projects/software-delivery-demo src/software_delivery_demo tests/demo
    git commit -m "feat: complete software delivery ontology demo"

## Plan-level acceptance checklist

- The simulator generates causal, time-ordered data with hidden truth isolated from features.
- The Ontology separates Requirement, ChangeRequest, WorkItem, Sprint, Dependency, Prediction, CandidatePlan, ActionOutcome, and Feedback.
- Historical snapshots exclude future observations.
- Required feature metadata and leakage rules are executable.
- Baseline forecasts always exist; ML releases only when policy passes.
- Candidate plans expose objectives, constraints, feasibility, and explanations.
- Mock Actions require approval, are idempotent, and create feedback.
- The business views expose evidence, gate status, forecasts, plan comparisons, and replay.
- The end-to-end path reaches ActionOutcome and Feedback.
- Every adversarial scenario either passes with evidence or is explicitly blocked.
- The full repository test suite passes before real connectors are considered.
