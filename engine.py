"""Hangmotor: előre dekódolt zene + pontos "most hallható" óra.

A lényeg: a hangkártya callbackje minden blokknál megmondja, hogy az adott
blokk első mintája MIKOR fog ténylegesen megszólalni (outputBufferDacTime).
Ezeket a (időpont, mintaszám) párokat eltesszük, és a kirajzolásnál a
pillanatnyi óraidőből visszaszámoljuk, melyik minta szól ÉPPEN a hangszóróban.
Így a kép nem a feldolgozáshoz, hanem a hallható hanghoz igazodik.
"""

import collections
import os
import threading

import miniaudio
import numpy as np
import sounddevice as sd

AUDIO_EXTS = {".mp3", ".flac", ".wav", ".ogg"}


def pick_output_device():
    """WASAPI alapértelmezett kimenet (Windowson ennek a legkisebb a késése)."""
    try:
        for api in sd.query_hostapis():
            if "WASAPI" in api["name"] and api["default_output_device"] >= 0:
                dev = api["default_output_device"]
                return dev, int(sd.query_devices(dev)["default_samplerate"])
    except Exception:
        pass
    dev = sd.default.device[1]
    return dev, int(sd.query_devices(dev, "output")["default_samplerate"])


class Track:
    def __init__(self, path, samples, sr, kbps, khz, channels):
        self.path = path
        self.samples = samples          # int16, (n, 2)
        self.sr = sr
        self.kbps = kbps
        self.khz = khz
        self.channels = channels

    @property
    def frames(self):
        return len(self.samples)

    @property
    def duration(self):
        return self.frames / self.sr


# A miniaudio fájlnév alapú függvényei Windowson nem boldogulnak az ékezetes
# útvonalakkal (pl. "Gáspár Laci"), ezért a fájlt mi olvassuk be, és a
# memóriából dekódolunk.
_INFO_BY_EXT = {
    ".mp3": miniaudio.mp3_get_info,
    ".flac": miniaudio.flac_get_info,
    ".ogg": miniaudio.vorbis_get_info,
    ".wav": miniaudio.wav_get_info,
}


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def _info(path, data):
    ext = os.path.splitext(path)[1].lower()
    return _INFO_BY_EXT.get(ext, miniaudio.mp3_get_info)(data)


def file_info(path):
    """(időtartam mp, eredeti mintavétel, csatornák) – a lejátszási listához."""
    info = _info(path, _read(path))
    return info.duration, info.sample_rate, info.nchannels


def load_track(path, sr):
    """A teljes számot előre dekódolja a hangkártya mintavételi frekvenciájára."""
    data = _read(path)
    info = _info(path, data)
    dec = miniaudio.decode(
        data,
        output_format=miniaudio.SampleFormat.SIGNED16,
        nchannels=2,
        sample_rate=sr,
    )
    samples = np.frombuffer(dec.samples, dtype=np.int16).reshape(-1, 2)
    kbps = 0
    if info.duration > 0:
        kbps = int(round(os.path.getsize(path) * 8 / info.duration / 1000))
    return Track(path, samples, sr, kbps, info.sample_rate // 1000, info.nchannels)


class Player:
    def __init__(self):
        self._lock = threading.Lock()
        self._track = None
        self._pos = 0
        self._playing = False
        self.ended = False
        self.volume = 0.8
        self.balance = 0.0
        # (dac_idő, kezdő_minta, minták_száma, track) – az utolsó néhány blokk
        self._hist = collections.deque(maxlen=256)
        self.stream = None
        self.device, self.sr = pick_output_device()
        try:
            self._open(self.device, self.sr)
        except Exception:
            dev = sd.default.device[1]
            self._open(dev, int(sd.query_devices(dev, "output")["default_samplerate"]))
            self.device = dev

    def _open(self, dev, sr):
        self.sr = sr
        self.stream = sd.OutputStream(
            device=dev, samplerate=sr, channels=2, dtype="float32",
            latency="low", callback=self._callback,
        )
        self._latency = self.stream.latency
        self.stream.start()

    def close(self):
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()

    # --- hangkártya szál ---------------------------------------------------
    def _callback(self, out, frames, tinfo, status):
        dac = tinfo.outputBufferDacTime
        if not dac:
            dac = tinfo.currentTime + self._latency
        v = self.volume ** 1.5 / 32768.0
        gl = v * min(1.0, 1.0 - self.balance)
        gr = v * min(1.0, 1.0 + self.balance)
        with self._lock:
            track, pos = self._track, self._pos
            if self._playing and track is not None:
                n = min(frames, track.frames - pos)
                chunk = track.samples[pos:pos + n]
                out[:n, 0] = chunk[:, 0] * gl
                out[:n, 1] = chunk[:, 1] * gr
                out[n:] = 0
                self._pos = pos + n
                if self._pos >= track.frames:
                    self._playing = False
                    self.ended = True
            else:
                n = 0
                out.fill(0)
            self._hist.append((dac, pos, n, track))

    # --- vezérlés ----------------------------------------------------------
    def load(self, track):
        with self._lock:
            self._track = track
            self._pos = 0
            self._playing = False
            self.ended = False

    def play(self):
        with self._lock:
            if self._track is not None:
                if self._pos >= self._track.frames:
                    self._pos = 0
                self._playing = True
                self.ended = False

    def pause(self):
        with self._lock:
            self._playing = False

    def stop(self):
        with self._lock:
            self._playing = False
            self._pos = 0

    def seek(self, seconds):
        with self._lock:
            if self._track is not None:
                f = int(seconds * self.sr)
                self._pos = max(0, min(self._track.frames - 1, f))

    @property
    def track(self):
        return self._track

    @property
    def is_playing(self):
        return self._playing

    # --- a lényeg: mi szól MOST? ------------------------------------------
    def heard(self, lead=0.0):
        """(track, minta_index, szól-e) – ami `lead` mp múlva hallható lesz.

        A `lead` a képernyő saját késését (kb. 1 képkocka) ellensúlyozza, és
        a kézi finomhangolás is ezen keresztül megy. Mivel a szám előre
        dekódolva van, a jövőbe is ránézhetünk: ilyenkor a legutolsó blokktól
        továbbszámolunk.
        """
        now = self.stream.time + lead
        with self._lock:
            hist = list(self._hist)
            fallback = (self._track, float(self._pos), False)
        for i in range(len(hist) - 1, -1, -1):
            dac, start, n, track = hist[i]
            if dac <= now:
                if n == 0:
                    return track, float(start), False
                ahead = (now - dac) * self.sr
                if i < len(hist) - 1:
                    ahead = min(float(n), ahead)    # régebbi blokk: utána szünet/ugrás jött
                return track, min(start + ahead, track.frames - 1.0), True
        if hist:
            _, start, _, track = hist[0]
            return track, float(start), False
        return fallback
