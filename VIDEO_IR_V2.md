# Video Project IR — V2

`schema_version: 2`. V1 files (`assets/demo-us-study-2026.json`, any project
built with `scripts/workflow.py`) are still loadable and are migrated in memory
by `project/migrate.py`. Nothing is deleted.

The IR describes **what the video means**, never how a renderer implements it.

---

## 1. Top level

```jsonc
{
  "schema_version": 2,
  "id": "prj_01H...",
  "project":   { "title": "...", "subtitle": "...", "language": "zh-CN",
                 "video_type": "explainer", "style_profile": "editorial",
                 "created_at": "...", "updated_at": "..." },
  "sources":   [ { "id": "src_1", "title": "...", "url": "https://...",
                   "retrieved_at": "...", "trust": "user_provided" } ],
  "brand":     { "name": "...", "colors": {}, "fonts": {}, "logo": null },
  "output":    { "preset": "youtube_16x9", "width": 1280, "height": 720,
                 "fps": 30, "bitrate_kbps": 6000,
                 "captions": { "mode": "burn_in", "format": "srt" } },
  "story":     { "logline": "...", "beats": [ /* Beat */ ] },
  "sequences": [ /* Sequence */ ],
  "audio":     { "narration_voice": {...}, "bgm": null, "mix": {...},
                 "loudness_target_lufs": -16 },
  "assets":    { "items": [ /* AssetRef */ ] },
  "quality":   { "checks": [...], "report": null },
  "provenance":{ "generator": "...", "prompts": [], "providers": {},
                 "created_by": "agent|studio|cli" }
}
```

## 2. Story beats — where rhythm comes from

```jsonc
{ "id": "b1", "t": 0.0, "kind": "hook",     "label": "问题先换掉",
  "intent": "推翻「先看排名」的默认动作" }
```

`kind ∈ hook | context | claim | evidence | turn | reveal | example |
comparison | payoff | cta | transition`.

Shot length is derived from beats + narration, **never** a uniform 5s grid.

## 3. Hierarchy

```
Sequence ▸ Scene ▸ Shot ▸ Layer
```

### Sequence

```jsonc
{ "id": "sq_1", "intent": "建立问题", "scenes": [ ... ] }
```

### Scene

```jsonc
{
  "id": "sc_1",
  "intent": "说明美国没有官方排名体系",
  "duration_hint_sec": 12.5,           // advisory; audio may override
  "narration": {                        // Narration IR
    "text": "申请美国学校，第一步不该是抄一张排名表。",
    "speaker": "narrator",
    "language": "zh-CN",
    "emotion": "calm",
    "pace": 0.96, "pitch": 0.0, "energy": 0.5,
    "emphasis": ["第一步", "不该"],
    "pause_after_ms": 280,
    "pronunciation": {},
    "style": "documentary"
  },
  "visual_strategy": "typography_led",  // typography_led | diagram_led |
                                        // image_led | data_led | screen_led |
                                        // avatar_led | broll | chart
  "sources": ["src_1"],
  "transition": { "type": "cut", "duration_ms": 0 },
  "shots": [ /* Shot */ ]
}
```

### Shot

```jsonc
{
  "id": "sh_1",
  "start": 0.0, "duration": 4.2,
  "camera": { "type": "static" },       // static | push | pull | pan | drift | zoom_mask
  "caption": { "text": "...", "position": "lower_third", "safe_area": true },
  "layers": [ /* Layer */ ]
}
```

### Layer — renderer neutral

```jsonc
{ "id": "ly_1", "type": "text", "role": "headline",
  "content": "没有官方排名，只有你的排序",
  "typography": { "size": "xl", "weight": 800, "align": "left", "tracking": "-0.03em" },
  "layout": { "x": 0.08, "y": 0.22, "w": 0.62, "h": 0.30, "anchor": "top_left" },
  "motion": { "enter": "rise", "duration_ms": 520, "easing": "ease_out_quint",
              "delay_ms": 120, "semantic": "reveal" },
  "style": { "color": "text", "opacity": 1.0 } }
```

`type ∈ text | image | video | svg | html | chart | shape | avatar | effect | audio`
`role ∈ headline | subhead | body | annotation | label | metric | evidence |
background | foreground | logo | caption`

There is **no** `remotionComponent`, no `cssClass`, no renderer-specific key at
this level. Renderers translate `type + role + layout + motion` into their own
output.

`motion.semantic` ties motion to meaning:

| semantic | meaning |
|---|---|
| `reveal` | something becomes known |
| `count` | a number grows |
| `trace` | a path is drawn |
| `connect` | a relation is established |
| `split` | a comparison appears |
| `depth` | hierarchy is shown |
| `progression` | a flow advances |
| `focus` | attention is pulled to a point |

Uniform `fade-up` on every element is an explicit anti-pattern — see
[references/visual-design-principles.md](references/visual-design-principles.md).

## 4. Narration IR

Not `text → wav`. The provider maps what it supports and ignores what it cannot:

```
text · speaker · language · voice · emotion · pace · pitch · energy
pause_before_ms · pause_after_ms · emphasis[] · pronunciation{} · style
```

`ProsodyPlanner` (post-Foundation) derives emphasis/breath groups/pauses from
the script. Until then, an LLM or a human may fill them; unknown fields are
optional.

## 5. AssetRef + provenance

```jsonc
{ "id": "as_1", "kind": "image", "origin": "local",
  "path": "assets/bg.jpg", "url": null, "license": "MIT",
  "generated": false, "generator": null, "prompt": null,
  "sha256": "...", "created_at": "...", "attribution": null }
```

`origin ∈ local | user | licensed_stock | generated | screenshot | recording |
remote`. Every asset is traceable; a video with no provenance is not shippable.

## 6. Output presets

`youtube_16x9 · youtube_shorts_9x16 · tiktok_9x16 · instagram_reels_9x16 ·
x_16x9 · bilibili_16x9 · xiaohongshu_3x4 · wechat_channels_9x16 · custom`

Preset controls resolution, fps, bitrate, **safe area** and caption size.

## 7. V1 → V2 migration

| V1 | V2 |
|---|---|
| `title`, `subtitle`, `author` | `project.title/subtitle`, `brand.name` |
| `language` | `project.language` |
| `voice {engine,name,rate}` | `audio.narration_voice` + provider hint |
| `sources[]` | `sources[]` (`id` added, URL preserved) |
| `scenes[].eyebrow` | `layers[]` with `role: "label"` |
| `scenes[].title` | `layers[]` with `role: "headline"` |
| `scenes[].body` | `layers[]` with `role: "body"` |
| `scenes[].narration` | `scene.narration.text` |
| `scenes[].tags[]` | `layers[]` with `role: "label"` |
| `scenes[].metric{,_label}` | `layers[]` with `role: "metric"` |
| — | one Shot per Scene, `visual_strategy: "typography_led"` |

Round-tripping is lossless for the fields above; migration is idempotent.

## 8. Validation

`schemas/video_ir_v2.schema.json` is generated from the Pydantic models and
checked in. `python -m html_video_workflow.cli validate project.json` validates
any file and reports path-level errors.
