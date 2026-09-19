# The Logfire dashboard: checked vs held

Three panels over pakka's own spans. Nothing here is read by the layer (Logfire is written to, never read from); this is the Insights tab a reviewer looks at.

The spans, all emitted by `pakka/staging.py`:

| span | when | attributes used here |
|---|---|---|
| `pakka.write` | every write the agent attempted | `run` (int), `tool`, `mode`, `decision` (`held` / `passed`), `held` (bool), `blocked` (bool), `first_flag` (`grounding` / `envelope` / `memory` / `rule` / `none`), `anomaly`, `supervisor` |
| `pakka.decision` | every approve, discard, edit, skip, send, rule, promotion, demotion | `decision`, `run`, `decided_by` |
| `pakka.run` | one per run | `run`, `mode`, `supervisor`, `model`, `agent`, `connectors`, `usage.requests`, `usage.input_tokens`, `usage.output_tokens`, `usage.tool_calls`, `usage.latency_s`, `usage.replay`, `checked`, `held`, `caught` |

The project fills up whenever the deployed app plays the demo. To refill it, run the whole 26-Friday demo over HTTP against the live URL (the same calls the page makes): `POST /reset`, `POST /decide` for Friday 1, `POST /run/{f}` with `auto_approve` for the montage, `POST /autopilot/{f}` for the rest. The scratch script the team uses for that is a 40-line `urllib` loop; the page's Reset → Approve → Play 5 Fridays → Autopilot does the same thing.

## Creating it

Logfire → the project → **+ Dashboard** → **Custom** → name it `pakka — checked vs held` → **Panel** for each query below. Bar, table and pie charts take a non-time-series query; a time-series chart needs `time_bucket($resolution, start_timestamp)` as its x column.

### Panel 1 · checked vs held per Friday (bar chart, x = `friday`)

Checked is flat: the layer looks at every write, every Friday. Held falls as trust is earned (Fridays 2–6 hold everything from unreleased tools; from Friday 7 the released tools pass) and spikes at each catch (8, 10, 12, 14, 17, 19).

```sql
select cast(attributes->>'run' as int) as friday,
       count(*) as checked,
       sum(case when attributes->>'decision' = 'held' then 1 else 0 end) as held,
       sum(case when attributes->>'decision' = 'held' and attributes->>'first_flag' <> 'none' then 1 else 0 end) as flagged
from records
where span_name = 'pakka.write'
group by 1
order by 1
```

`held` counts everything that waited for a person, including writes held only because their tool was not yet released and writes blocked behind one. `flagged` is the subset a check caught.

### Panel 2 · what people did with the held writes (pie or table)

```sql
select attributes->>'decision' as decision, count(*) as n
from records
where span_name = 'pakka.decision'
  and attributes->>'decision' in ('approve', 'discard', 'edit', 'skip')
group by 1
order by 2 desc
```

### Panel 3 · holds by reason (bar chart, x = `reason`)

```sql
select attributes->>'first_flag' as reason, count(*) as holds
from records
where span_name = 'pakka.write'
  and attributes->>'decision' = 'held'
  and attributes->>'first_flag' <> 'none'
group by 1
order by 2 desc
```

### Panel 4 · what each run cost (bar chart, x = `run`)

```sql
select cast(attributes->>'run' as int) as run,
       sum(cast(attributes->>'usage.input_tokens' as int)) as input_tokens,
       sum(cast(attributes->>'usage.output_tokens' as int)) as output_tokens,
       sum(cast(attributes->>'usage.requests' as int)) as requests,
       avg(cast(attributes->>'usage.latency_s' as double)) as latency_s
from records
where span_name = 'pakka.run' and attributes->>'usage.replay' = 'false'
group by 1
order by 1
```

Replays are excluded (`usage.replay = false`): they spend no tokens now. Tokens per held write is this joined with Panel 1 on `run`.

### Optional · the same thing over time (time series)

```sql
select time_bucket($resolution, start_timestamp) as x,
       count(*) as checked,
       sum(case when attributes->>'decision' = 'held' then 1 else 0 end) as held
from records
where span_name = 'pakka.write'
group by x
order by x
```

## Reading it

- The `checked` bars never shrink. The layer interrupts less because it has learned, never because it is off.
- On the demo's data: 268 checked over 26 Fridays, 25 held at the root, 54 blocked behind a held write, 7 flagged holds for 7 anomalies, 0 wrongly held.
- If a Friday shows more than one flagged hold, or a flagged hold on a Friday with no anomaly, that is a false positive and belongs in `docs/ANOMALIES.md`.

The `->>` operator and `cast(... as int)` follow Logfire's SQL reference (DataFusion with the JSON functions); if the cast is refused on a project, `(attributes::text)->>'run'` is the documented fallback for the key.

Screenshot of Panel 1 goes to `video/assets/logfire-chart.png`; the README's Logfire section points at it.
