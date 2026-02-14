"""Dependency-aware task ordering.

Pure logic module with no I/O dependencies. Computes processing order
based on task dependencies, ensuring children are processed before parents
and blocked tasks are deferred.
"""

from __future__ import annotations


def compute_processing_order(
    tasks: list[dict],
    dependencies: dict[str, list[dict]],
) -> list[dict]:
    """Reorder tasks respecting dependency constraints.

    Rules:
    1. Tasks with all dependencies completed -> ready (maintain existing sort)
    2. Tasks with incomplete dependencies -> deferred to end
    3. Parent tasks with undone children -> children queued first

    Args:
        tasks: List of task dicts from MCP (must have "id", "status" fields).
        dependencies: Map of task_id -> list of dependency task dicts
            (each with "id" and "status" fields).

    Returns:
        Reordered list of task dicts.
    """
    if not tasks:
        return []

    task_by_id = {t["id"]: t for t in tasks}
    task_ids_in_list = set(task_by_id.keys())

    # Build blocked-by map: task_id -> set of incomplete dependency IDs
    blocked_by: dict[str, set[str]] = {}
    for task_id, deps in dependencies.items():
        incomplete = set()
        for dep in deps:
            dep_status = dep.get("status", "pending")
            if dep_status not in ("completed", "cancelled"):
                incomplete.add(dep["id"])
        if incomplete:
            blocked_by[task_id] = incomplete

    # Topological sort using Kahn's algorithm
    # Only consider edges within our task set
    in_degree: dict[str, int] = {t["id"]: 0 for t in tasks}
    graph: dict[str, list[str]] = {t["id"]: [] for t in tasks}

    for task_id, deps in dependencies.items():
        if task_id not in task_ids_in_list:
            continue
        for dep in deps:
            dep_id = dep["id"]
            dep_status = dep.get("status", "pending")
            if dep_status in ("completed", "cancelled"):
                continue
            if dep_id in task_ids_in_list:
                # dep_id must come before task_id
                graph[dep_id].append(task_id)
                in_degree[task_id] = in_degree.get(task_id, 0) + 1

    # Start with tasks that have no in-list incomplete dependencies
    ready: list[str] = []
    for t in tasks:
        tid = t["id"]
        if in_degree.get(tid, 0) == 0 and tid not in blocked_by:
            ready.append(tid)

    ordered: list[str] = []
    while ready:
        tid = ready.pop(0)
        ordered.append(tid)
        for neighbor in graph.get(tid, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0 and neighbor not in blocked_by:
                ready.append(neighbor)

    # Tasks blocked by external (not-in-list) dependencies go to the end
    blocked_external: list[str] = []
    for t in tasks:
        tid = t["id"]
        if tid not in ordered:
            if tid in blocked_by:
                # Check if ALL blockers are external
                internal_blockers = blocked_by[tid] & task_ids_in_list
                if not internal_blockers:
                    blocked_external.append(tid)

    # Remaining tasks (circular deps or complex blocking) at the very end
    remaining = [
        t["id"] for t in tasks if t["id"] not in ordered and t["id"] not in blocked_external
    ]

    result_ids = ordered + blocked_external + remaining
    return [task_by_id[tid] for tid in result_ids if tid in task_by_id]


def identify_blocked_tasks(
    tasks: list[dict],
    dependencies: dict[str, list[dict]],
) -> dict[str, list[str]]:
    """Identify which tasks are blocked and by what.

    Args:
        tasks: List of task dicts.
        dependencies: Map of task_id -> list of dependency dicts.

    Returns:
        Map of blocked task_id -> list of blocking task_ids (incomplete deps).
    """
    blocked: dict[str, list[str]] = {}
    for task in tasks:
        task_id = task["id"]
        deps = dependencies.get(task_id, [])
        blocking = []
        for dep in deps:
            dep_status = dep.get("status", "pending")
            if dep_status not in ("completed", "cancelled"):
                blocking.append(dep["id"])
        if blocking:
            blocked[task_id] = blocking
    return blocked
