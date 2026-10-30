"""Database credential reconciler: basic access (CAP-027), password rotation (CAP-028), delete (CAP-029).

Access is compared in a canonical form: `read`/`write` are the same as `data_reader`/`data_writer`, and the
grants are flattened to one privilege set per resource (all buckets, a bucket, a scope or a collection), so
Capella's grouping and ordering never show up as a change.

Capella never returns passwords. They are sent on create, and afterwards only on explicit rotation
(`apply --rotate-passwords`, `credential update --rotate-password`); a changed `${VAR}` value is not a change.

Advanced credentials (`userRoles`) are out of scope for 1.0.0: one with a declared name is BLOCKED, and
`apply --prune` leaves undeclared ones alone.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from capellactl.api import endpoints as ep
from capellactl.api.errors import NotFound
from capellactl.engine.context import RunContext
from capellactl.output import secrets_out
from capellactl.output.password_gen import generate_password
from capellactl.resources.base import Action, ActionType, Change, Observed, Reconciler

CANON = {"read": "data_reader", "write": "data_writer", "data_reader": "data_reader", "data_writer": "data_writer"}
ALL = "(all buckets)"
PASSWORD_NOTE = "note: passwords are not compared; use --rotate-password to change them"
ADVANCED_REASON = ("an advanced credential with this name exists in Capella; capellactl 1.0 manages basic credentials "
                   "only (advanced credentials are planned for 1.1)")


def canon_privileges(privs: Any) -> frozenset[str]:
    return frozenset(CANON.get(str(p), str(p)) for p in privs or [])


def privilege_label(privs: frozenset[str] | None) -> str | None:
    """data_reader → read, data_writer → write, both → read+write (other privileges listed as they are)."""
    if not privs:
        return None
    words = (["read"] if "data_reader" in privs else []) + (["write"] if "data_writer" in privs else [])
    words += sorted(p for p in privs if p not in ("data_reader", "data_writer"))
    return "+".join(words)


WILDCARD = "*"


def without_wildcards(access: Any) -> list[dict[str, Any]]:
    """Capella returns `*` for "every bucket/scope/collection" (a whole-bucket grant comes back as
    `scopes: [{name: '*'}]`); the file writes those levels by leaving them out. Returns new dicts."""
    out = []
    for entry in access or []:
        e = {k: v for k, v in entry.items() if k != "resources"}
        buckets = (entry.get("resources") or {}).get("buckets") or []
        if buckets and not any(b.get("name") == WILDCARD for b in buckets):
            rb = []
            for b in buckets:
                item = {k: v for k, v in b.items() if k != "scopes"}
                scopes = b.get("scopes") or []
                if scopes and not any(s.get("name") == WILDCARD for s in scopes):
                    item["scopes"] = []
                    for s in scopes:
                        sc = {k: v for k, v in s.items() if k != "collections"}
                        colls = s.get("collections") or []
                        if colls and WILDCARD not in colls:
                            sc["collections"] = list(colls)
                        item["scopes"].append(sc)
                rb.append(item)
            e["resources"] = {**entry["resources"], "buckets": rb}
        elif entry.get("resources") and not buckets:
            e["resources"] = entry["resources"]
        out.append(e)
    return out


def _resource_keys(entry: dict[str, Any]) -> list[str]:
    """Resources one grant applies to: ALL, 'bucket', 'bucket/scope' or 'bucket/scope/collection'."""
    buckets = (entry.get("resources") or {}).get("buckets") or []
    if not buckets:
        return [ALL]
    keys = []
    for b in buckets:
        scopes = b.get("scopes") or []
        if not scopes:
            keys.append(str(b["name"]))
        for s in scopes:
            colls = s.get("collections") or []
            if not colls:
                keys.append(f"{b['name']}/{s['name']}")
            keys += [f"{b['name']}/{s['name']}/{c}" for c in colls]
    return keys


def access_map(access: Any) -> dict[str, frozenset[str]]:
    """Canonical access: one privilege set per resource (CAP-027 AC3)."""
    out: dict[str, frozenset[str]] = {}
    for entry in without_wildcards(access):
        privs = canon_privileges(entry.get("privileges"))
        for k in _resource_keys(entry):
            out[k] = out.get(k, frozenset()) | privs
    return out


def access_changes(desired: Any, observed: Any) -> list[Change]:
    """`orders/inventory: read → read+write` per resource whose privileges differ (CAP-027 AC4)."""
    d, o = access_map(desired), access_map(observed)
    keys = sorted(set(d) | set(o), key=lambda k: (k == ALL, k))
    return [Change(k, privilege_label(o.get(k)), privilege_label(d.get(k))) for k in keys if d.get(k) != o.get(k)]


def _resource_text(entry: dict[str, Any]) -> str:
    buckets = (entry.get("resources") or {}).get("buckets") or []
    if not buckets:
        return ALL
    parts = []
    for b in sorted(buckets, key=lambda x: str(x["name"])):
        scopes = b.get("scopes") or []
        if not scopes:
            parts.append(str(b["name"]))
        for s in sorted(scopes, key=lambda x: str(x["name"])):
            colls = sorted(str(c) for c in s.get("collections") or [])
            tail = "" if not colls else f"/{colls[0]}" if len(colls) == 1 else "/{" + ",".join(colls) + "}"
            parts.append(f"{b['name']}/{s['name']}{tail}")
    return ", ".join(parts)


def access_summary(access: Any) -> str:
    """`read+write · orders/inventory/{items,suppliers}`; grants to all buckets come last (CAP-027 AC1/AC5)."""
    entries = sorted(without_wildcards(access), key=lambda e: _resource_text(e) == ALL)
    return "; ".join(f"{privilege_label(canon_privileges(e.get('privileges')))} · {_resource_text(e)}" for e in entries)


def api_access(access: Any) -> list[dict[str, Any]]:
    """The access list as the API takes it: the file's grants without tool-only keys (`external`)."""
    out = []
    for entry in access or []:
        e: dict[str, Any] = {"privileges": list(entry.get("privileges") or [])}
        buckets = (entry.get("resources") or {}).get("buckets")
        if buckets:
            rb = []
            for b in buckets:
                item: dict[str, Any] = {"name": b["name"]}
                if b.get("scopes"):
                    item["scopes"] = [{"name": s["name"], **({"collections": list(s["collections"])}
                                                           if s.get("collections") else {})} for s in b["scopes"]]
                rb.append(item)
            e["resources"] = {"buckets": rb}
        out.append(e)
    return out


def is_advanced(body: dict[str, Any]) -> bool:
    """userRoles credentials. A basic credential whose access was removed (empty `access`) is not advanced."""
    return bool(body.get("userRoles")) or body.get("credentialType") == "advanced"


def secret_dir_for(cfg: Any) -> Path:
    """`credentialsOutput`, relative to the config file's directory."""
    base = Path(cfg.path).parent if cfg is not None and getattr(cfg, "path", None) else Path.cwd()
    out = Path(cfg.credentials_output) if cfg is not None else Path("./.capellactl/credentials")
    return out if out.is_absolute() else base / out


def secret_dir(ctx: RunContext) -> Path:
    return secret_dir_for(ctx.config)


def cluster_name(cluster: Action | None) -> str:
    d = cluster.desired if cluster is not None and isinstance(cluster.desired, dict) else {}
    return str(d.get("name") or (cluster.key if cluster is not None else ""))


def kept_secret_note(directory: Path, cluster: str, name: str) -> str | None:
    """CAP-029 AC2: the local file of a generated password is never deleted by capellactl."""
    p = secrets_out.secret_path(directory, cluster, name)
    return f"local secret file kept: {p} (delete it if no longer needed)" if p.exists() else None


class CredentialReconciler(Reconciler):
    kind = "credential"
    story = "CAP-027"
    prunable = True

    def __init__(self, children: list[Reconciler] | None = None) -> None:
        super().__init__(children)
        self._noted = False

    def desired_items(self, parent_desired: Any) -> list[Any]:
        return list(parent_desired.get("databaseCredentials") or []) if isinstance(parent_desired, dict) else []

    def key(self, desired: Any, parent: Action | None) -> str:
        return f"{parent.key}/{desired['name']}" if parent else str(desired["name"])

    def _ids(self, cluster: Action | None) -> tuple[str, str]:
        project = cluster.ancestor("project") if cluster is not None else None
        assert cluster is not None and cluster.id is not None and project is not None and project.id is not None
        return project.id, cluster.id

    def observe(self, ctx: RunContext, parent: Action | None) -> list[Observed]:
        return [Observed(str(u["id"]), u) for u in ep.list_credentials(ctx.client, *self._ids(parent))]

    # --------------------------------------------------------------- planning
    def diff(self, ctx: RunContext, desired: Any, observed: Observed | None, parent: Action | None) -> Action:
        key = self.key(desired, parent)
        if desired.get("password") and not ctx.rotate_passwords and not self._noted:
            self._noted = True
            ctx.progress(PASSWORD_NOTE)  # once per run (CAP-028 AC4)
        if observed is None:
            return Action(self.kind, key, ActionType.CREATE, self, desired=desired, parent=parent,
                          summary=access_summary(desired.get("access")))
        a = Action(self.kind, key, ActionType.NOOP, self, desired=desired, observed=observed, parent=parent)
        if is_advanced(observed.body):
            a.type, a.reason, a.topic = ActionType.BLOCKED, ADVANCED_REASON, "credentials"
            return a
        a.changes = access_changes(desired.get("access"), observed.body.get("access"))
        if ctx.rotate_passwords:
            a.data["rotate"] = True
            a.label = "rotate password"
        if a.changes or a.data.get("rotate"):
            a.type = ActionType.UPDATE
        return a

    def delete_action(self, ctx: RunContext, observed: Observed, parent: Action | None) -> Action:
        """`apply --prune`: a basic credential the file no longer declares (CAP-029 AC3)."""
        name = str(observed.body.get("name"))
        key = f"{parent.key}/{name}" if parent else name
        if is_advanced(observed.body):
            return Action(self.kind, key, ActionType.NOOP, self, desired={"name": name}, observed=observed,
                          parent=parent, notes=["(advanced credential: not managed by capellactl 1.0, left unchanged)"])
        return Action(self.kind, key, ActionType.DELETE, self, desired={"name": name}, observed=observed, parent=parent,
                      summary=access_summary(observed.body.get("access")))

    # --------------------------------------------------------------- applying
    def apply(self, ctx: RunContext, action: Action) -> None:
        pid, cid = self._ids(action.parent)
        d, cluster = action.desired, cluster_name(action.parent)
        if action.type is ActionType.CREATE:
            self._create(ctx, action, pid, cid, cluster)
            return
        assert action.observed is not None and action.observed.id is not None
        uid = action.observed.id
        if action.type is ActionType.DELETE:
            with contextlib.suppress(NotFound):  # already gone: the goal is reached
                ep.delete_credential(ctx.client, pid, cid, uid)
            note = kept_secret_note(secret_dir(ctx), cluster, str(d["name"]))
            if note:
                ctx.progress(note)
            return
        if action.type is ActionType.UPDATE:
            self._update(ctx, action, pid, cid, uid, cluster)

    def _create(self, ctx: RunContext, action: Action, pid: str, cid: str, cluster: str) -> None:
        d = action.desired
        body: dict[str, Any] = {"name": d["name"], "credentialType": "basic", "access": api_access(d.get("access"))}
        if d.get("password"):
            body["password"] = d["password"]
            action.created_id, _ = ep.create_credential(ctx.client, pid, cid, body)
            return
        directory = secret_dir(ctx)
        secrets_out.preflight(directory, cluster, str(d["name"]))  # never create when the secret cannot be saved
        action.created_id, password = ep.create_credential(ctx.client, pid, cid, body)
        path = secrets_out.write_generated_credential(directory, cluster, str(d["name"]), action.created_id, password)
        ctx.progress(secrets_out.saved_message(path))
        warning = secrets_out.git_warning(directory)
        if warning:
            ctx.warn(*warning)

    def _update(self, ctx: RunContext, action: Action, pid: str, cid: str, uid: str, cluster: str) -> None:
        d, name = action.desired, str(action.desired["name"])
        current, etag = ep.get_credential(ctx.client, pid, cid, uid)
        body: dict[str, Any] = {}
        if access_changes(d.get("access"), current.get("access")):
            body["access"] = api_access(d.get("access"))  # never the password (CAP-027 AC4)
        saved: tuple[Path, Path | None] | None = None
        if action.data.get("rotate"):
            # Capella treats a PUT without `access` as "no access": a password-only rotation removed every
            # grant (seen 2026-10-07). Always send the access with the password.
            body.setdefault("access", api_access(d.get("access")) if d.get("access") else current.get("access") or [])
            password = d.get("password")
            if not password:  # generated; saved before it is sent (CAP-028 AC2)
                password = generate_password()
                saved = secrets_out.write_rotated_credential(secret_dir(ctx), cluster, name, uid, password)
            body["password"] = password
        if not body:
            return
        try:
            ep.update_credential(ctx.client, pid, cid, uid, body, if_match=etag)
        except BaseException:
            if saved is not None:
                secrets_out.restore_rotated_credential(*saved)
            raise
        if "password" in body:
            ctx.progress(f"password rotated for {name}")
            if saved is not None:
                ctx.progress(secrets_out.saved_message(saved[0]))
