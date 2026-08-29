# PreFlight

### Deployment Survival Engine

**Know what breaks before production does.**

PreFlight analyzes a proposed software change, traces its real downstream dependencies, evaluates deployment and rollback risk, and produces a deterministic deployment verdict backed by source-level evidence.

> **Change → Evidence → Causal Graph → Blast Radius → Risk → Policy → Verdict**

[Live Demo](https://preflight-delta-weld.vercel.app/) · [Architecture](docs/ARCHITECTURE.md) · [Determinism Contract](docs/DETERMINISM.md) · [Limitations](docs/LIMITATIONS.md)

---

## The problem

A deployment can be technically valid and still be operationally unsafe.

Consider:

```text
ALTER TABLE users
DROP COLUMN phone_number;

The migration itself succeeds.

But somewhere downstream:

users.phone_number
       │
       │ DB_READ
       ▼
UserService
       │
       │ HTTP_CALL
       ▼
ProfileAPI
       │
       │ API_CONSUMES
       ▼
ProfileClient

The database is healthy.

The build may be green.

The deployment can still break production.

The hard problem is not detecting that a file changed.

The hard problem is determining:

What actually depends on the changed entity?
How far does the impact propagate?
Which contracts become incompatible?
Can the previous version still operate against the new state?
Is there enough evidence to make a safe decision?
Can the decision be traced back to the source evidence that produced it?

PreFlight is built around those questions.

What PreFlight does

PreFlight treats a deployment as a causal dependency problem.

Given a repository or two repository snapshots, it constructs an evidence-backed representation of the change and evaluates its survivability.

                     REPOSITORY
                         │
                         ▼
                ┌─────────────────┐
                │ Secure Ingestion│
                └────────┬────────┘
                         │
                         ▼
                  CHANGE / DIFF
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
       SOURCE           SQL           OPENAPI
      ANALYSIS       ANALYSIS         ANALYSIS
          │              │              │
          └──────────────┼──────────────┘
                         ▼
                 EVIDENCE GRAPH
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
     BLAST RADIUS     API RISK      ROLLBACK
          │              │              │
          └──────────────┼──────────────┘
                         ▼
                 DEPLOYMENT POLICY
                         │
                         ▼
              ┌──────────────────────┐
              │      VERDICT         │
              │                      │
              │ SAFE                 │
              │ CAUTION              │
              │ DO_NOT_DEPLOY        │
              │ UNKNOWN              │
              └──────────┬───────────┘
                         │
                         ▼
                 EVIDENCE / PROOF

The important distinction is that the UI is not generating a story around a verdict.

The graph, findings, risk factors, rollback assessment, and provenance are all derived from the analysis result.

A deployment verdict is only useful if you can prove it

PreFlight's central object is the Evidence Graph.

A finding is connected to the evidence that produced it.

For example:

DROP_COLUMN
    │
    ▼
users.phone_number
    │
    │ DB_READ
    ▼
UserService
    │
    │ HTTP_CALL
    ▼
ProfileAPI
    │
    │ API_CONSUMES
    ▼
ProfileClient
    │
    ▼
DEPLOYMENT FINDING
    │
    ▼
RISK FEATURE
    │
    ▼
POLICY EVALUATION
    │
    ▼
DO_NOT_DEPLOY

The frontend exposes this graph interactively.

Selecting evidence can lead back to:

source file
line number
analyzer
affected entity
relationship
finding
risk contribution
decision

This makes the graph an interactive proof surface, rather than a decorative dependency diagram.

The four verdict states

PreFlight intentionally separates safe, unsafe, and unknown.

Verdict	Meaning
SAFE	Available evidence supports deployment safety
CAUTION	Risk exists but does not cross a blocking policy
DO_NOT_DEPLOY	Blocking evidence was found
UNKNOWN	Required evidence was unavailable or insufficient

The last one is critical.

UNKNOWN ≠ SAFE

If PreFlight cannot establish something from available evidence, it does not silently convert uncertainty into confidence.

For example:

FORWARD: UNKNOWN

Reason:
No next-version application snapshot was supplied.
Compatibility cannot be established from available evidence.

That is deliberate.

Deterministic decisions

PreFlight separates decision-making from explanation.

The decision engine is deterministic.

The explanation layer is not authoritative.

                 INPUT
                   │
                   ▼
          ┌──────────────────┐
          │ Deterministic    │
          │ Analysis Engine  │
          └────────┬─────────┘
                   │
                   ▼
          Evidence + Findings
                   │
                   ▼
             Risk Features
                   │
                   ▼
             Policy Engine
                   │
                   ▼
               VERDICT
                   │
                   ▼
             Decision Hash
                   │
                   └─────────────┐
                                 ▼
                         Explanation Layer
                              (advisory)

AI does not determine:

the verdict
the risk score
the evidence graph
policy outcomes
decision hashes

AI explains the result after the deterministic engine has produced it.

Engine decides. AI explains.

Determinism is a product requirement

For identical inputs:

INPUT
  ↓
same analysis
  ↓
same evidence
  ↓
same risk
  ↓
same policy
  ↓
same verdict
  ↓
same decision hash

PreFlight uses canonical serialization and deterministic hashing to make the decision reproducible.

The project explicitly tests that decision hashes remain stable across runs.

See docs/DETERMINISM.md.

Counterfactual analysis

PreFlight can run an alternative analysis and allow the user to switch between the two real engine outputs.

For example:

CURRENT ANALYSIS

DROP_COLUMN
DO_NOT_DEPLOY
Risk: 100
17 graph nodes

versus:

ALTERNATIVE ANALYSIS

ADD_COLUMN
SAFE
Risk: 9
7 graph nodes

Selecting an analysis replaces the active report with that exact returned payload.

The transition does not:

refetch the analysis
recompute the result
invent an intermediate verdict
fabricate an intermediate risk score

The displayed endpoints are real engine outputs.

The animation is presentation only.

Multi-change convergence

Real releases contain multiple changes.

Those changes can converge on the same downstream system.

PreFlight preserves both causal paths:

CHANGE A ──────────┐
                   │
                   ▼
              ComplianceAPI
                   ▲
                   │
CHANGE B ──────────┘

The shared entity remains one entity while each causal path remains inspectable.

This matters because naïvely deduplicating graph nodes can destroy the very evidence needed to understand why a deployment is risky.

Rollback is analyzed separately

A deployment is not survivable merely because the forward migration appears valid.

PreFlight evaluates rollback feasibility as its own analysis dimension.

                 PROPOSED STATE
                      │
             ┌────────┴────────┐
             ▼                 ▼
        FORWARD PATH      ROLLBACK PATH
             │                 │
             ▼                 ▼
       New application    Old application
       + new schema       + new schema
             │                 │
             ▼                 ▼
          RESULT            RESULT

Example:

ROLLBACK: UNSAFE

Failure point:
OLD APPLICATION expects users.phone_number,
which the proposed schema no longer contains.

If the required next-version snapshot is missing:

FORWARD: UNKNOWN

PreFlight does not infer compatibility from absence of evidence.

Analysis capabilities
Repository ingestion
ZIP archive ingestion
archive validation
extraction limits
controlled file handling
manifest generation
unsupported-project detection
no uploaded-code execution
Static analysis
Python
Kotlin
Tree-sitter based parsing
semantic dependency extraction
typed graph construction
deterministic traversal
Database analysis
SQL migration parsing
SQLGlot
schema comparison
destructive migration detection
changed-column analysis
downstream dependency tracing
API analysis
OpenAPI contract analysis
compatibility findings
affected endpoint detection
contract evidence
Deployment analysis
blast-radius calculation
multi-hop dependency traversal
multi-change analysis
convergence detection
rollback feasibility
deterministic risk scoring
deterministic policy evaluation
Evidence system
source provenance
line-level evidence
typed relationships
evidence graph
causal-path inspection
convergence visualization
Decision system
SAFE
CAUTION
DO_NOT_DEPLOY
UNKNOWN
deterministic decision hashes
advisory AI explanation
Architecture
preflight/
│
├── src/preflight/
│   │
│   ├── ingestion/
│   │   ├── archive security
│   │   ├── repository extraction
│   │   └── multipart handling
│   │
│   ├── parsers/
│   │   ├── Python
│   │   ├── Kotlin
│   │   └── diagnostics
│   │
│   ├── graph/
│   │   ├── graph construction
│   │   ├── traversal
│   │   ├── blast radius
│   │   └── serialization
│   │
│   ├── orchestration/
│   │   ├── pipeline
│   │   ├── models
│   │   └── analysis execution
│   │
│   ├── schema.py
│   ├── semantic.py
│   ├── structural_diff.py
│   ├── rollback_truth.py
│   └── api_contract.py
│
├── frontend/
│   ├── app/
│   ├── components/
│   ├── hooks/
│   └── lib/
│
├── fixtures/
├── scripts/
├── tests/
├── docs/
│
└── pyproject.toml

The backend is intentionally structured so that analysis logic is separated from HTTP transport and presentation.

API
Health
GET /health

Response:

{
  "engine": "deterministic",
  "status": "online"
}
Analyze a registered scenario
POST /api/analyze
Content-Type: application/json
Analyze an uploaded repository
POST /api/analyze-project
Content-Type: multipart/form-data
Compare two repository snapshots
POST /api/analyze-change
Content-Type: multipart/form-data
old=<old-repository.zip>
new=<new-repository.zip>
Quick start
Requirements
Python 3.10+
Node.js 20+
npm
Backend
git clone https://github.com/srthck/preflight.git
cd preflight

pip install -e ".[dev]"

Run the complete test suite:

python -m pytest -q

Start the API:

python scripts/preflight_api.py 8000

Verify:

curl http://127.0.0.1:8000/health
Frontend
cd frontend
npm install
npm run dev

Create:

frontend/.env.local

with:

NEXT_PUBLIC_API_URL=http://127.0.0.1:8000

Then open:

http://localhost:3000
Verification

The repository currently contains:

491 tests passed

Automated gates include:

pytest                  PASS
ruff                    PASS
mypy --strict           PASS
TypeScript              PASS
ESLint                  PASS
Next.js production build PASS
API integration         PASS
Evidence graph contract PASS
Decision hashes         STABLE

The frontend has also been exercised in Chrome through Playwright at:

1440 × 900
768 × 1024
390 × 844
reduced-motion

Browser-verified flows include:

destructive analysis
SAFE analysis
UNKNOWN analysis
unsupported input
evidence graph
source evidence inspection
convergence
two-version analysis
counterfactual selection
keyboard graph traversal
reduced-motion behaviour
upload lifecycle
responsive layouts
verdict auto-scroll
judge mode
Security posture

PreFlight analyzes repository archives without executing the uploaded application's code.

The ingestion layer is designed around controlled analysis of untrusted archives.

Current protections include:

archive validation
bounded extraction
upload-size limits
controlled file handling
no dynamic execution of uploaded application code
no network dependency in the deterministic analysis core
no local extraction-path leakage in API responses
explicit unsupported/unknown states

PreFlight is a static-analysis and deployment-risk system.

It is not a sandbox for running arbitrary uploaded applications.

Engineering principles
Evidence over assumption

Every displayed claim should have a corresponding backend source.

Determinism over probabilistic verdicts

The same input should produce the same decision.

UNKNOWN over fabricated certainty

Missing evidence is represented as missing evidence.

Causality over file lists

A changed file is not the same thing as an affected system.

Separation of decision and explanation

The explanation layer cannot rewrite the deterministic result.

Security over convenience

Uploaded repositories are treated as untrusted input.

Product claims require verification

Implemented does not automatically mean verified.

Browser behaviour is tested where browser behaviour matters.

Known limitations

PreFlight is deliberately honest about its boundaries.

Static analysis cannot discover every dynamic dependency.
Dynamic SQL can limit dependency discovery.
Runtime behaviour is not equivalent to static evidence.
Feature-to-policy attribution is currently aggregated through a POLICY EVALUATION junction because the decision engine does not expose precise feature→rule attribution.
Counterfactual analysis currently requires an available alternative scenario.
Native browser tooltips are used for some long graph labels.
Long-session memory profiling has not been comprehensively benchmarked.
Performance measurements are environment-specific.
PreFlight does not replace integration tests, staging, observability, deployment controls, or production monitoring.

See docs/LIMITATIONS.md.

What PreFlight is not

PreFlight is not:

a CI build system
a conventional linter
a vulnerability scanner
a replacement for integration tests
a runtime APM
a deployment platform
an AI chatbot that guesses whether a change is safe

It is a deployment survivability analysis layer.

Its job is to connect a proposed change to the systems that depend on it and determine whether the available evidence supports shipping it.

Why the project exists

Modern software systems are increasingly distributed across:

databases
backend services
APIs
mobile clients
configuration
multiple repository versions
independently deployed components

The blast radius of a change therefore exists across boundaries.

Traditional diff tooling tells you:

"What changed?"

PreFlight is designed to answer:

"What does that change reach?"
"How does it propagate?"
"What evidence proves the impact?"
"Can we still roll back?"
"What does policy say?"
"How certain are we?"

That is the gap PreFlight targets.

Project status

PreFlight currently has a working deterministic analysis pipeline, interactive evidence graph, two-version comparison, rollback analysis, counterfactual analysis, production API, and deployed web interface.

The system is still an engineering project rather than a claim of universal deployment correctness.

The strongest claim it makes is narrower:

When PreFlight has the required evidence, it can turn a software change into a reproducible deployment-risk decision whose causal path can be inspected.

That boundary is intentional.

License

MIT


### One important correction before you paste this

Your old README says:

> `Day 2 Tree-sitter static parser — Planned`  
> `Day 3 NetworkX graph extraction — Planned`  
> `Day 6 SQLGlot — Planned`  
> `Day 8 Rollback — Planned`

That is **actively hurting you now** because you've already implemented those things. It makes the repository look unfinished even though the product is much further along.

Also, I would **not** put "Top 0.1%", "world-class", "Apple-level", "production-ready", or "enterprise-grade" in the README. If the product deserves those labels, the reviewer should conclude that from the evidence. Claiming them yourself weakens the impression.

And one more thing: **don't overdo badges.** Three to five factual badges are stronger than 15 decorative ones.

If you want the README to actually compete with exceptional GitHub projects, the **next upgrade isn't more prose**. It's adding **a killer hero screenshot/GIF + a 30-second architecture visual + a concrete before/after analysis example** immediately under the opening. That would make a much bigger difference than another 1,000 words.