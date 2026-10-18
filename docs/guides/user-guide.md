# User guide

How to use each page of the On Record web app. Run it with `npm run dev` in `apps/web` (see the [README quick start](../../README.md#quick-start)). Line numbers are as of commit `8943885`.

## Demo mode and live mode

The app decides once, before the first render, whether to use the API or the two bundled demo meetings: a `?demo=` query parameter wins, then `VITE_DEMO`, then a `GET /api/health` check (`apps/web/src/api/mode.ts:12-31`). No server in the repository answers `/api/health` yet, so the app runs in demo mode unless you force live mode, and in live mode most pages have no server routes to call (see [what is not in the repository yet](../ARCHITECTURE.md#what-is-not-in-the-repository-yet)). In demo mode the system status shows "Demo data" (`apps/web/src/components/shell/SystemStatus.tsx:116`) and changes such as ticking off an action item are kept in memory only (`apps/web/src/api/demo/demoApi.ts:1-3`).

| Action | Demo mode |
| --- | --- |
| Browse meetings, commitments, decisions, people and the graph | Works on the two bundled meetings |
| Ask a typed question | Answered by simple matching over the demo data, not by a model (`apps/web/src/api/demo/demoApi.ts:438`) |
| Ask a spoken question | Refused: "Spoken questions need Gemma 4 on the API server…" (`apps/web/src/api/demo/demoApi.ts:439-440`) |
| Start a live meeting or upload a recording | Refused with a 503 error (`apps/web/src/api/demo/demoApi.ts:373`, `apps/web/src/api/demo/demoApi.ts:395`) |

## Landing page (`/`)

The landing page plays a demo meeting on a 3D turntable, unwinds it into speaker lanes, replays the meeting room and runs a scripted Ask conversation (`apps/web/src/landing/LandingPage.tsx:1-2`, `apps/web/src/landing/AskDemo.tsx:1-2`). Its sections are described in [DESIGN.md](../DESIGN.md#landing-page). "Open the demo" leads into the app.

## Meetings (`/meetings`)

Lists meetings newest first, each with a strip of who spoke when, plus actions to start a meeting or upload a recording, and the graph totals (`apps/web/src/pages/MeetingsPage.tsx:44-53`, `apps/web/src/pages/MeetingsPage.tsx:110-114`). Select a meeting to open its room.

## Meeting room (`/m/:id`)

One meeting, from top to bottom (`apps/web/src/pages/MeetingRoom.tsx:1-2`):

- **Audio transport** (top right): play, the current position and download.
- **Speaker lanes**: one row per speaker, a block for each turn. Click a block to hear it; use the arrow keys to move between turns (`apps/web/src/components/meeting/SpeakerLanes.tsx:84-85`). Faded blocks are turns where the system is unsure who spoke (`apps/web/src/components/meeting/SpeakerLanes.tsx:128-129`). The rename key on a lane name sets the speaker's name; demo meetings can be renamed only in demo mode (`apps/web/src/pages/MeetingRoom.tsx:308`).
- **Transcript**: follows playback, and flashes a line you jump to.
- **Extracted by Gemma 4**: decisions, action items with a done toggle, and topics, each with the quote it came from; play the quote to hear that moment.

## Commitments (`/commitments`)

Action items across meetings, grouped by owner and filtered to open, done or all, with a done toggle and the evidence to play (`apps/web/src/pages/CommitmentsPage.tsx:1-2`, `apps/web/src/pages/CommitmentsPage.tsx:28-42`).

## Decisions (`/decisions`)

Each current decision above the earlier decisions it replaced, with the quotes behind them and a button to play each moment (`apps/web/src/pages/DecisionsPage.tsx:1-2`, `apps/web/src/pages/DecisionsPage.tsx:19-33`).

## People (`/people`)

A sortable table of people with their meetings, utterances, talk time and open items, and a "Who knows about…" search that ranks people by how much they said on a topic (`apps/web/src/pages/PeoplePage.tsx:13-20`, `apps/web/src/pages/PeoplePage.tsx:168-185`).

## Graph (`/graph`)

What FalkorDB stores for one meeting (the newest by default) or for all meetings. Choose a node in the graph or from "Go to a node" to see its properties and neighbours; zoom with the keys in the corner, the wheel, or `+`, `−` and `0` (`apps/web/src/pages/GraphPage.tsx:1-2`, [DESIGN.md](../DESIGN.md#app-shell)).

## Ask drawer (every app page)

Open it with Ask in the rail, the `/` key, or a question from the command palette (⌘K or Ctrl+K) (`apps/web/src/components/ask/AskDrawer.tsx:1`, `apps/web/src/components/CommandPalette.tsx:59`).

- **Scope**: ask about all meetings, or only the one you are in (`apps/web/src/components/ask/AskDrawer.tsx:450-460`).
- **Typing**: type a question and press Ask.
- **Speaking**: hold the talkback button or Space and release to send, click once to start and again to send, or turn on hands-free to send each question when you pause (`apps/web/src/components/ask/useVoiceQuestion.ts:1-4`). Spoken questions need a server (see the table above).
- **Answers** cite the lines they used; play a citation to hear it, and open "Why this answer" for the model, the searches and the Cypher queries. With "Speak answers" on, the answer is read aloud by the browser; pressing talkback interrupts it (`apps/web/src/components/ask/speech.ts:1`, `apps/web/src/components/ask/AskDrawer.tsx:261-268`).
- The conversation is kept for the browser tab (`apps/web/src/components/ask/askStore.ts:1`); "New conversation" starts again.

## Documents

There is no Documents page on `main`. The document routes are served by a separate API app (`apps/api/wsw_brain/documents/app.py:1-6`); see the [README](../../README.md#documents-with-sarvam-document-ai) and the [API reference](../api/README.md).

## Other controls

- **Command palette** (⌘K or Ctrl+K): go to a page, meeting or person, or ask a question.
- **Theme**: the sun and moon key switches between light and dark; the choice is remembered ([DESIGN.md](../DESIGN.md#tone)).
