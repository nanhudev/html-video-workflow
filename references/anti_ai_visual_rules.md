# Anti-AI Visual Rules

Machine-readable rules behind `VisualDesignCritic`. Every rule has an id, a
severity and a concrete remedy, so a violation is actionable rather than
atmospheric.

## Why there is no "AI score"

You will not find an `AI Feel = 37.52%` anywhere in this project.

A single number implies a measurement that does not exist. There is no ground
truth for "looks like AI", no calibration set, and no unit. Printing a decimal
would dress a handful of heuristics up as instrumentation, and then everyone
would optimise the decimal instead of the frames.

What we emit instead: **warnings**, each with severity, evidence and a
suggestion. Several warnings about the same scene is information. `AI Feel 62/100`
is a vibe wearing a lab coat.

## Severity levels

| Level | Meaning |
| --- | --- |
| `error` | Almost certainly reads as generated. Fix before shipping. |
| `warning` | A real risk. Worth a deliberate decision to keep. |
| `info` | Notable, but may be exactly right for this scene. |

## Rules

### AA-001 · uniform-motion
**Severity:** error
Every animated layer shares one start time, one duration or a constant stagger
(e.g. `delay = i * 100ms`). This is *the* signature of a template firing.
**Evidence:** distinct start times / total layers.
**Suggestion:** weight delays and durations by layer role; let some layers
overlap entirely.

### AA-002 · identical-motion
**Severity:** warning
All layers use the same primitive. Even with good timing, one entrance style
reads as a batch process.
**Evidence:** count of distinct primitives.
**Suggestion:** pick the primitive from each layer's semantic intent.

### AA-003 · everything-centered
**Severity:** warning
`text-align: center` on every layer. Centring is a valid choice for one
element and a statement of nothing for five.
**Suggestion:** use `editorial_left` / `editorial_right`, or reserve `center`
for genuinely single-message scenes.

### AA-004 · flat-hierarchy
**Severity:** error
Largest text is under 1.6x the smallest *meaningful* text. Without optical
distance there is no entry point for the eye.
**Evidence:** ratio between the largest and median type size.
**Suggestion:** use a `TypographyProfile`; promote a sole headline to `display`.

### AA-005 · too-many-layers
**Severity:** warning
More than five layers carrying text. The eye cannot sequence them in the time a
scene is on screen.
**Suggestion:** split the scene, or demote detail to narration.

### AA-006 · safe-area-violation
**Severity:** error (was: silently ignored)
Content intrudes into a platform's overlay region. On TikTok/Reels the headline
ends up under the like rail and the last line behind the caption block.
**Evidence:** the specific inset breached.
**Suggestion:** enable safe areas, or move the layer inside them.

### AA-007 · accent-everywhere
**Severity:** warning
Every layer uses the accent colour. Accent means "look here"; applied globally it
means nothing.
**Suggestion:** reserve accent for one element per scene.

### AA-008 · no-negative-space
**Severity:** info
Layer bounding boxes cover more than ~75% of the usable area. Frames need air.
**Suggestion:** remove a layer or shrink the boxes.

### AA-009 · repeated-scene-structure
**Severity:** warning
Consecutive scenes use the same layout **and** the same motion set. A viewer
reads repetition across scenes far faster than within one.
**Suggestion:** vary layout between neighbours — see `SceneVariationPolicy`.

### AA-010 · long-line-length
**Severity:** info
Body lines exceed ~44 CJK characters (or ~80 Latin). Long lines are hard to
read in motion, where there is no time to re-read.
**Suggestion:** narrow the slot or split the sentence.

### AA-011 · low-contrast
**Severity:** error
Text contrast below WCAG AA (4.5:1 for body, 3:1 for large text). This is both an
accessibility failure and a legibility failure once the frame is compressed.
**Evidence:** computed ratio.
**Suggestion:** change the text or the background, not the opacity.

### AA-012 · synchronous-exit
**Severity:** info
No layer has any exit or continuous motion; everything enters and freezes. Real
scenes breathe.
**Suggestion:** add parallax to the background layer.

## Adding a rule

A rule is lintable only if it can be checked from data the compiler already has.
If you find yourself wanting to analyse pixels, you probably want a *visual
regression test* instead — that compares frames, which is honest, rather than
scoring them, which is not.
