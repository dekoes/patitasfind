"""Utilidades de audio (numpy) para el diseño sonoro de los videos: leer/escribir WAV, envolventes y detección de golpes."""
import wave

import numpy as np

SR = 48000


def leer(ruta):
    with wave.open(ruta, "rb") as w:
        n, ch, sw = w.getnframes(), w.getnchannels(), w.getsampwidth()
        datos = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
    return datos.reshape(-1, ch) if ch > 1 else np.stack([datos, datos], axis=1)


def escribir(ruta, x):
    x = np.clip(x, -1, 1)
    with wave.open(ruta, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((x * 32767).astype(np.int16).tobytes())


def envolvente(x, ms=10):
    mono = np.abs(x).mean(axis=1)
    n = int(SR * ms / 1000)
    k = len(mono) // n
    return mono[: k * n].reshape(k, n).max(axis=1), n


def segmentos(x, umbral_db=-26, min_ms=90, separacion_ms=120):
    """Devuelve [(inicio, fin, pico_db)] de golpes separados por silencio (relativo al pico del archivo)."""
    env, n = envolvente(x)
    pico = env.max() + 1e-9
    db = 20 * np.log10(env / pico + 1e-9)
    activo = db > umbral_db
    segs, i = [], 0
    while i < len(activo):
        if activo[i]:
            j = i
            silencio = 0
            while j < len(activo) and silencio < separacion_ms / 10:
                silencio = silencio + 1 if not activo[j] else 0
                j += 1
            fin = j - int(silencio)
            if (fin - i) * 10 >= min_ms:
                segs.append((i * n, fin * n, float(db[i:fin].max())))
            i = j
        else:
            i += 1
    return segs


def recortar(x, ini, fin, pre_ms=8, fade_ms=40):
    a = max(0, ini - int(SR * pre_ms / 1000))
    y = x[a:fin].copy()
    f = min(len(y), int(SR * fade_ms / 1000))
    if f > 0:
        y[-f:] *= np.linspace(1, 0, f)[:, None]
    return y


def normalizar(x, pico=0.89):
    m = np.abs(x).max()
    return x * (pico / m) if m > 0 else x
