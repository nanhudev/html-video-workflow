# Visual Design Principles

This is the design contract for everything that renders pixels. It exists because
generated video has a recognisable smell: centred text, uniform three-second
scenes, one fade for every transition, and a stock gradient behind it all.

The rules below are enforced where they can be enforced (schema + renderer), and
documented where they cannot.

---

## 1. Motion must carry meaning

Every animated layer declares `motion.semantic`. A renderer is allowed to choose
*how* to express a semantic, but never to invent a different one.

| semantic | means | typical expression |
|---|---|---|
| `reveal` | this content appears as a unit | fade + small rise |
| `count` | the number is the point | numeric roll-up, tick marks |
| `trace` | follow a path or process | drawing line, travelling dot |
| `connect` | relate two things | link growing between anchors |
| `split` | contrast or divergence | two halves separating |
| `depth` | establish scale or foreground | parallax shift |
| `progression` | position within a sequence | progress bar, index tick |
| `focus` | isolate one item from many | dimming siblings |
| `drift` | ambient, non-informative | slow background movement |

**Forbidden:** `fadeIn` as the only motion on a scene whose point is a number, a
comparison, or a process. If the semantic is `count`, a fade is a lie about what
matters.

## 2. Duration is content, not a constant

Scene length comes from narration length plus a deliberate pause, never from a
fixed slot. The mock planner in `providers/llm/mock_llm.py` varies duration as
`3.4 + 0.9 * index` specifically so that uniform timing cannot creep back in
unnoticed.

- A scene with one short line may run 2.5 s.
- A scene carrying a definition runs as long as the sentence does.
- Never pad to a round number. `7.0` is suspicious; `6.8` is honest.

`tests/test_project_ir.py` asserts that generated durations are non-uniform.

## 3. Composition rules

**Asymmetric anchors.** Text does not sit dead centre by default. Anchors are
chosen from an asymmetric set (`start/end`, `upper_left/lower_right`) so the eye
has a path. Dead centre is reserved for a deliberate single-statement beat.

**One focal point.** Exactly one layer per shot may carry `role="headline"`.
Two headlines means no headline.

**Role drives typography.** Sizes come from `ROLE_STYLE` in
`providers/renderer/document.py`, not from ad-hoc inline styles. The scale is
deliberately wide (60px headline vs 15px annotation) so hierarchy survives on a
phone.

**Negative space is a layer.** Layout positions are expressed as ratios in
`[0,1]` (`Layout` clamps them), so margins scale with the frame instead of
breaking on a different aspect ratio.

## 4. Colour and surface

- Themes are data (`providers/renderer/themes.py`), never branches in render code.
- The ten original themes are preserved verbatim; changing them changes existing
  users' output, which is a breaking change.
- Glow and texture are accent devices. A surface that is *only* gradient plus
  glow is the AI-slideshow look this project exists to avoid.
- Contrast is checked at render time; body text below 4.5:1 against its surface
  is a bug, not a style choice.

## 5. The renderer must stay neutral

The IR may not contain `remotionComponent`, `cssClass`, `templateId`, or any
other renderer-specific token. If a designer wants a new effect, it is added as a
`motion.semantic` value or a layer `role` — both of which every renderer must
interpret — not as a CSS hook that only one renderer understands.

This is asserted in `tests/test_providers.py` (`test_document_is_renderer_neutral`).

## 6. Text that ends up on screen

- Narration and on-screen text are different artifacts. The caption track is
  generated from `narration.text`; a headline is what the viewer reads, and the
  narrator may say more than that.
- No sentence should be split across a scene boundary mid-clause.
- Punctuation in captions follows the narration exactly. Do not "tidy" it.

## 7. Review checklist

Before calling a visual change done:

- [ ] Does each animated layer's semantic match what the content *means*?
- [ ] Are scene durations non-uniform, and justified by their content?
- [ ] Is there exactly one focal layer per shot?
- [ ] Do positions use ratios rather than pixels?
- [ ] Does the IR remain renderer-neutral?
- [ ] Does the theme come from the theme table rather than inline code?
- [ ] Would a viewer notice the machinery? If yes, simplify.
