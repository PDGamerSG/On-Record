# Design direction: "night session"

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

A recording studio after dark. Near-black desk, hairline panels, film grain, and light coming only from the things that matter: speaker colours, the playhead, and the red of a live take.

- The chrome is monochrome. **Speaker colours are the only hues**, so they always mean "a person said this".
- Red (`--rec`) appears only while audio is being captured. A replay is not a capture, so the landing's "Replaying as live" dot is ink, not red.
- Primary buttons are light (ink on dark), not coloured.

## Tokens

Everything reads from [`apps/web/src/styles/tokens.css`](../apps/web/src/styles/tokens.css). Components use **only** tokens, so a restyle is a token swap. The landing page adds a few layout values of its own at the top of `landing.css`.

| Token | Value | Role |
|---|---|---|
| `--bg` / `--bg-2` | `#08090B` / `#0B0D10` | page; alternate bands |
| `--surface` / `-2` / `-3` | `#101216` / `#15181D` / `#1B1F25` | panels; hover and inputs; pressed and selected |
| `--surface-sunk` | `#0A0B0E` | wells: lanes, code, evidence quotes |
| `--ink` / `-2` / `-3` | `#ECEFF3` / `#A3ACB8` / `#6B7480` | text; secondary (AA); decorative or large only |
| `--line` / `--line-strong` | `#1E232A` / `#2C333C` | hairlines; control borders |
| `--rec` | `#FF4D3D` | live capture only |
| `--focus` | `#8AB4FF` | focus rings, links |
| `--on-spk` | `#08090B` | text on a speaker colour |

**Speaker palette.** Eight tape-label hues, brightened for the dark desk and assigned by speaker index: cobalt `#5B8CFF`, teal `#2CC4A8`, mustard `#F2B53A`, plum `#E066B3`, moss `#9BC53D`, rust `#F07A3C`, violet `#9B7BFF`, slate `#8CA0B3`. Text on a speaker colour is `--on-spk`. The canvas and WebGL art read these values from the CSS at runtime, so the record, the unspool and the lanes always match the tokens.

**Type.**
- **Recursive** carries the interface. `MONO 1` is for data only: timecodes, counts, model names, Cypher.
- **Newsreader** (variable, with optical sizes) is the voice of speech. It sets quoted speech in the app, and the landing page's headlines at weight 400 with `opsz` 72. One serif family does both jobs, so the product's display voice is literally the face of what people said.
- Body 15 px in the app, 17 to 19 px on the landing page. Headlines: `clamp(3rem, …, 5.75rem)`, line height 0.97, tracking −0.025em.
- Sentence case everywhere. No kicker labels above headings and no section numbers.

**Shape and depth.**
- Radius: 6 px chips and lane blocks, 8 px controls, 12 px panels, 16 to 22 px landing frames, fully round for landing buttons and the talkback button.
- Raised surfaces get a 1 px inner top highlight (`--hi`) instead of drop shadows. Landing frames (the live room, the Ask console, the sleeve) use a 1 px border at 8% white and one long, soft, offset shadow.
- Texture: film grain over the whole page (`body::after`) and a dot grid (`--dots`) behind wells.

## Motion

Easing is expo-out, `cubic-bezier(0.16, 1, 0.3, 1)`, everywhere.

- **One authored moment per surface.** On the landing page it's the record: the platter spins at 33⅓ rpm, the tonearm lifts, swings and lowers onto the current moment, and a jump in time lifts the arm instead of sliding it. The key light drifts and follows the pointer, so the colour in the grooves catches and moves.
- **The unspool** is scroll-driven: each turn of speech peels off the spiral, outer (earliest) turns first, and settles into its speaker's lane.
- **Reveals** are armed by JavaScript, so content is visible without it: headings rise out of a soft blur, framed product UI lifts and scales in, lists stagger by 70 ms.
- **Nav.** Solid with a hairline once you scroll, tucks away while you read down and returns when you scroll up. A pill slides under the section in view, and a reading-progress hairline runs along its bottom edge. The logo is a record, and it turns at 33⅓ rpm while the landing record plays.
- **Buttons.** The light primary has a single sheen sweep on hover and its arrow nudges right. Press states move 1 px.
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
8. **Closing.** "Put your next meeting on record." over the record rising from the bottom of the page, turning slowly under a light that stays put.
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
4. **Quiet chrome, bright voices.** Lucide icons at 1.75 stroke. No emoji, no sparkle icons, no decorative gradients in the app (the level meter and the landing's light are signal, not decoration).
