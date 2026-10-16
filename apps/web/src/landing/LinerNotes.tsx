import { timecode } from "../lib/format";
import { SIDES } from "./sides";

const PERSONNEL: [string, string][] = [
  ["Gemma 4 12B", "hears spoken questions natively, answers, calls tools, and reads decisions and owners out of the meeting. Runs locally through Ollama."],
  ["EmbeddingGemma 300M", "meaning search, fused with full-text and graph lookups."],
  ["Silero VAD", "finds the speech."],
  ["TitaNet-small", "tells the voices apart."],
  ["faster-whisper", "writes the words down."],
  ["FalkorDB", "the graph every line is written to, as it is spoken."],
  ["Kokoro-82M", "the four voices in the demo meetings."],
];

const MEASURED: [string, string, string][] = [
  ["Speaker attribution", "100%", "100%"],
  ["Diarization error", "0.0%", "0.3%"],
  ["Word error rate", "3.1%", "2.7%"],
];

export default function LinerNotes() {
  return (
    <section className="l-section notes" id="notes" aria-labelledby="notes-title">
      <div className="l-wrap">
        <div className="l-head">
          <h2 id="notes-title" className="l-h2" data-reveal>
            Liner notes.
          </h2>
          <p className="l-lede" data-reveal style={{ ["--d" as string]: 1 }}>
            Who played what on this record, and how well it went.</p>
        </div>

        <div className="sleeve" data-reveal="frame">
          <figure className="sleeve-photo">
            <img src="/landing/stylus.webp" alt="Close-up of the stylus resting in the groove, which is banded in the colours of four speakers" loading="lazy" width={1600} height={1000} />
            <figcaption>
              Side A at {timecode(SIDES[0].decisions[0].made_at)}, the moment Priya locks the Starter price. Rendered in Blender from the
              meeting’s own timings.
            </figcaption>
          </figure>

          <div className="sleeve-text">
            <div className="sleeve-block">
              <h3 className="sleeve-h">Tracklist</h3>
              <ol className="tracks">
                {SIDES.map((s) => (
                  <li key={s.id}>
                    <span className="tracks-side">{s.letter}</span>
                    <span className="tracks-title">
                      {s.title}
                      <span className="tracks-who">{s.speakers.map((x) => x.name).join(", ")}</span>
                    </span>
                    <span className="tc tracks-time">{timecode(s.duration)}</span>
                  </li>
                ))}
              </ol>
            </div>

            <div className="sleeve-block">
              <h3 className="sleeve-h">Personnel</h3>
              <dl className="personnel">
                {PERSONNEL.map(([who, what]) => (
                  <div key={who}>
                    <dt>{who}</dt>
                    <dd>{what}</dd>
                  </div>
                ))}
              </dl>
            </div>

            <div className="sleeve-block">
              <h3 className="sleeve-h">Measured</h3>
              <table className="measured">
                <thead>
                  <tr>
                    <th scope="col">
                      <span className="visually-hidden">Metric</span>
                    </th>
                    <th scope="col">Side A</th>
                    <th scope="col">Side B</th>
                  </tr>
                </thead>
                <tbody>
                  {MEASURED.map(([k, a, b]) => (
                    <tr key={k}>
                      <th scope="row">{k}</th>
                      <td className="tc">{a}</td>
                      <td className="tc">{b}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="sleeve-small">
                A line reached the graph about 2 to 3 seconds after its speaker paused, and a batch write took about 45 ms. Answers took about 2
                seconds with Gemma 4 E4B on a laptop RTX 4060.
              </p>
              <p className="sleeve-small sleeve-honest">
                Measured in the upstream build on synthetic voices, so treat these as an upper bound. Real rooms have overlap and noise, and
                overlapping speech currently goes to one speaker.
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
