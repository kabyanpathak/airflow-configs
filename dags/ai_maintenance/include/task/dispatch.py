"""Bob selects only specialists with a bounded, evidenced assignment."""
import json

from .run_agent import SPECIALISTS, _cached, _clear_handoff, _context, _invoke, _remaining, _save
from pathlib import Path
from .run_agent import prompt_text
from .runtime import require_run


def dispatch(config, run):
    if not require_run(config, run):
        return run
    cached = _cached(run, "dispatch")
    if cached is None and _remaining(run) <= 0:
        _save(run, "dispatch", {"specialists": [], "assignments": {}, "reason": "Soft deadline reached"}, config)
        (Path(run["state_dir"]) / "dispatch.meta.json").unlink(missing_ok=True)
        _save(run, "dispatch_handoff", {"status": "deferred", "reason": "Soft deadline reached"}, config)
        return run
    context = _context(config, run)
    context["owner_request"] = config.get("requested_task", "")
    prompt = prompt_text(config, "bob") + "\nDISPATCH MODE. Return exactly {specialists: [role], assignments: {role: bounded assignment with source evidence}, reason: string}. Only quinn, aria, mira, rowan are valid. Rowan requires an explicit owner request.\n" + json.dumps(context)
    try:
        result = cached or _invoke(config, run, "bob", prompt)
    except TimeoutError:
        result = {"specialists": [], "assignments": {}, "reason": "Dispatch invocation timed out; deferred"}
        _save(run, "dispatch_handoff", {"status": "unfinished", "reason": result["reason"]}, config)
        _save(run, "dispatch", result, config)
        (Path(run["state_dir"]) / "dispatch.meta.json").unlink(missing_ok=True)
        return run
    if not isinstance(result, dict) or set(result) != {"specialists", "assignments", "reason"}:
        raise ValueError("Invalid dispatch result")
    roles = result["specialists"]
    if not isinstance(roles, list) or any(not isinstance(role, str) or role not in SPECIALISTS for role in roles) or len(roles) != len(set(roles)):
        raise ValueError("Invalid specialist selection")
    if not isinstance(result["assignments"], dict) or set(result["assignments"]) != set(roles) or not all(isinstance(v, str) and v.strip() for v in result["assignments"].values()):
        raise ValueError("Each selected specialist requires an assignment")
    if not isinstance(result["reason"], str) or not result["reason"].strip():
        raise ValueError("Dispatch requires justification")
    if "rowan" in roles and not config.get("requested_task"):
        raise ValueError("Rowan requires an explicit owner request")
    _save(run, "dispatch", result, config)
    _clear_handoff(run, "dispatch")
    return run
