# Project schema

```json
{
  "title": "Video title",
  "subtitle": "Optional deck",
  "author": "AI Video Workflow",
  "language": "zh-CN",
  "voice": {"engine": "sapi", "name": "Microsoft Huihui Desktop"},
  "sources": [{"title": "Source name", "url": "https://..."}],
  "scenes": [
    {
      "eyebrow": "01 / OPEN",
      "title": "Short scene title",
      "body": "One or two concise lines rendered on screen.",
      "narration": "Natural spoken narration.",
      "tags": ["tag one", "tag two"],
      "metric": "12–18 months",
      "metric_label": "Suggested research lead time"
    }
  ]
}
```

Use 5–9 scenes. Keep titles under 22 Chinese characters, body under 80 Chinese characters, and narration around 45–90 Chinese characters per scene. Claims must be supported by `sources`; avoid rankings presented as official facts.
