"""
vad.py
Voice Activity Detection using Silero VAD.

Instead of cutting audio every fixed N seconds (which chops sentences), this
detects speech and yields a phrase when the speaker pauses OR when a max
duration cap is hit (so we don't wait forever during long monologues).

Silero VAD runs on CPU, lightweight — doesn't compete with Whisper for GPU.

Design: feed it 16kHz mono float32 audio in 512-sample frames. It tracks
speech start/stop. We buffer speech frames; when silence is detected after
speech (a pause) OR we hit the max cap, we emit the buffered phrase.
"""

import numpy as np
from silero_vad import load_silero_vad

# Silero expects exactly 512-sample frames at 16kHz.
FRAME_SIZE = 512
SAMPLE_RATE = 16000


class PhraseDetector:
    """
    Feed audio frames; get back complete phrases at natural pauses.

    Parameters:
      threshold:        speech probability cutoff (0-1). Higher = stricter.
      min_silence_ms:   silence after speech before we call it a pause.
      max_phrase_s:     hard cap so long monologues still get chunked.
      min_phrase_s:     ignore ultra-short blips (noise).
    """

    def __init__(self, threshold=0.5, min_silence_ms=400,
                 max_phrase_s=5.0, min_phrase_s=0.4):
        self.model = load_silero_vad()
        self.threshold = threshold
        self.min_silence_frames = int((min_silence_ms / 1000) * SAMPLE_RATE / FRAME_SIZE)
        self.max_phrase_frames = int(max_phrase_s * SAMPLE_RATE / FRAME_SIZE)
        self.min_phrase_samples = int(min_phrase_s * SAMPLE_RATE)

        self._buffer = []          # list of float32 frames (speech)
        self._silence_run = 0      # consecutive silent frames after speech
        self._in_speech = False
        self._frames_in_phrase = 0

    def reset(self):
        self.model.reset_states()
        self._buffer = []
        self._silence_run = 0
        self._in_speech = False
        self._frames_in_phrase = 0

    def _emit(self):
        if not self._buffer:
            return None
        phrase = np.concatenate(self._buffer)
        self._buffer = []
        self._silence_run = 0
        self._in_speech = False
        self._frames_in_phrase = 0
        self.model.reset_states()
        if phrase.size < self.min_phrase_samples:
            return None  # too short, likely noise
        return phrase

    def process_frame(self, frame: np.ndarray):
        """
        Feed one 512-sample float32 frame.
        Returns a phrase (np.float32 array) when one is ready, else None.
        """
        if frame.size != FRAME_SIZE:
            # pad/truncate defensively
            if frame.size < FRAME_SIZE:
                frame = np.pad(frame, (0, FRAME_SIZE - frame.size))
            else:
                frame = frame[:FRAME_SIZE]

        # Silero wants a torch tensor; it accepts numpy via its wrapper too,
        # but to be safe we pass through torch.
        import torch
        prob = self.model(torch.from_numpy(frame), SAMPLE_RATE).item()

        is_speech = prob >= self.threshold

        if is_speech:
            self._in_speech = True
            self._buffer.append(frame)
            self._silence_run = 0
            self._frames_in_phrase += 1
        else:
            if self._in_speech:
                # keep a little trailing silence in buffer for natural cutoff
                self._buffer.append(frame)
                self._silence_run += 1
                self._frames_in_phrase += 1

        # Emit on a pause after speech...
        if self._in_speech and self._silence_run >= self.min_silence_frames:
            return self._emit()

        # ...or if we've hit the max phrase length cap.
        if self._frames_in_phrase >= self.max_phrase_frames:
            return self._emit()

        return None
