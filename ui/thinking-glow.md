# Thinking glow for the chat panel

Option B, the breathing amber halo, shown **only while Bench Buddy is thinking**, with a bright amber edge that travels around the panel border.

- **Idle:** the panel looks the same as it does now.
- **Thinking:** a soft amber halo pulses around the panel, and a bright segment runs around the border.
- **Done thinking:** both fade out over about 0.4 s.

Nothing in the app has been changed yet. To apply it, make the two edits below.

---

## 1. CSS: add to `styles.css`

Put this right after the `.panel{...}` rule (around line 79).

```css
/* ---------- thinking glow ---------- */
@property --glow-a{syntax:"<angle>";inherits:false;initial-value:0deg}
@keyframes glow-spin{to{--glow-a:360deg}}
@keyframes glow-breathe{
  0%,100%{box-shadow:var(--shadow),0 0 0 1px rgba(244,183,58,.55),0 0 18px 2px rgba(244,183,58,.22)}
  50%    {box-shadow:var(--shadow),0 0 0 1px rgba(244,183,58,.9), 0 0 36px 8px rgba(244,183,58,.42)}
}

.panel{transition:box-shadow .4s var(--ease)}
.panel.thinking{animation:glow-breathe 2.4s ease-in-out infinite}

/* the travelling edge: a conic gradient masked down to a 2px ring */
.panel::before{content:"";position:absolute;inset:0;z-index:5;border-radius:inherit;padding:2px;pointer-events:none;
  background:conic-gradient(from var(--glow-a),transparent 0 62%,rgba(244,183,58,.35) 76%,#f4b73a 90%,#fff1c9 94%,transparent 97%);
  -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);
  -webkit-mask-composite:xor;mask-composite:exclude;
  opacity:0;transition:opacity .4s var(--ease)}
.panel.thinking::before{opacity:1;animation:glow-spin 2.2s linear infinite}

/* reduced motion: keep a steady halo + static edge, no pulsing or spinning */
@media (prefers-reduced-motion:reduce){
  .panel.thinking{box-shadow:var(--shadow),0 0 0 1px rgba(244,183,58,.8),0 0 24px 4px rgba(244,183,58,.3)}
}
```

### How it works

| Piece | What it does |
|---|---|
| `glow-breathe` | Pulses the amber halo by adding two layers to the panel's existing `--shadow`, which stays intact. A panel's own `box-shadow` isn't clipped by its `overflow:hidden`, so the glow shows outside the card. |
| `.panel::before` | A full-size overlay painted with a conic gradient that is mostly transparent, with one bright amber tail. The mask removes everything except a 2px ring, so only the border lights up. |
| `@property --glow-a` | Registers the angle so it can be animated. Rotating it moves the bright tail around the ring. |
| `pointer-events:none` | Lets clicks pass through the overlay, so the chat stays usable. |

### Tweaks

- **Speed:** `glow-spin 2.2s`. Lower means faster.
- **Tail length:** `62%` is where the tail starts. Lower values give a longer tail.
- **Edge thickness:** `padding:2px` on `::before`.
- **Halo strength:** the `36px 8px` and `.42` values in the 50% keyframe.
- **Color:** the amber is `#f4b73a`, the same as `--accent`.

### Notes

- The panel is a tall rectangle, so the edge moves a little faster along the short top and bottom sides than down the long sides. That comes from how conic gradients work, and it looks fine in motion.
- Browsers without `@property` (Firefox before 128) show the halo and a **static** bright edge instead of a rotating one.
- The existing global reduced-motion rule (`styles.css:301`) already cuts the animations short. The extra media query above keeps the glow visible as a steady state.

---

## 2. JS: one line in `js/app.mjs`

In `thinking(on)` (around line 332), toggle the class on the panel:

```js
function thinking(on) {
  ui.thinking = on;
  document.querySelector(".panel").classList.toggle("thinking", on);   // ← add
  $("log").querySelector(".typing")?.remove();
  if (on) { $("log").append(typingEl()); $("log").scrollTop = $("log").scrollHeight; avatar("thinking"); setStatus("Thinking…"); }
  else if ($("avatar").classList.contains("thinking")) avatar("");
}
```

`thinking()` already runs at every point where the bot starts or stops thinking: after a send, on CHECK, after push-to-talk with server STT, and on reset. So the glow follows the typing dots automatically, and nothing else needs wiring.
