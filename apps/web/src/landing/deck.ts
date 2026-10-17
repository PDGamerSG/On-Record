// One playback clock for the whole landing page: the record, the caption, the lanes and the transcript
// all read deck.time(). With sound off the clock is virtual (the page plays the meeting silently, as a
// muted video would); with sound on, the audio element is the clock. Seeking either way drops the needle.
import { useEffect, useState, useSyncExternalStore } from "react";
import { lineAt, SIDES, type Side } from "./sides";
import type { Utterance } from "../api/types";

type Listener = () => void;

export interface DeckState {
  side: number;
  sound: boolean;
  playing: boolean;
  loading: boolean;
  error: string | null;
  /** speed of the silent clock; audio always plays at 1x */
  rate: number;
}

export class Deck {
  private t0 = 0;
  private anchor = performance.now();
  private audio: HTMLAudioElement | null = null;
  private listeners = new Set<Listener>();
  state: DeckState = { side: 0, sound: false, playing: true, loading: false, error: null, rate: 1 };

  get current(): Side {
    return SIDES[this.state.side];
  }

  /** Seconds into the current side. Cheap; safe to call every frame. */
  time(): number {
    const a = this.audio;
    if (this.state.sound && a && !this.state.loading) return a.currentTime;
    if (!this.state.playing) return this.t0;
    const t = this.t0 + ((performance.now() - this.anchor) / 1000) * this.state.rate;
    if (t < this.current.duration) return t;
    this.t0 = 0; // the run-out groove: lift and start the side again
    this.anchor = performance.now();
    return 0;
  }

  seek(t: number): void {
    const clamped = Math.max(0, Math.min(this.current.duration - 0.25, t));
    this.t0 = clamped;
    this.anchor = performance.now();
    if (this.audio && this.state.sound) this.audio.currentTime = clamped;
    if (!this.state.playing) this.set({ playing: true });
    if (this.audio && this.state.sound && this.audio.paused) void this.playAudio();
    this.emit();
  }

  setSide(i: number): void {
    if (i === this.state.side) return;
    const keepSound = this.state.sound;
    this.stopAudio();
    this.t0 = 0;
    this.anchor = performance.now();
    this.set({ side: i, playing: true, error: null });
    if (keepSound) void this.setSound(true);
  }

  /** Speed up the silent replay (the live room uses 2x so lines land while you watch). */
  setRate(rate: number): void {
    if (rate === this.state.rate) return;
    this.t0 = this.time();
    this.anchor = performance.now();
    this.set({ rate });
  }

  togglePlaying(): void {
    if (this.state.playing) {
      this.t0 = this.time();
      this.audio?.pause();
      this.set({ playing: false });
    } else {
      this.anchor = performance.now();
      this.set({ playing: true });
      if (this.state.sound) void this.playAudio();
    }
  }

  async setSound(on: boolean): Promise<void> {
    if (!on) {
      this.t0 = this.time();
      this.anchor = performance.now();
      this.stopAudio();
      this.set({ sound: false, loading: false });
      return;
    }
    const t = this.time();
    const a = this.ensureAudio();
    a.currentTime = t;
    this.set({ sound: true, loading: true, playing: true, error: null, rate: 1 });
    await this.playAudio();
  }

  private ensureAudio(): HTMLAudioElement {
    const src = this.current.audio;
    if (this.audio && this.audio.dataset.src === src) return this.audio;
    this.audio?.pause();
    const a = new Audio(src);
    a.dataset.src = src;
    a.preload = "auto";
    a.addEventListener("ended", () => this.seek(0));
    a.addEventListener("waiting", () => this.set({ loading: true }));
    a.addEventListener("playing", () => this.set({ loading: false }));
    this.audio = a;
    return a;
  }

  private async playAudio(): Promise<void> {
    const a = this.ensureAudio();
    try {
      await a.play();
      this.set({ loading: false });
    } catch {
      // autoplay refused or the file is missing: fall back to the silent clock
      this.t0 = a.currentTime;
      this.anchor = performance.now();
      this.set({ sound: false, loading: false, error: "Couldn't start the audio. Click again to try." });
    }
  }

  private stopAudio(): void {
    if (!this.audio) return;
    this.audio.pause();
    this.audio = null;
  }

  dispose(): void {
    this.stopAudio();
    this.listeners.clear();
  }

  private set(patch: Partial<DeckState>): void {
    this.state = { ...this.state, ...patch };
    this.emit();
  }

  private emit(): void {
    for (const l of this.listeners) l();
  }

  subscribe = (l: Listener): (() => void) => {
    this.listeners.add(l);
    return () => this.listeners.delete(l);
  };

  snapshot = (): DeckState => this.state;
}

export function useDeckState(deck: Deck): DeckState {
  return useSyncExternalStore(deck.subscribe, deck.snapshot);
}

/** The line under the stylus and a whole-second clock, re-rendering only when either changes. */
export function useNowPlaying(deck: Deck): { line: Utterance | null; second: number } {
  const [now, setNow] = useState<{ line: Utterance | null; second: number }>(() => ({ line: lineAt(deck.current, deck.time()), second: 0 }));
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const t = deck.time();
      const line = lineAt(deck.current, t);
      const second = Math.floor(t);
      setNow((prev) => (prev.line === line && prev.second === second ? prev : { line, second }));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [deck]);
  return now;
}

/** Put the record on the right side, drop the needle on the line and turn the sound on. */
export function playLine(deck: Deck, side: Side, u: Utterance): void {
  deck.setSide(SIDES.indexOf(side));
  deck.seek(u.t_start + 0.05);
  if (!deck.state.sound) void deck.setSound(true);
}
