# Kotassium UI rubric

Score each category 1 to 10. A 10 means nothing in the category needs a
change a careful designer would ask for. Every score needs evidence: a
screenshot path under `artifacts/ui/`, or a line of `tools/ui.py` output.
Write `no score` for a category you could not check. Do not invent one.

Reference points: a dark, high-contrast shell like Spotify (sidebar, hero
header, one green accent for the primary action), and the Polymarket card
language (a bold headline, one large figure per card, large unmistakable
action buttons, almost no chrome). Kotassium is a music player, not a to-do
list or a dashboard.

## Categories

1. **Cleanliness.** Each screen has one job. Little text, no empty columns,
   no dead controls, no copy that repeats the label beside it.
2. **Consistency.** One radius scale (pills 999, panels 8, covers 4 to 6), one
   icon scale (16, 20, 24), one control height per role, one accent colour.
3. **Attention.** The first thing the eye lands on is the thing to do next.
4. **Next-click prominence.** The action most likely to be clicked next is the
   most visually dominant control on the screen. Secondary actions recede.
5. **Icon centring.** Every icon-only control centres its glyph within 0.10px
   (`tools/ui.py` `{"icons": "all"}`). The play triangles carry a documented
   optical offset (AGENTS.md), so they are not judged on box centring.
6. **Typographic hierarchy.** Three clear levels (title, label, meta). Sizes
   come from the scale, not from one-off values.
7. **Spacing rhythm.** Gutters repeat (16, 24, 32). Groups are separated by
   more space than the items within them.
8. **Phone (390x844).** Tap targets at least 44px. No truncated essential
   title. No horizontal scroll (`{"layout": true}` reports `scrollX: false`).
9. **Desktop (1440x900).** Uses the width without dead space or cramped
   columns. The sidebar, content and player feel balanced.
10. **Other sizes.** Looks deliberate at 1024x700 and 1920x1080 too.
11. **States.** Empty, playing, paused and no-track states each say what to do
    next, in as few words as possible.
12. **Accessibility.** Text contrast at least 4.5:1. Every icon-only control
    has a label. Focus is visible on keyboard navigation.
13. **Motion and feedback.** Hover, press and active states respond at once.
    Motion is short. Reduced motion is respected.
14. **Scannability.** A list or grid reads at a glance: the title is clear, the
    meta is quiet, the columns line up.
15. **Brand fit.** Confident, dark and bold like the references, with one
    accent. It does not look like a generic admin panel.

## How to check

    venv/bin/python tools/ui.py tools/ui_views.json      # every view, both sizes
    venv/bin/python tools/ui.py '[{"goto":"/"},{"icons":"all"}]'
    venv/bin/python tools/ui.py '[{"size":[1024,700]},{"goto":"/"},{"shot":"t-home"}]'

Read a screenshot with the Read tool. Look at it. Then judge it.
