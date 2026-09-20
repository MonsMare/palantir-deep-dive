# Palantir Foundry / Ontology / AIP — Engineering Research

A structured engineering study of **Palantir Foundry, Ontology, and AIP**, focused on a practical question:

> How does an enterprise move from raw data and fragmented workflows to a governed decision system that connects data, semantics, models, AI, actions, security, and delivery?

This repository is not a product summary and not an attempt to reproduce Palantir feature-by-feature. It reorganises Palantir's public documentation into an **end-to-end engineering model** that can be studied, compared, and tested.

## What This Repository Demonstrates

This work is intended to show how I approach complex technology systems:

**Research → Decompose → Compare → Form a model → Derive engineering principles → Validate through follow-up experiments**

The research covers:

- data connectivity and integration
- use-case development and application construction
- analytics and model engineering
- Ontology and enterprise semantic modelling
- AIP, Agents, Logic, tools, and evaluation
- security, governance, and administration
- DevOps and product delivery
- decision loops, prediction, optimisation, Actions, and feedback

## Research Structure

The core research lives in [`wiki/`](wiki/README.md).

Recommended reading order:

1. [End-to-end engineering method](wiki/01-端到端工程方法.md)
2. [Ontology](wiki/04-Ontology本体.md)
3. [Data connectivity and integration](wiki/02-数据连接与集成.md)
4. [Use-case development](wiki/03-用例开发与应用构造.md)
5. [Analytics and model engineering](wiki/05-分析与模型工程.md)
6. [AIP / AI construction](wiki/06-AIP智能构造.md)
7. [Security and governance](wiki/07-安全治理管理.md)
8. [DevOps and product delivery](wiki/08-开发运维与交付.md)
9. [Research coverage and evidence](wiki/00-研究范围与证据.md)
10. [Ontology prediction-capability diagnosis](wiki/10-Ontology预测能力诊断.md)
11. [Ontology-oriented AI engineering methodology](wiki/11-Ontology化AI工程方法论.md)
12. [Data-product and unstructured-source pipeline methodology](wiki/12-数据产品与散乱资料管道方法论.md)
13. [Methodology acceptance checklist](wiki/13-方法论验收清单.md)
14. [Palantir-like engineering formula](wiki/14-Palantir-like工程公式.md)

> Most detailed research notes are currently written in Chinese. This English README serves as the international landing page.

## Evidence Discipline

The research prioritises first-party Palantir documentation and separates evidence by strength:

- **A-level** — architecture, lifecycle, and core-concept documentation
- **B-level** — product overviews, best practices, operations, and governance guidance
- **C-level** — APIs, SDKs, connectors, widgets, FAQs, and implementation examples

The goal is to avoid treating individual product features as isolated ideas. Instead, each source is interpreted in the context of the full engineering lifecycle.

See [Research Scope & Evidence](wiki/00-研究范围与证据.md) for the methodology.

## Core Interpretation

My current synthesis is:

> Foundry's engineering model begins with business decisions and user outcomes, turns source data into governed data products, maps them into an operational semantic layer through Ontology, and then lets analytics, models, applications, Agents, automation, permissions, and Actions operate against the same governed system of meaning.

The important part is not any single component. It is the **closed loop**:

```text
Business decision
  → governed data
  → semantic model
  → analysis / model / AI
  → action
  → observed outcome
  → feedback into the system
```

## Related Research

- **[AI-FDE-Shipyard](https://github.com/MonsMare/AI-FDE-Shipyard)** — engineering experiments and stress tests around Palantir-inspired AI/data workflows
- **[Enterprise-Semantic-Infrastructure-Research](https://github.com/MonsMare/Enterprise-Semantic-Infrastructure-Research)** — evidence-first Knowledge Runtime and enterprise semantic infrastructure research

## Why I Built This

I am interested in the layer between **technology research and system design**:

- Which parts of a successful platform are actually replicable?
- Which capabilities depend on years of organisational and data accumulation?
- What changes when LLMs and Agents become part of the enterprise stack?
- What should be copied, redesigned, or replaced?

This repository is one part of that broader investigation.

---

**Research focus:** Enterprise AI · Technology Strategy · Ontology · Decision Systems · AI Governance

> Independent research project. Not affiliated with Palantir Technologies.
