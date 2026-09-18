"""Bounded, read-only model execution. Models return proposals, never commands."""
from __future__ import annotations

import fnmatch
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from .runtime import read_json, require_run, write_json

AI = Path(__file__).resolve().parents[2] / "AI"
ROLES = {"bob", "alice", "quinn", "aria", "mira", "rowan"}
SPECIALISTS = {"quinn", "aria", "mira", "rowan"}


PROVIDER_ENDPOINTS = {
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
}


def prompt_text(config, role=None):
    name = config['agents'][role]['prompt'] if role else config['shared_prompt']
    path = Path(name)
    if not path.is_absolute():
        path = AI.parent / path
    return path.read_text()


def _remaining(run, wind_down=False):
    key = "hard_deadline" if wind_down else "soft_deadline"
    deadline = datetime.fromisoformat(run[key].replace("Z", "+00:00"))
    if deadline.tzinfo is None:
        raise ValueError("Deadlines must include a timezone")
    return (deadline - datetime.now(timezone.utc)).total_seconds()


def _redact(value, config):
    text = value if isinstance(value, str) else json.dumps(value)
    # Redact all explicitly named secrets, including Linear's credentials.
    def walk(item):
        if isinstance(item, dict):
            for key, val in item.items():
                if key.endswith("_env") and isinstance(val, str):
                    secret = os.environ.get(val)
                    if secret:
                        yield secret
                else:
                    yield from walk(val)
        elif isinstance(item, list):
            for child in item:
                yield from walk(child)
    for secret in sorted(set(walk(config)), key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    return text


def _save(run, name, value, config, dependency_digest=None):
    root = Path(run["state_dir"])
    root.mkdir(parents=True, exist_ok=True)
    path = root / (name + ".json")
    write_json(path, json.loads(_redact(value, config)))
    metadata = {"base_commit": run.get("base_commit"), "config_digest": run.get("config_digest")}
    if dependency_digest is not None:
        metadata["dependency_digest"] = dependency_digest
    write_json(root / (name + ".meta.json"), metadata)


def _load(run, name):
    path = Path(run["state_dir"]) / (name + ".json")
    return json.loads(path.read_text()) if path.is_file() else None


def _cached(run, name, dependency_digest=None):
    metadata = read_json(Path(run["state_dir"]) / (name + ".meta.json"), {})
    expected = {"base_commit": run.get("base_commit"), "config_digest": run.get("config_digest")}
    if dependency_digest is not None:
        expected["dependency_digest"] = dependency_digest
    if run.get("base_commit") and metadata == expected:
        return _load(run, name)
    return None


def _safe_path(path):
    if not isinstance(path, str):
        return False
    p = Path(path)
    return (isinstance(path, str) and bool(path) and not p.is_absolute()
            and ".." not in p.parts and ".git" not in p.parts
            and not any(part.startswith(".env") for part in p.parts))


def _clear_handoff(run, role):
    root = Path(run["state_dir"])
    for suffix in (".json", ".meta.json"):
        (root / (role + "_handoff" + suffix)).unlink(missing_ok=True)


def _context(config, run):
    root = Path(run["worktree"]).resolve()
    result = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                            capture_output=True, check=True, timeout=10)
    tracked = result.stdout.decode().split("\0")
    selected = run.get("changed_paths", [])
    for paths in config.get("paths", {}).values():
        if isinstance(paths, list):
            selected = selected + paths
    selected = list(dict.fromkeys(selected + tracked))
    budget = 120_000
    files = {}
    for name in selected:
        if not _safe_path(name):
            continue
        path = root / name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
            continue
        if any(word in name.lower() for word in ("secret", "credential", "private_key", "id_rsa")):
            continue
        if path.suffix.lower() not in {".py", ".md", ".rst", ".txt", ".yaml", ".yml", ".toml", ".js", ".ts", ".tsx", ".json", ".sql", ".go", ".rs", ".c", ".cpp", ".h", ".hpp", ".java", ".kt", ".swift", ".cs", ".sh", ".html", ".css", ".vue", ".svelte", ".rb", ".php", ".dart"} and path.name not in {"Dockerfile", "Makefile"}:
            continue
        if path.stat().st_size > min(30_000, budget):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        files[name] = text
        budget -= len(text)
        if budget <= 0:
            break
    state = Path(run["project_state_dir"])
    history = {name: read_json(state / (name + ".json")) for name in ("findings", "linear_findings", "last_handoff", "last_review")}
    return {"files": files, "coverage": "Bounded file sample; omitted files are not reviewed.",
            "saved_history": history,
            "changed_paths": run.get("changed_paths", []),
            "permissions": {"allowed_changes": config["allowed_changes"], "allow_test_authorship": config.get("allow_test_authorship", False)},
            "validation": _load(run, "validation"),
            "deadlines": {key: run[key] for key in ("soft_deadline", "hard_deadline")}}


def _http_worker(connection, endpoint, key, payload, timeout):
    try:
        request = Request(endpoint.rstrip("/") + "/chat/completions",
                          data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("Response too large")
        result = json.loads(raw)["choices"][0]["message"]["content"]
        connection.send((True, result))
    except Exception:
        # Provider error bodies and URLs can contain credentials: never persist them.
        connection.send((False, "Model request failed"))
    finally:
        connection.close()


def _invoke(config, run, role, prompt, wind_down=False):
    if not require_run(config, run):
        raise RuntimeError("Cannot invoke model for ineligible or no-op run")
    remaining = _remaining(run, wind_down)
    if remaining <= 0:
        raise TimeoutError("Agent deadline reached")
    model = config["agents"][role]
    key = os.environ.get(model["api_key_env"])
    if not key:
        raise ValueError("Model credential is unavailable")
    timeout = min(float(config["limits"].get("request_timeout_seconds", 120)), remaining)
    payload = {"model": model["model"],
               "messages": [{"role": "system", "content": prompt_text(config)},
                            {"role": "user", "content": _redact(prompt, config)}],
               "response_format": {"type": "json_object"},
               ("max_completion_tokens" if model["provider"] == "openai" else "max_tokens"): config["limits"].get("max_output_tokens", 4096)}
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_http_worker, args=(child, PROVIDER_ENDPOINTS[model["provider"]], key, payload, timeout))
    process.start()
    child.close()
    try:
        if not parent.poll(timeout):
            raise TimeoutError("Model request cancelled at execution deadline")
        ok, output = parent.recv()
        if not ok:
            raise RuntimeError(output)
        if _remaining(run, wind_down) <= 0:
            raise TimeoutError("Model response arrived after deadline")
        return json.loads(_redact(output, config))
    finally:
        if process.is_alive():
            process.terminate()
        process.join(2)
        if process.is_alive():
            process.kill()
            process.join(2)
        parent.close()


def _strings(value, nonempty=False):
    return isinstance(value, list) and (bool(value) or not nonempty) and all(isinstance(x, str) and x.strip() for x in value)


def validate_output(value, config):
    required = {"summary", "findings", "proposals", "approved_proposal_ids", "approved"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("Agent output has invalid fields")
    if not isinstance(value["summary"], str) or type(value["approved"]) is not bool or not _strings(value["approved_proposal_ids"]):
        raise ValueError("Invalid review result")
    if not isinstance(value["findings"], list) or not isinstance(value["proposals"], list):
        raise ValueError("Findings and proposals must be lists")
    for finding in value["findings"]:
        fields = {"identity", "title", "description", "kind", "severity", "confidence", "evidence", "verification_steps", "status", "resolution_evidence"}
        if not isinstance(finding, dict) or set(finding) != fields:
            raise ValueError("Invalid finding fields")
        if not all(isinstance(finding[k], str) and finding[k].strip() for k in ("identity", "title", "description")):
            raise ValueError("Missing finding identity or description")
        if finding["kind"] not in {"bug", "investigation"} or finding["severity"] not in {"critical", "high", "medium", "low"}:
            raise ValueError("Invalid finding category")
        if type(finding["confidence"]) not in (int, float) or not 0 <= finding["confidence"] <= 1:
            raise ValueError("Invalid finding confidence")
        if not _strings(finding["evidence"], True) or not _strings(finding["verification_steps"], True):
            raise ValueError("Findings require evidence and verification steps")
        if finding["status"] not in {"open", "resolved"} or not _strings(finding["resolution_evidence"], finding["status"] == "resolved"):
            raise ValueError("Resolution requires explicit evidence")
    ids = set()
    for proposal in value["proposals"]:
        if not isinstance(proposal, dict) or set(proposal) != {"id", "path", "content", "reason"} or not all(isinstance(x, str) for x in proposal.values()):
            raise ValueError("Invalid proposal")
        path = proposal["path"]
        if not _safe_path(path) or not any(fnmatch.fnmatchcase(path, pattern) for pattern in config["allowed_changes"]):
            raise ValueError("Proposal path is outside allowed changes")
        is_test = "tests" in Path(path).parts or Path(path).name.startswith("test_")
        if not (Path(path).suffix.lower() in {".md", ".rst", ".txt"} or (is_test and config.get("allow_test_authorship") is True)):
            raise ValueError("Production code proposals are prohibited")
        if not proposal["id"] or proposal["id"] in ids:
            raise ValueError("Proposal IDs must be unique")
        ids.add(proposal["id"])
    return value


def run_agent(config, run, role):
    if role not in SPECIALISTS:
        raise ValueError("Unknown specialist")
    if not require_run(config, run):
        return run
    cached = _cached(run, role)
    if cached is not None:
        validate_output(cached, config)
        _clear_handoff(run, role)
        return run
    dispatch = _load(run, "dispatch") or {}
    if role not in dispatch.get("specialists", []):
        return run
    if _remaining(run) <= 0:
        _save(run, role + "_handoff", {"status": "deferred", "reason": "Soft deadline reached"}, config)
        return run
    prompt = prompt_text(config, role)
    context = _context(config, run)
    context["assignment"] = dispatch["assignments"][role]
    try:
        output = _invoke(config, run, role, prompt + "\n" + json.dumps(context))
        validate_output(output, config)
        if output["approved"] or output["approved_proposal_ids"]:
            raise ValueError("Specialists cannot approve proposals")
        _save(run, role, output, config)
        _clear_handoff(run, role)
    except TimeoutError:
        _save(run, role + "_handoff", {"status": "unfinished", "reason": "Invocation cancelled; no completed response"}, config)
    return run
