"""Dependency-aware task ordering.

Pure logic module with no I/O dependencies. Computes processing order
based on task dependencies, ensuring children are processed before parents
and blocked tasks are deferred.
"""

from __future__ import annotations


def _build_blocked_by(
    dependencies: dict[str, list[dict]],
) -> dict[str, set[str]]:
    """Build a map of task_id -> set of incomplete dependency IDs.

    Args:
        dependencies: Map of task_id -> list of dependency task dicts
            (each with "id" and "status" fields).

    Returns:
        Map of task_id -> set of IDs of incomplete dependencies that block it.
        Only tasks with at least one incomplete dependency are included.
    """
    blocked_by: dict[str, set[str]] = {}
    for task_id, deps in dependencies.items():
        incomplete = set()
        for dep in deps:
            dep_status = dep.get("status", "pending")
            if dep_status not in ("completed", "cancelled"):
                incomplete.add(dep["id"])
        if incomplete:
            blocked_by[task_id] = incomplete
    return blocked_by


def _topological_sort(
    tasks: list[dict],
    dependencies: dict[str, list[dict]],
    blocked_by: dict[str, set[str]],
    task_ids_in_list: set[str],
) -> list[str]:
    """Perform Kahn's topological sort over the tasks.

    Only considers edges within the given task set and skips tasks that are
    externally blocked (i.e., in blocked_by but with no in-list blockers).

    Args:
        tasks: List of task dicts (must have "id" field).
        dependencies: Map of task_id -> list of dependency task dicts.
        blocked_by: Map of task_id -> set of incomplete dependency IDs
            (from _build_blocked_by).
        task_ids_in_list: Set of task IDs present in tasks.

    Returns:
        Ordered list of task IDs that can be processed (unblocked, respecting
        internal dependency order).
    """
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

    return ordered


def _partition_remaining(
    tasks: list[dict],
    ordered: list[str],
    blocked_by: dict[str, set[str]],
    task_ids_in_list: set[str],
) -> tuple[list[str], list[str]]:
    """Partition tasks not yet in the ordered list into two buckets.

    Args:
        tasks: Full list of task dicts (must have "id" field).
        ordered: Task IDs already placed by topological sort.
        blocked_by: Map of task_id -> set of incomplete dependency IDs.
        task_ids_in_list: Set of all task IDs in the list.

    Returns:
        A tuple of (blocked_external, remaining) where:
        - blocked_external: Tasks blocked only by dependencies outside the list.
        - remaining: All other unplaced tasks (circular deps, complex blocking).
    """
    ordered_set = set(ordered)

    # Tasks blocked only by external (not-in-list) dependencies
    blocked_external: list[str] = []
    for t in tasks:
        tid = t["id"]
        if tid not in ordered_set:
            if tid in blocked_by:
                # Check if ALL blockers are external
                internal_blockers = blocked_by[tid] & task_ids_in_list
                if not internal_blockers:
                    blocked_external.append(tid)

    blocked_external_set = set(blocked_external)

    # Remaining tasks (circular deps or complex blocking) at the very end
    remaining = [
        t["id"] for t in tasks if t["id"] not in ordered_set and t["id"] not in blocked_external_set
    ]

    return blocked_external, remaining


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

    blocked_by = _build_blocked_by(dependencies)
    ordered = _topological_sort(tasks, dependencies, blocked_by, task_ids_in_list)
    blocked_external, remaining = _partition_remaining(tasks, ordered, blocked_by, task_ids_in_list)

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
