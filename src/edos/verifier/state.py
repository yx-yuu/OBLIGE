from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class VerifierNode:
    node_id: str
    parent_node_id: str | None
    branch_id: str
    node_depth: int
    behavior_surface: str
    stage_marker: str
    node_status: str = "active"
    controller_state: str = ""
    latch_state: str = "active"
    marker_echoed: bool = False
    theory_source: str = "P1_validation_subgraph"
    derivation_step: str = "validation_subgraph"
    created_turn_id: int = 0
    completed_turn_id: int | None = None
    visits: int = 1
    visit_turn_ids: list[int] = field(default_factory=list)
    marker_history: list[str] = field(default_factory=list)


@dataclass
class VerifierState:
    run_id: str
    condition: str
    completed_nodes: list[str] = field(default_factory=list)
    active_node: str | None = None
    active_marker: str | None = None
    marker_count: int = 0
    nodes: dict[str, VerifierNode] = field(default_factory=dict)
    active_branch_id: str | None = None
    last_node_id: str | None = None
    behavior_surfaces_seen: list[str] = field(default_factory=list)
    repair_counts: dict[str, int] = field(default_factory=dict)
    pagination_counts: dict[str, int] = field(default_factory=dict)
    echo_count: int = 0
    latch_enabled: bool = True
    dynamic_marker_enabled: bool = True
    budget_control_enabled: bool = True

    @classmethod
    def load_or_create(
        cls,
        path: str | Path,
        *,
        run_id: str,
        condition: str,
        latch_enabled: bool,
        dynamic_marker_enabled: bool = True,
        budget_control_enabled: bool = True,
    ) -> "VerifierState":
        state_path = Path(path)
        if state_path.exists():
            with state_path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
            nodes = {
                node_id: VerifierNode(**node)
                for node_id, node in raw.get("nodes", {}).items()
            }
            fields = {
                "run_id",
                "condition",
                "completed_nodes",
                "active_node",
                "active_marker",
                "marker_count",
                "active_branch_id",
                "last_node_id",
                "behavior_surfaces_seen",
                "repair_counts",
                "pagination_counts",
                "echo_count",
                "latch_enabled",
                "dynamic_marker_enabled",
                "budget_control_enabled",
            }
            payload = {key: value for key, value in raw.items() if key in fields}
            payload["nodes"] = nodes
            payload.setdefault("latch_enabled", latch_enabled)
            payload.setdefault("dynamic_marker_enabled", dynamic_marker_enabled)
            payload.setdefault("budget_control_enabled", budget_control_enabled)
            return cls(**payload)
        return cls(
            run_id=run_id,
            condition=condition,
            latch_enabled=latch_enabled,
            dynamic_marker_enabled=dynamic_marker_enabled,
            budget_control_enabled=budget_control_enabled,
        )

    def save(self, path: str | Path) -> None:
        state_path = Path(path)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        with state_path.open("w", encoding="utf-8") as handle:
            json.dump(asdict(self), handle, ensure_ascii=False, indent=2)
            handle.write("\n")

    def next_node(self, surface: str, turn_id: int) -> VerifierNode:
        if self.latch_enabled and self.active_node and self.active_node in self.nodes:
            node = self.nodes[self.active_node]
            node.visits += 1
            node.node_status = "active"
            node.latch_state = "active"
            node.visit_turn_ids.append(turn_id)
            self.active_branch_id = node.branch_id
        else:
            branch_id = self._branch_for_surface(surface)
            parent_node_id = self.last_node_id
            node_depth = self._next_depth(parent_node_id)
            node_id = f"{surface}-{turn_id:04d}"
            node = VerifierNode(
                node_id=node_id,
                parent_node_id=parent_node_id,
                branch_id=branch_id,
                node_depth=node_depth,
                behavior_surface=surface,
                stage_marker="",
                created_turn_id=turn_id,
                visit_turn_ids=[turn_id],
            )
            self.nodes[node_id] = node
            self.active_node = node_id
            self.active_branch_id = branch_id
        marker = self._next_marker()
        self.active_marker = marker
        node.stage_marker = marker
        node.marker_history.append(marker)
        if node.behavior_surface not in self.behavior_surfaces_seen:
            self.behavior_surfaces_seen.append(node.behavior_surface)
        return node

    def mark_completed(self, node_id: str, turn_id: int | None = None) -> None:
        if node_id not in self.completed_nodes:
            self.completed_nodes.append(node_id)
        if node_id in self.nodes:
            self.nodes[node_id].node_status = "completed"
            self.nodes[node_id].latch_state = "completed"
            self.nodes[node_id].completed_turn_id = turn_id
        if self.active_node == node_id:
            self.active_node = None
        self.last_node_id = node_id

    def mark_incomplete(self, node_id: str, *, marker_echoed: bool) -> None:
        if node_id in self.nodes:
            self.nodes[node_id].node_status = "incomplete"
            self.nodes[node_id].latch_state = (
                "active" if self.latch_enabled else "disabled"
            )
            self.nodes[node_id].marker_echoed = marker_echoed
        self.last_node_id = node_id

    def release_static_step(self, node_id: str, *, marker_echoed: bool) -> None:
        if node_id in self.nodes:
            self.nodes[node_id].node_status = "incomplete"
            self.nodes[node_id].latch_state = "static"
            self.nodes[node_id].marker_echoed = marker_echoed
        if self.active_node == node_id:
            self.active_node = None
        self.last_node_id = node_id

    def repair_count(self, node_id: str | None) -> int:
        if not node_id:
            return 0
        return max(0, int(self.repair_counts.get(node_id, 0)))

    def pagination_count(self, node_id: str | None) -> int:
        if not node_id:
            return 0
        return max(0, int(self.pagination_counts.get(node_id, 0)))

    def record_repair(self, node_id: str) -> int:
        count = self.repair_count(node_id) + 1
        self.repair_counts[node_id] = count
        return count

    def record_pagination(self, node_id: str) -> int:
        count = self.pagination_count(node_id) + 1
        self.pagination_counts[node_id] = count
        return count

    def graph_summary(self) -> dict[str, object]:
        nodes = list(self.nodes.values())
        node_count = len(nodes)
        branches = {node.branch_id for node in nodes if node.branch_id}
        open_nodes = [
            node
            for node in nodes
            if node.node_status not in {"completed"}
        ]
        completed_count = sum(1 for node in nodes if node.node_status == "completed")
        max_depth = max((node.node_depth for node in nodes), default=0)
        surfaces = Counter(node.behavior_surface for node in nodes if node.behavior_surface)
        return {
            "validation_graph_node_count": node_count,
            "validation_graph_branch_count": len(branches),
            "validation_graph_open_node_count": len(open_nodes),
            "validation_graph_completed_node_count": completed_count,
            "validation_graph_completion_ratio": completed_count / node_count
            if node_count
            else 0.0,
            "validation_graph_max_depth": max_depth,
            "validation_graph_active_branch_id": self.active_branch_id or "",
            "validation_graph_active_node_id": self.active_node or "",
            "validation_graph_surface_count": len(surfaces),
            "validation_graph_surface_histogram": dict(sorted(surfaces.items())),
        }

    def _next_depth(self, parent_node_id: str | None) -> int:
        if not parent_node_id or parent_node_id not in self.nodes:
            return 0
        return self.nodes[parent_node_id].node_depth + 1

    @staticmethod
    def _branch_for_surface(surface: str) -> str:
        return f"{surface}-branch-001"

    def _next_marker(self) -> str:
        if not self.dynamic_marker_enabled:
            return "PB-CHECK-STATIC"
        self.marker_count += 1
        return f"PB-CHECK-{self.marker_count:03d}"
