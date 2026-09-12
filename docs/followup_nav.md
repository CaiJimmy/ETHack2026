# Follow-up: the left navigation

Raised by the project owner after the clarity critique was already running, so it is not in
docs/design_critique.md and the redesign agent did not see it.

## The note

The side panel is mainly an interactive chapter list. It is probably not needed at all, and if it is
kept it should collapse.

## Why it holds

It is a fixed 206px column on a 1280px recording frame, so it spends 16% of the width on navigation for
a page a judge scrolls through once. The critique measured it at 50 words repeated on every screen, and
it is the only element that appears in all 25 viewports of scroll.

The critique's own plan makes this worse rather than better: it proposes hanging a "How this works"
drawer off the nav, which entrenches a column we may not want.

## Options, in the order I would try them

1. Drop the nav. Replace it with the wordmark top left and let the page scroll. Reclaims 206px for the
   control surface, which is the screen that most needs the room.
2. Collapse it to a 48px rail of section numbers that expands on hover or click.
3. Keep it only on the control surface, where a judge may want to jump, and drop it below the fold.

Option 1 is the strongest for the recording. Option 2 keeps wayfinding for someone browsing the live
site afterwards. The decision changes the layout of section 01, so it has to be made before the demo is
re-recorded, not after.

## Sequencing

The clarity workflow re-records the demo in its verify phase. This change lands after that, so the
recording has to be redone once more. That is about twenty minutes and it is worth it: a stale GIF of a
superseded layout is worse than no GIF.
