# Security

## Reporting a vulnerability

Open a private security advisory on this repository
(**Security → Report a vulnerability**) rather than a public issue. Please
include the version (`html-video doctor` prints it), your OS, and the smallest
reproduction you can manage.

There is no bug bounty. This is a small project maintained in spare time; the
commitment here is a prompt reply and a fix or an honest explanation.

## What this software does with your data

**It runs locally.** There is no backend service, no telemetry, and no
analytics. Nothing is sent anywhere unless you explicitly configure an AI model.

| Data | Where it goes |
| :--- | :--- |
| Your topic and documents | Stay on your disk, in the project directory under `HVW_HOME`. |
| Generated video, audio, subtitles | Stay on your disk. |
| API key | Written to `HVW_HOME\.env` with restrictive permissions. Sent **only** to the endpoint you configured, as an `Authorization` header. Never logged, never written into project JSON or job artifacts. |
| Narration text | Sent to your configured model endpoint when AI writing is enabled — that is the one outbound call in the whole pipeline. |

To verify the claims above rather than trust them:

```bash
html-video doctor          # probes the machine, reports what is real
```

and read `src/html_video_workflow/providers/` — every outbound call in this
project goes through a provider, and there is no other network code.

## The local server

The studio binds to `127.0.0.1` by default. It is a local development server, not
a hardened service:

- It has **no authentication** — anything on your machine can reach it.
- Do not bind it to `0.0.0.0` on an untrusted network.
- It can read and reveal files inside `HVW_HOME`; path traversal outside that
  root is rejected by `utils/desktop.py::resolve_within`.

## Frozen build

The Windows download is built with PyInstaller and is **not code-signed**, so
SmartScreen warns on first launch. The build is produced by
[`.github/workflows/release.yml`](.github/workflows/release.yml) from a tagged
commit; you can inspect that workflow and build the same artifact yourself with
`python scripts/pack_release.py`.

## Dependencies

Python dependencies are pinned in `pyproject.toml`. The packaged build bundles
FFmpeg (from Chocolatey on the CI runner) and a Chromium-based browser is used
from the system for rendering; neither is vendored into this repository.
