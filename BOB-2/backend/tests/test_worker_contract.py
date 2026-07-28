"""Static contracts for tenant-safe registered background tasks."""

from __future__ import annotations

import ast
from pathlib import Path

from app.worker.settings import WorkerSettings


def test_registered_tasks_require_organization_scope_as_first_statement():
    source_path = Path("app/worker/tasks.py")
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    functions = {
        node.name: node
        for node in module.body
        if isinstance(node, ast.AsyncFunctionDef)
    }

    registered_names = {
        function.name
        for function in WorkerSettings.functions
    }
    assert registered_names

    for name in registered_names:
        task = functions[name]
        argument_names = [argument.arg for argument in task.args.args]
        assert "organization_id" in argument_names
        assert task.body, f"{name} has no body"

        first_statement = task.body[0]
        assert isinstance(first_statement, ast.With), (
            f"{name} must enter tenant_scope as its first statement"
        )
        assert len(first_statement.items) == 1
        scope_call = first_statement.items[0].context_expr
        assert isinstance(scope_call, ast.Call)
        assert isinstance(scope_call.func, ast.Name)
        assert scope_call.func.id == "tenant_scope"
        assert len(scope_call.args) == 1
        assert isinstance(scope_call.args[0], ast.Name)
        assert scope_call.args[0].id == "organization_id"


def test_worker_retry_and_capacity_policy_is_explicit():
    assert WorkerSettings.max_jobs == 4
    assert WorkerSettings.job_timeout == 300
    assert WorkerSettings.keep_result == 3600
    assert WorkerSettings.max_tries == 3
    assert WorkerSettings.retry_jobs is True
    assert WorkerSettings.health_check_interval == 30
