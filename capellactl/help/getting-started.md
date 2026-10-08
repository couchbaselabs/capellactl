# Getting started

1. **Connect.** Create an API key in the Capella UI (Organization settings → API Keys) and copy its
   **API Key Token** (shown once; not the API Key ID). Run `capellactl configure` and paste the token. The key is checked and stored in your OS keychain. For CI, set
   `CAPELLA_API_KEY` and `CAPELLA_ORG_ID` instead.
2. **Discover.** `configure` offers to write `capella.yaml` from your project and clusters right away
   (or run `capellactl import` later). Nothing in Capella changes. capellactl maintains the file; you
   do not edit it. For a new project: `capellactl project list`, then `capellactl project create NAME`.
3. **Validate** offline (optional): `capellactl validate`.
4. **Plan**: `capellactl plan`. Straight after discovery it reports no changes. Nothing changes.
5. **Deploy and change** with commands: `capellactl cluster options` shows what you can deploy (including
   the free tier, `--free-tier`); `capellactl cluster create NAME` (asks what it needs, deploys,
   waits), `capellactl cluster update NAME …`, `capellactl cluster scale NAME --nodes N`. Each shows the
   plan, asks once, records the change in capella.yaml and applies it.
6. **Sync**: `capellactl sync` refreshes capella.yaml after changes made in the Capella UI.

Next: `capellactl help idempotency`, `capellactl help scaling`, `capellactl help safety`.
