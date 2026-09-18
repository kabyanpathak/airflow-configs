"""Independent reviews approve only proposal IDs already present in evidence."""
import json
import hashlib
import subprocess

from .run_agent import SPECIALISTS, _cached, _clear_handoff, _context, _invoke, _load, _save, validate_output
from .run_agent import prompt_text
from .runtime import require_run


def review(config, run, role="bob"):
    if role not in {"bob", "alice"}:
        raise ValueError("Review role must be Bob or Alice")
    if not require_run(config, run):
        return run
    evidence = {name: _load(run, name) for name in sorted(SPECIALISTS)}
    proposals = {p["id"]: p for report in evidence.values() if report for p in report["proposals"]}
    all_ids = [p["id"] for report in evidence.values() if report for p in report["proposals"]]
    if len(all_ids) != len(proposals):
        raise ValueError("Specialist proposal IDs collide")
    if role == "alice":
        evidence["bob_review"] = _load(run, "bob_review")
    evidence["dispatch"] = _load(run, "dispatch")
    evidence["handoffs"] = {name: _load(run, name + "_handoff") for name in sorted(SPECIALISTS | {"dispatch"})}
    context = _context(config, run)
    diff = subprocess.run(["git", "-C", run["worktree"], "diff", "--no-ext-diff", "HEAD"], capture_output=True, text=True, check=True, timeout=10)
    context["actual_worktree_diff"] = diff.stdout[:120000]
    context["recorded_activity"] = evidence
    context["permissions"] = {"allowed_changes": config["allowed_changes"], "allow_test_authorship": config.get("allow_test_authorship", False)}
    prompt = prompt_text(config, role) + "\nREVIEW MODE. Return the shared result schema. Do not author new proposals; approve existing IDs only.\n" + json.dumps(context, sort_keys=True)
    # Reviews depend on actual evidence, not just the base commit. A retry may
    # complete previously deferred specialists while keeping the same base.
    dependency_digest = hashlib.sha256((prompt_text(config) + prompt + diff.stdout).encode()).hexdigest()
    try:
        result = validate_output(_cached(run, role + "_review", dependency_digest) or _invoke(config, run, role, prompt, wind_down=True), config)
    except TimeoutError:
        _save(run, role + "_handoff", {"status": "unfinished", "reason": "Review invocation cancelled at deadline"}, config)
        raise
    if result["proposals"]:
        raise ValueError("Review cannot add proposals")
    if not set(result["approved_proposal_ids"]).issubset(proposals):
        raise ValueError("Review approved nonexistent proposals")
    if role == "alice":
        bob = evidence["bob_review"] or {}
        if not set(result["approved_proposal_ids"]).issubset(bob.get("approved_proposal_ids", [])):
            raise ValueError("Alice can approve only Bob-approved proposals")
    _save(run, role + "_review", result, config, dependency_digest)
    _clear_handoff(run, role)
    return run
