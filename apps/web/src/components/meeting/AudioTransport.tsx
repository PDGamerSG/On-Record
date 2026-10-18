import { DownloadSimpleIcon, PauseIcon, PlayIcon } from "@phosphor-icons/react";
import { timecode } from "../../lib/format";
import type { AudioElementState } from "./useAudioElement";

interface Props {
  src: string;
  title: string;
  audio: AudioElementState;
  fallbackDuration: number;
}

/** Transport for a recorded meeting: play/pause, position and a download. The speaker lanes are the scrubber. */
export default function AudioTransport({ src, title, audio, fallbackDuration }: Props) {
  const total = audio.duration || fallbackDuration;
  // the API serves WAV, but a recording with its own extension in the URL (the demo's .m4a) keeps it
  const ext = /\.([a-z0-9]{2,4})$/i.exec(src.split(/[?#]/)[0])?.[1]?.toLowerCase() ?? "wav";
  const fileName = `${title.replace(/[\\/:*?"<>|]+/g, " ").trim() || "meeting"}.${ext}`;
  return (
    <div className="transport">
      <div className="transport-row">
        <button
          type="button"
          className="transport-play"
          onClick={audio.toggle}
          disabled={!!audio.error}
          aria-label={audio.playing ? "Pause recording" : "Play recording"}
        >
          {audio.playing ? <PauseIcon weight="fill" aria-hidden="true" /> : <PlayIcon weight="fill" aria-hidden="true" />}
        </button>
        <span className="transport-time tc">
          <span className="transport-now">{timecode(audio.time)}</span>
          <span className="transport-of"> / {timecode(total)}</span>
        </span>
        <a className="transport-dl" href={src} download={fileName} aria-label="Download audio" title="Download audio">
          <DownloadSimpleIcon aria-hidden="true" />
        </a>
      </div>
      <audio ref={audio.attach} className="transport-audio" src={src} preload="metadata" aria-label="Meeting recording" />
      {audio.error && (
        <p className="transport-error" role="alert">
          {audio.error}
        </p>
      )}
    </div>
  );
}
