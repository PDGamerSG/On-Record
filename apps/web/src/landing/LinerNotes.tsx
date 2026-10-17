import { timecode } from "../lib/format";
import { SIDES } from "./sides";

const PERSONNEL: [string, string][] = [
  ["Gemma 4", "hears questions, answers, extracts decisions"],
  ["EmbeddingGemma 300M", "meaning search"],
  ["Silero VAD", "finds the speech"],
  ["TitaNet-small", "tells voices apart"],
  ["faster-whisper", "writes the words down"],
  ["FalkorDB", "stores every line as a graph"],
  ["Kokoro-82M", "voices the demo meetings"],
];

const MEASURED: [string, string, string][] = [
  ["Speaker attribution", "100%", "100%"],
  ["Diarization error", "0.0%", "0.3%"],
  ["Word error rate", "3.2%", "3.1%"],
];

// medians from replaying side B live, and from asking the demo questions, on an M1 Max with Gemma 4 E4B
const SPEED: [string, string][] = [
  ["Line in the graph, after a pause", "2.2 s"],
  ["Answer to a typed question", "5.1 s"],
  ["Hearing a spoken one", "+0.7 s"],
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
            Who played what, and how well it went.
          </p>
        </div>

        <div className="sleeve" data-reveal="frame">
          <figure className="sleeve-photo">
            <img src="/landing/stylus.webp" alt="Close-up of the stylus resting in the groove, which is banded in the colours of four speakers" loading="lazy" width={1600} height={1000} />
            <figcaption>Side A at {timecode(SIDES[0].decisions[0].made_at)}: Priya locks the Starter price.</figcaption>
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
                  {SPEED.map(([k, v]) => (
                    <tr key={k}>
                      <th scope="row">{k}</th>
                      <td className="tc" colSpan={2}>
                        {v}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="sleeve-small sleeve-honest">
                Measured on a MacBook (M1 Max) with Gemma 4 E4B and synthetic voices, so treat accuracy as an upper bound: real rooms have
                overlap and noise.
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
