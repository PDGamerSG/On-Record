# Design direction: "studio daylight"

**Subject.** Meetings as recorded audio: who spoke, when, and what they committed to.

**Audience.**
- Team leads and ICs looking for "who said what" after the fact.
- Judges at a two-minute expo demo, who meet the landing page first.

**Primary job.** Make speaker-attributed speech feel tangible, checkable and askable.

**The memorable thing** is the **speaker lane**, carried onto a **record**.
- In the app, one horizontal lane per speaker shows blocks where they spoke, like a studio multitrack.
- On the landing page the same meeting is pressed into vinyl. The groove runs from the outer edge (00:00) to the label (the last word), and every band of groove is tinted for whoever was speaking. Click a groove and the needle drops there: the audio plays and the caption names the speaker.
- Scrolling on unwinds the record into the multitrack, so the two views read as one idea.

## Tone

A recording studio in daylight. Warm paper behind white panels, hairline borders, soft shadows, and the black turntable shot like a product on a seamless backdrop. Colour comes only from the things that matter: speaker colours, the playhead, and the red of a live take.

- The chrome is neutral. **Speaker colours are the only hues**, so they always mean "a person said this".
- Red (`--rec`) appears only while audio is being captured. A replay is not a capture, so the landing's "Replaying as live" dot is ink, not red.
- Primary buttons are ink (white text on near-black), not coloured.
- Fewer words. Every section makes one point in one or two sentences; details sit behind a click ("Why this answer", the status popover).

**Night session.** The same studio after dark is one click away: the sun and moon key in the landing nav or the app sidebar (or "Switch to dark mode" in the command palette) sets `data-theme="dark"` on `<html>`. The choice is kept in `localStorage`, and `index.html` applies it before the first paint, so the page never flashes the wrong theme. Daylight is the default.

## Tokens

Everything reads from [`apps/web/src/styles/tokens.css`](../apps/web/src/styles/tokens.css). Components use **only** tokens, so a restyle is a token swap. The landing page adds a few layout values of its own at the top of `landing.css`.

| Token | Value | Role |
|---|---|---|
| `--bg` / `--bg-2` | `#F6F5F2` / `#EFEDE8` | page (warm paper); alternate bands |
| `--surface` / `-2` / `-3` | `#FFFFFF` / `#F3F2EE` / `#E9E7E2` | panels; hover and inputs; pressed, selected and segmented tracks |
| `--surface-sunk` | `#F8F7F4` | wells: lanes, code, evidence quotes |
| `--ink` / `-2` / `-3` | `#15171C` / `#535963` / `#6E7480` | text (17.9:1 on white); secondary (7:1); tertiary (4.7:1) |
| `--line` / `--line-strong` | `#E7E5DF` / `#D6D3CB` | hairlines; control borders |
| `--rec` | `#DC2F22` | live capture only |
| `--focus` | `#2563EB` | focus rings, links |
| `--on-ink` / `--on-spk` | `#FFFFFF` | text on ink and on a speaker colour |
| `--tint` / `--shade` / `--paper` | RGB channels | translucent fills (`rgb(var(--tint) / 0.06)`), shadows, and rings in the page colour; they flip with the theme |
| `--glass` / `--pool` | frosted white / soft white | frosted bars (landing nav, transport, zoom keys); the light behind the hero deck |
| `--side-bg` | `#ECEBE5` | the desk the app sidebar and the page panel sit on (`#040506` at night) |

Dark mode overrides the same names under `:root[data-theme="dark"]`: near-black desk (`#08090B` page, `#101216` panels), `#ECEFF3` ink, light primary buttons, and the speaker hues brightened for the dark desk (cobalt `#5B8CFF`, teal `#2CC4A8`, mustard `#F2B53A`, plum `#E066B3`, …). Canvas and WebGL art re-read the tokens when the theme switches, so the graph, the unspool and the record's grooves always match it.

**Speaker palette.** Eight tape-label hues, deepened for paper. Each meeting assigns them to its speakers (`color_idx`), and a renamed or merged speaker keeps theirs, so quotes, lanes and the graph look the colour up in the meeting rather than from the track number: cobalt `#3366E6`, teal `#0C8A7C`, mustard `#C58A0A`, plum `#C03B8C`, moss `#5B8A14`, rust `#D0521B`, violet `#7450E0`, slate `#5C7085`. Each is at least 3:1 on white. Text on a speaker colour is `--on-spk`; a speaker's name set *in* their colour uses `--spk-text`, the hue mixed 20% toward black so it reads at AA. The canvas and WebGL art read these values from the CSS at runtime, so the record, the unspool and the lanes always match the tokens.

**Type.**
- **Inter** (variable, optical sizes) carries the interface.
- **Recursive Mono** (`--font-mono`) is for data only: timecodes, model names, Cypher.
- **Newsreader** (variable, with optical sizes) is the voice of speech. It sets quoted speech in the app, and the landing page's headlines at weight 400. One serif family does both jobs, so the product's display voice is literally the face of what people said.
- Body 15 px in the app, 17 to 20 px on the landing page. Headlines: `clamp(3rem, …, 5.75rem)`, line height 0.97, tracking −0.03em. Ledes stop at about 40 characters a line.
- Sentence case everywhere. No kicker labels above headings and no section numbers.

**Shape and depth.**
- Radius: 6 px chips and lane blocks, 10 px controls, 14 px panels, 18 to 22 px landing frames, fully round for buttons, badges, the audio transport and the talkback button.
- Panels are white on paper with a hairline and a barely-there shadow (`--shadow-panel`); things that float (popovers, the Ask drawer, the palette) use `--shadow-float`. Landing frames use one long, soft, offset shadow.
- Speakers appear as a round initial in a 14% tint of their colour, in the lanes and the transcript.

## Motion

Easing is expo-out, `cubic-bezier(0.16, 1, 0.3, 1)`, everywhere.

- **One authored moment per surface.** On the landing page it's the record: the platter spins at 33⅓ rpm, the tonearm lifts, swings and lowers onto the current moment, and a jump in time lifts the arm instead of sliding it. The key light drifts and follows the pointer, so the colour in the grooves catches and moves.
- **The unspool** is scroll-driven: each turn of speech peels off the spiral, outer (earliest) turns first, and settles into its speaker's lane.
- **Reveals** are armed by JavaScript, so content is visible without it: headings rise out of a soft blur, framed product UI lifts and scales in, lists stagger by 70 ms.
- **Nav.** Transparent over the hero; once you scroll it becomes a floating capsule of frosted paper, tucks away while you read down and returns when you scroll up. A pill slides under the section in view, and a reading-progress hairline runs inside the capsule. The logo is a record, and it turns at 33⅓ rpm while the landing record plays.
- **Buttons.** The ink primary has a single sheen sweep on hover and its arrow nudges right. Press states move 1 px.
- `prefers-reduced-motion` stops all of it: the record is drawn once with the needle in place, the unspool shows the finished lanes, and nothing reveals.

## Landing page

Sections, top to bottom:
1. **Hero.** Headline, one line of support, two buttons (open the demo, see how it works). On the right, the turntable plays the demo meeting. Under it, the line being spoken is captioned in the speaker's colour, with a transport: side A or B (the two demo meetings), a tape strip of who spoke when, previous and next line, and **Listen** (a dashed "sound gate"; audio only starts on a click). On narrow screens the record comes first.
2. **Built on.** A quiet row of the open models and the database.
3. **The groove is the timeline.** The scroll-driven unspool from record to lanes.
4. **It listens while you talk.** The four pipeline stages, then the app's real meeting-room components (lanes, transcript, Gemma's extractions) replaying the record as if it were live. While it's on screen and silent it cues to just before the first decision and runs at 2x, so lines and decisions land while you watch.
5. **Decisions that know when they changed.** The Starter-price decision from one meeting, superseded by the next; each card plays its evidence on the record. Open commitments by owner.
6. **Ask it out loud.** The talkback microphone (rendered in Blender), and the demo conversation run through the app's own demo Ask engine: "What did Priya commit to?", "And when is that due?", "Mark it done." Citations play on the record. "Why this answer" shows the tools Gemma called, the timings and the Cypher.
7. **Liner notes.** A record sleeve's back: the stylus close-up, the tracklist (the two meetings), personnel (each model and its job) and the measured results, with an honest note on what they were measured on.
8. **Closing.** "Put your next meeting on record." on clean paper, with the record rising from the bottom of the page beneath it, turning slowly under a light that stays put.
9. **Footer.** Links, the event and track, and a large wordmark.

The demo link opens the pricing review's meeting room in demo mode, and the meetings list when a live API is running (its meeting ids are its own).

## 3D assets

Everything 3D is built from scripts, so it can be rebuilt or restyled:

- [`scripts/blender/build_turntable.py`](../apps/web/scripts/blender/build_turntable.py) models the turntable procedurally (plinth, strobe-dot platter, record, tonearm with `ArmPivot` and `ArmLift` nodes) and exports the GLB, the baked contact shadow and the stylus, still and record renders. The record's grooves and label in the stills are pressed from `fixtures.json`.
- [`scripts/blender/build_mic.py`](../apps/web/scripts/blender/build_mic.py) renders the talkback microphone.
- [`scripts/blender/build.sh`](../apps/web/scripts/blender/build.sh) runs both, compresses the GLB with meshopt (keeping the record's UVs and the node tree), and writes WebP images to `public/landing/`.
- In the browser, the grooves, roughness and label are drawn on canvases from the same fixtures, so switching sides re-presses the record. The grooves use radial anisotropy, which gives the bow-tie sheen of real vinyl.

## Principles

1. **Speech is evidence.** Every claim the AI makes sits next to the quote it came from: speaker colour, name, timecode, and a play button.
2. **Show the machine honestly.** Label which model did what. Count graph writes in plain numbers. Say when something is demo data, a replay, or measured on synthetic voices.
3. **Red means live.**
4. **Quiet chrome, bright voices.** Phosphor icons, regular weight, switching to fill for the current section and for transport glyphs. No emoji, no sparkle icons, no decorative gradients in the app (the level meter and the landing's light are signal, not decoration).

## App shell

A sidebar on the desk at the left, and the page on its own inset panel beside it.
- **Top:** the record mark and name (with a "Demo" chip on bundled data) and search (⌘K opens the command palette).
- **Sections:** the five sections, each with a live count (open commitments on an ink badge, a red "Live" tag while a meeting records). The current one sits on a white key that slides between rows.
- **Recent meetings:** each drawn as a small record whose grooves are its speakers' colours, sized by talk time. It turns on hover, and keeps turning while live.
- **Open commitments:** the newest three, each ruled in its owner's colour.
- **Foot:** **Ask**, the only dark control, then the system status, the light/dark key and the fold key.

The sidebar folds to a 64 px icon rail (the fold key or `[`, remembered across visits), with name tags beside each icon; icons sit on the same axis in both widths, so folding only clips labels. Below 1100 px it is always the rail. On phones it is a drawer behind a slim top bar (menu, mark, status, Ask), closing on Escape, the scrim or any link. The meeting room puts the title and its facts on the left and the audio transport, one pill holding play, position and download, on the right; the lanes, transcript and Gemma's extractions sit below.

The graph has a small stack of zoom keys in its corner (in, out, fit, with the current zoom between them); the wheel, a pinch and the `+`, `−` and `0` keys do the same. Choosing a node, in the graph or from "Go to a node", brings it to the middle and close enough to read its neighbours.
