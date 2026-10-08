"""Project reconciler (CAP-009)."""

from __future__ import annotations

from typing import Any

from capellactl.api import endpoints as ep
from capellactl.engine.context import RunContext
from capellactl.engine.normalize import field_changes
from capellactl.resources.base import RENAMED_NOTE, Action, ActionType, Observed, PlanError, Reconciler


class ProjectReconciler(Reconciler):
    kind = "project"
    story = "CAP-009"

    def desired_items(self, parent_desired: Any) -> list[Any]:
        """One item per project of the file (both the projects: and the single-project form)."""
        items = []
        for entry in parent_desired.projects():
            d = {k: v for k, v in entry.data.items() if k != "clusters"}
            d["_clusters"] = entry.clusters
            items.append(d)
        return items

    def key(self, desired: Any, parent: Action | None) -> str:
        return str(desired["name"])

    def observe(self, ctx: RunContext, parent: Action | None) -> list[Observed]:
        self._all = [Observed(str(p["id"]), p) for p in ep.list_projects(ctx.client)]
        return self._all

    def _renamed_from(self, ctx: RunContext, desired: Any) -> tuple[str, str] | None:
        """(project, cluster) when a Capella project that is not in the file holds one of this project's declared
        clusters: the project was probably renamed in the Capella UI (CAP-048 AC4)."""
        declared = {str(c.get("name")) for c in desired.get("_clusters") or [] if isinstance(c, dict)}
        if not declared:
            return None
        from capellactl.config.loader import project_entries

        in_file = {e.name for e in project_entries(ctx.config.data)} if ctx.config is not None else set()
        for o in getattr(self, "_all", []):
            if o.body.get("name") in in_file:
                continue
            for c in ep.list_clusters(ctx.client, o.id):
                if c.get("name") in declared:
                    return str(o.body.get("name")), str(c.get("name"))
        return None

    def match(self, desired: Any, observed: list[Observed]) -> list[Observed]:
        pinned = desired.get("id")
        if pinned:
            found = [o for o in observed if o.id == pinned]
            if not found:
                raise PlanError(f"project {pinned} not found")
            return found
        return [o for o in observed if o.body.get("name") == desired["name"]]

    def diff(self, ctx: RunContext, desired: Any, observed: Observed | None, parent: Action | None) -> Action:
        key = self.key(desired, parent)
        if observed is None:
            renamed = None if desired.get("id") else self._renamed_from(ctx, desired)
            if renamed:
                a = Action(self.kind, key, ActionType.BLOCKED, self, desired=desired, parent=parent, topic="idempotency")
                a.reason = (f"no project named {key}; project {renamed[0]} has its cluster {renamed[1]}, so it was "
                            "probably renamed in Capella. Run 'capellactl sync' to adopt the new name, or rename it "
                            "back in Capella (apply would create a second project)")
                return a
            return Action(self.kind, key, ActionType.CREATE, self, desired=desired, parent=parent)
        skip = {"_clusters", "id"}
        if not desired.get("id"):
            skip.add("name")
        changes = field_changes(desired, observed.body, skip=skip)
        t = ActionType.UPDATE if changes else ActionType.NOOP
        a = Action(self.kind, key, t, self, desired=desired, observed=observed, parent=parent, changes=changes)
        if any(c.path == "name" for c in changes):
            a.notes.append(RENAMED_NOTE)
        return a

    def delete_action(self, ctx: RunContext, observed: Observed, parent: Action | None) -> Action:
        """`destroy` (CAP-030): the project, deleted last."""
        return Action(self.kind, str(observed.body.get("name")), ActionType.DELETE, self,
                      desired={"name": observed.body.get("name")}, observed=observed, parent=parent)

    def apply(self, ctx: RunContext, action: Action) -> None:
        d = action.desired
        if action.type is ActionType.DELETE:
            assert action.observed is not None and action.observed.id is not None
            ep.delete_project(ctx.client, action.observed.id)
            return
        if action.type is ActionType.CREATE:
            body: dict[str, Any] = {"name": d["name"]}
            if d.get("description") is not None:
                body["description"] = d["description"]
            action.created_id = ep.create_project(ctx.client, body)
            return
        if action.type is ActionType.UPDATE:
            assert action.observed is not None and action.observed.id is not None
            current, etag = ep.get_project(ctx.client, action.observed.id)
            body = {
                "name": d["name"] if d.get("id") else current.get("name", d["name"]),
                "description": d["description"] if "description" in d else current.get("description", ""),
            }
            ep.update_project(ctx.client, action.observed.id, body, if_match=etag)
