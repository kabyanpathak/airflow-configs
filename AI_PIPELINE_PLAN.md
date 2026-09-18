# Reusable Agentic AI Pipeline

Status: proposed implementation plan. No DAG implementation or schedule is enabled yet.

## Purpose

Build a reusable maintenance pipeline entirely within this Airflow project using DAG Factory. Project settings come from a vault task. Agents review code, investigate bugs, maintain documentation and task status, and synchronize actionable findings with Linear. The owner writes production implementation code and controls architecture and product direction.

## Required DAG structure

```text
dags/
  ai_maintenance/
    ai_maintenance.py           # Registration entry point; same name as folder
    Configs/
      maintenance.yaml          # DAG Factory definition and dependencies
    include/
      task/
        vault.py                # Returns the run's configuration dictionary
        eligibility.py
        prepare_branch.py
        dispatch.py
        run_agent.py
        review.py
        publish.py
        finalize.py
      callbacks/                # Reserved for reusable failure callbacks later
    AI/
      prompts/
        shared.md
        bob.md
        alice.md
        mira.md
        quinn.md
        aria.md
        rowan.md
      schemas/
    .airflowignore
```

Use this structure for new DAG folders. Existing DAGs are not renamed as part of this implementation. Ignore `include/`, `AI/`, and configuration files during Airflow DAG discovery while leaving the registration entry point discoverable. The loader explicitly reads `Configs/`. Ignore rules do not prevent callable imports or reading prompts and YAML.

## Vault and callable convention

- `start` is an EmptyOperator.
- The next task calls a function in `include/task/vault.py`, returning a Python dictionary through XCom.
- The dictionary provides project ID, repository/base branch, disposable review branch/worktree, relevant documentation and backlog paths, allowed changes, validation commands, Linear destination, model profiles, and execution limits.
- Secrets live in the local `.env` and are explicitly injected into the runtime. The vault contains environment-variable names, not resolved secret values. Only the task that needs a secret resolves it; secrets must not enter XCom, prompts, or logs.
- YAML supplies explicit `op_kwargs` by pulling values from the vault task. Validate native types rather than assuming templated dictionaries or booleans remain correctly typed.
- Business actions live in Python files under `include/task/`, including actions supported by provider operators. Callables may use provider hooks/SDKs; any operator delegation must preserve the required execution and cancellation behavior.
- Agent stages may be organized into TaskGroups. Each selected stage remains visible in Airflow.
- A final EmptyOperator marks `end`. Its dependencies must preserve failures; cleanup must not turn a failed run into success.
- Failure-email callbacks are deferred. Create the reserved location without configuring email delivery now.

## Workflow

```text
start -> vault -> eligibility / project lock -> prepare local review branch
      -> inspect changes and saved findings -> Bob dispatch
      -> selected specialist tasks -> Bob review -> Alice audit
      -> apply approved proposals to review worktree / synchronize Linear
      -> save handoff and report -> end
```

Cleanup and evidence preservation also run on failure. If nothing relevant changed and no findings or requests are due, record a no-op without model calls. Persist last-reviewed commit/content identifiers internally to avoid repeatedly reviewing unchanged material; there is no separate user-facing snapshot workflow.

## Local weekly review branch

- Use a dedicated local Git branch, initially `codex/ai-maintenance`, checked out in a separate, stable worktree directory. Both names/paths are configurable per project.
- The owner can `cd` into that worktree to inspect files and use `git diff`; a branch itself is not a directory.
- At the first eligible run of each new weekly slot, recreate the disposable branch/worktree from the configured local base branch. Do not push or create GitHub branches.
- Retries within the same slot reuse that run's branch and artifacts rather than deleting progress again.
- Reset only the explicitly designated AI branch/worktree. Keep the owner's normal checkout untouched. The review workspace is disposable; changes the owner wants to retain must be copied or committed elsewhere before its next refresh.
- Default input is committed content on the selected base. A separately configured option may include relevant uncommitted work through an isolated copy; never silently omit it while claiming it was reviewed.
- Put approved documentation/status changes and any permitted test proposals in the review worktree. Do not automatically apply them to the owner's main checkout. Automatic commits remain off initially.
- Persist audit logs, finding identities, Linear mappings, pending external actions, and unfinished-work handoffs outside the disposable worktree.
- Revalidate unfinished work against the new base before continuing. Weekly branch refresh must not erase issue history or manufacture duplicate findings.

## Agent roles

| Agent | Responsibility |
| --- | --- |
| Bob | Review changes, assign bounded work, assess specialist evidence, approve maintenance proposals, and summarize results. |
| Quinn | Run existing checks, investigate bugs and regressions, and identify missing tests. New test authorship is an explicit configuration option. |
| Aria | Investigate memory, CPU, performance, timers, concurrency, and idle/background behavior; distinguish measurements from hypotheses. |
| Mira | Propose updates to affected documentation, README status, existing task checkboxes, and verified project records. |
| Alice | Independently audit recorded activity, actual file changes, permissions, and evidence. Deterministic controls enforce boundaries. |
| Rowan | Prepare learning references and context for an owner-selected task, only when requested. |

Bob uses the strongest configured model; specialists use suitable configurable profiles. Run only justified specialists. Initially limit specialist concurrency to one. Agents may not implement production features/fixes, redefine acceptance criteria, or invent a new roadmap.

## Schedule and finishing the day

- Initially run once weekly, Sunday at **12:00 PM America/Los_Angeles**.
- Use the Mac when awake with Docker/Airflow running. The browser may remain closed. Skip missed runs; disable historical catchup and reject stale executions outside the configured start tolerance.
- Soft deadline: **1:00 PM**. Stop new investigations and enter wind-down. Tell running agents that the day is over where the execution interface supports it; all assignments also carry the deadline in advance.
- Preserve evidence, partial outputs, proposed changes, and concise unfinished-work handoffs. Finish bounded synthesis/publication where feasible; journal anything remaining for later.
- If a model invocation cannot receive a live wind-down message, stop it safely and preserve recorded output. Do not assume a prompt alone enforces a deadline.
- Hard deadline: **2:00 PM**. Enforce cancellation of remaining agent processes and prevent further publication. Recovery must be possible from already persisted artifacts.
- Prefer finishing within one hour. Never create work merely to use the available time.
- Keep one active run per project and a durable weekly slot record. Later support two to four configured days per week with the same workflow.

## Linear behavior

- Publish actionable bugs/investigations with evidence, severity, confidence, reproduction or verification steps, and a stable finding identity.
- Deduplicate and update existing findings. Do not bulk-import the development backlog or invent feature tasks.
- Update existing development issues only when explicitly mapped to the pipeline.
- Automatically close enrolled issues only after their specific resolution/acceptance criteria have been verified. A fix existing solely on the disposable AI branch is not a completed owner implementation.
- Record resolution evidence, respect human overrides, and reopen enrolled findings when a regression is verified. Leave partial or uncertain work open.
- Journal external actions and reconcile ambiguous responses before retrying, avoiding duplicate issues and comments. A Linear outage must not require repeating completed AI review.

## Implementation and verification

1. Build the exact folder convention, DAG Factory loader/YAML, start/end markers, and vault-to-op_kwargs flow.
2. Implement project validation, weekly eligibility, isolated branch preparation, durable state, and bounded execution.
3. Adapt existing agent prompts and repair change detection, dispatch, structured validation, and audit gaps.
4. Add review-worktree proposals, Linear creation/update/closure, and recoverable publication.
5. Test with fake agents and mocked Linear: imports, XCom types, secret exclusion, branch refresh/retry behavior, owner-checkout preservation, no-op runs, deadlines, failed tasks, deduplication, and evidence-based closure.
6. Perform a controlled live review before enabling weekly operation. Keep callbacks/email for a later change.

After plan approval, implementation and independent testing may be assigned to separate subagents. Required live configuration includes the destination repository/base branch, worktree location, Linear destination, and model credentials. Docker must have explicit access to the configured local repository paths.
