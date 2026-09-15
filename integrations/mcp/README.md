# MCP Integration (skeleton)

Status: **skeleton only.** The server is not implemented. This document fixes the
contract so the tool surface does not get invented ad hoc later.

Model Context Protocol lets an external agent drive this runtime. The design
constraint is that the agent must never be able to claim a render succeeded when
it did not — so **every tool returns the runtime's own state**, and no tool has a
"success" boolean of its own.

## Why an MCP layer at all

The runtime already exposes a REST API. MCP adds one thing the API cannot: a
typed tool surface an LLM can call safely, with schemas short enough to fit in a
context window and no ability to construct arbitrary requests.

## Transport

stdio, one server per repository checkout. No network listener by default: this
is a local-first tool, and an unauthenticated render endpoint on a LAN is a
liability.

```
python -m html_video_workflow.mcp        # not yet implemented
```

## Planned tool surface

Deliberately small. Each maps to a function that already exists and is tested.

| Tool | Backed by | Returns |
|---|---|---|
| `hvw_hardware` | `hardware.profile.probe_hardware` | profile dict, `probed_at` |
| `hvw_providers` | `providers.registry.capabilities` | list with real probe states |
| `hvw_probe_provider` | `Provider.probe` | one probe result |
| `hvw_plan` | `pipeline.router.plan_pipeline` | selection + `reason[]` per stage |
| `hvw_validate` | `project.ir.validate_project` | errors with JSON paths |
| `hvw_create_project` | `save_project` | `project_id` |
| `hvw_render` | `VideoRuntime.run_job` | `job_id` (job continues in background) |
| `hvw_job_status` | `VideoRuntime.get_job` | status, progress, `fallbacks[]` |
| `hvw_job_events` | `runtime.events.read_events` | append-only log slice |
| `hvw_quality` | `job.quality` | check list, `passed`/`warned`/`failed` |

## Non-negotiable rules

1. **No fabricated success.** `hvw_render` returns a job id, never `completed`.
   The agent must poll `hvw_job_status`. A job can fail after the tool returns.
2. **Fallbacks are surfaced, not hidden.** `hvw_job_status` always includes
   `fallbacks[]`. An agent that omits them is misreporting the run.
3. **Probes are live.** `hvw_providers` triggers real probes. It is allowed to be
   slow; it is not allowed to return cached optimism.
4. **No destructive tools.** There is no delete, no model download, no config
   write. Those require a human at the CLI.
5. **Secrets never cross the boundary.** No tool returns an API key. Config
   responses use the masked form (`sk-****7a3`).
6. **Paths are runtime-resolved.** Tools never accept an arbitrary output path;
   artifacts go to `outputs_dir()`.

## Files when implemented

```
integrations/mcp/
  README.md          this document
  server.py          stdio entry point
  tools.py           tool schemas + dispatch to the modules above
  resources.py       exposes job manifests and QC reports as MCP resources
```

## Resources (read-only, planned)

- `hvw://job/<job_id>/manifest` — the persisted `job.json`
- `hvw://job/<job_id>/quality` — the QC report
- `hvw://project/<project_id>/ir` — the V2 project document
- `hvw://hardware` — the cached profile

Resources are preferable to tools for anything the agent only needs to read: they
cost no tool call and cannot mutate state.

## Testing expectation

When implemented, the acceptance test is behavioural, not structural: point an
agent at a project whose renderer will fail, and assert the agent reports the
failure and the fallback rather than a success. A tool surface that can produce a
false positive is worse than no tool surface.
