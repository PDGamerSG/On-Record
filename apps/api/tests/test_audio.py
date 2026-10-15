from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from wsw_brain.contracts import SAMPLE_RATE
from wsw_brain.listen import (
    AudioTooLong,
    WavAppender,
    decode_file,
    float_to_pcm16,
    iter_decode,
    pcm16_to_float,
    write_wav,
)


def tone(rate: int = 44_100, duration_s: float = 1.5) -> np.ndarray:
    t = np.arange(int(rate * duration_s)) / rate
    return (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


def test_pcm16_round_trip_and_odd_payload_rejection() -> None:
    samples = np.linspace(-1.0, 1.0, 1001, dtype=np.float32)
    encoded = float_to_pcm16(samples)
    decoded = pcm16_to_float(encoded)
    assert decoded.dtype == np.float32
    assert np.max(np.abs(decoded - samples)) < 1e-4
    with pytest.raises(ValueError, match="odd number"):
        pcm16_to_float(b"\x00\x01\x02")


def test_decode_file_resamples_downmixes_and_writes_wav(tmp_path: Path) -> None:
    stereo = np.stack([tone(), tone()], axis=1)
    source = tmp_path / "source.wav"
    sf.write(source, stereo, 44_100, subtype="PCM_16")

    decoded = decode_file(source)
    assert decoded.dtype == np.float32
    assert decoded.ndim == 1
    assert abs(decoded.size - int(1.5 * SAMPLE_RATE)) < SAMPLE_RATE * 0.05

    output = write_wav(tmp_path / "nested" / "copy.wav", decoded)
    info = sf.info(str(output))
    assert info.samplerate == SAMPLE_RATE
    assert info.channels == 1


def test_decode_file_reads_compressed_upload(tmp_path: Path) -> None:
    import av

    path = tmp_path / "upload.ogg"
    container = av.open(str(path), mode="w", format="ogg")
    stream = container.add_stream("libopus", rate=48_000)
    stream.layout = "mono"
    samples = (0.4 * np.sin(2 * np.pi * 300 * np.arange(48_000) / 48_000)).astype(np.float32)
    frame = av.AudioFrame.from_ndarray((samples * 32767).astype(np.int16)[None, :], format="s16", layout="mono")
    frame.sample_rate = 48_000
    for packet in stream.encode(frame):
        container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()

    decoded = decode_file(path)
    assert abs(decoded.size - SAMPLE_RATE) < SAMPLE_RATE * 0.05


def test_iter_decode_yields_bounded_blocks(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    sf.write(source, np.zeros(int(SAMPLE_RATE * 2.5), dtype=np.float32), SAMPLE_RATE)
    blocks = list(iter_decode(source, block_s=1.0))
    assert len(blocks) == 3
    assert [block.size for block in blocks] == [SAMPLE_RATE, SAMPLE_RATE, SAMPLE_RATE // 2]


def test_decode_file_enforces_duration_limit(tmp_path: Path) -> None:
    source = tmp_path / "long.wav"
    sf.write(source, np.zeros(SAMPLE_RATE * 2, dtype=np.float32), SAMPLE_RATE)
    with pytest.raises(AudioTooLong, match="limit is 0:00:01"):
        decode_file(source, max_duration_s=1)


def test_wav_appender_is_readable_while_growing(tmp_path: Path) -> None:
    path = tmp_path / "recording.wav"
    recorder = WavAppender(path)
    recorder.append(np.full(SAMPLE_RATE // 2, 0.25, dtype=np.float32))
    with wave.open(str(path), "rb") as reader:
        assert reader.getnchannels() == 1
        assert reader.getframerate() == SAMPLE_RATE
        assert reader.getnframes() == SAMPLE_RATE // 2
    recorder.close()
    assert recorder.closed
    assert recorder.frames == SAMPLE_RATE // 2
    with pytest.raises(RuntimeError, match="already closed"):
        recorder.append(np.zeros(1, dtype=np.float32))
