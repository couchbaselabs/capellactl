# Hibernation: power off/on and schedules

Turning a cluster off stops compute charges; storage, data, buckets, indexes, users and allowed IPs
remain. Linked App Services turn off too. Data API charges continue.

- On demand: `capellactl cluster power NAME --off` / `--on` (waits until done; free-tier clusters too).
- Weekly schedule: Capella turns the cluster off outside the on-windows.

```bash
capellactl cluster schedule set NAME --timezone US/Pacific --weekdays 08:00-18:00 --weekend off
capellactl cluster schedule set NAME --friday 08:00-14:30      # per-day override
capellactl cluster schedule show NAME                          # weekly grid and the next on/off time
capellactl cluster schedule delete NAME
```

`schedule set` records it in capella.yaml (`hibernation:`), so `apply` keeps it:

```yaml
hibernation:
  timezone: US/Pacific
  weekdays: "08:00-18:00"     # on-window Monday–Friday
  weekend: "off"
  friday: "08:00-14:30"       # per-day override
```

Rules from the API: times on the hour or half hour; every day cannot be off. Quote `"on"`/`"off"`:
unquoted YAML reads them as true/false (capellactl converts them, with a tip).

- Pause for a demo or incident: `capellactl cluster schedule pause NAME --power-on`, later `resume`.
  Both record `paused` in capella.yaml.

While a cluster is turned off, changes to it and to what it holds are blocked (the schedule itself can
still change). Turn it on first, or pass `apply --power-on`.
