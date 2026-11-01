"""Diseño sonoro de los videos: convierte las marcas del motor (build/cues-<video>.json) en efectos reales CC0
(audio/norm, BigSoundBank) y sintetizados, los mezcla con la música y monta el audio en el video.
Uso: python sonido.py adopcion|perdido|instagram [--montar]
  --montar  además pone la mezcla final en el mp4 de out/ (video copiado tal cual, audio AAC 192 kbps)."""
import json
import os
import subprocess
import sys

import numpy as np

from audio_util import SR, escribir, leer, segmentos

BASE = os.path.join(os.path.dirname(__file__), "..")
DURACION = {"instagram": 30}  # segundos; los demás videos duran 60
SALIDA = {"instagram": "guauwoow-instagram-30s"}
SEMILLA = {"adopcion": 42, "instagram": 23}
N = SR * 60
_cache = {}


def norm(nombre):
    if nombre not in _cache:
        _cache[nombre] = leer(os.path.join(BASE, "audio", "norm", nombre + ".wav"))
    return _cache[nombre]


def tramo(nombre, ini, fin, fade=0.03):
    x = norm(nombre)[int(ini * SR): int(fin * SR)].copy()
    f = min(len(x), int(fade * SR))
    if f:
        x[-f:] *= np.linspace(1, 0, f)[:, None]
        x[: min(len(x), 64)] *= np.linspace(0, 1, min(len(x), 64))[:, None]
    return x


def golpes(nombre, umbral=-30, min_ms=20, sep_ms=80, maxlen=0.35, cola=0.06):
    """Lista de recortes individuales (un golpe cada uno)."""
    x = norm(nombre)
    out = []
    for s, e, _ in segmentos(x, umbral, min_ms, sep_ms):
        fin = min(e + int(cola * SR), s + int(maxlen * SR))
        y = x[max(0, s - 96): fin].copy()
        f = min(len(y), int(0.03 * SR))
        y[-f:] *= np.linspace(1, 0, f)[:, None]
        out.append(y)
    return out


def tono(x, semitonos):
    if abs(semitonos) < 1e-3:
        return x
    r = 2 ** (semitonos / 12)
    idx = np.arange(0, len(x) - 1, r)
    return np.stack([np.interp(idx, np.arange(len(x)), x[:, c]) for c in range(2)], axis=1)


def pico(x):
    """Segundos desde el inicio hasta el punto más fuerte (para alinear barridos con la animación)."""
    return int(np.argmax(np.abs(x).mean(axis=1))) / SR


def t_(seg):
    return np.arange(int(SR * seg)) / SR


def estereo(m):
    return np.stack([m, m], axis=1)


# ------------------------------------------------------------------ sonidos sintetizados
def golpe_grave(f0=70, dur=0.35, v=1.0):
    t = t_(dur)
    f = f0 * (1 + 1.6 * np.exp(-t * 40))
    y = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 11)
    y += np.random.RandomState(4).randn(len(t)) * np.exp(-t * 300) * 0.25
    return estereo(np.tanh(y * 1.6) * 0.6 * v)


def boom(v=1.0):
    t = t_(1.1)
    f = 34 + 40 * np.exp(-t * 6)
    y = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 3.2) * np.minimum(1, t / 0.01)
    return estereo(np.tanh(y * 1.8) * 0.55 * v)


def glissando(f0, f1, dur, v=0.4):
    t = t_(dur)
    f = f0 * (f1 / f0) ** (t / dur)
    y = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.sin(np.pi * t / dur) ** 0.6
    return estereo(y * v)


def burbuja(f0=900, f1=260, dur=0.09, v=0.5):
    t = t_(dur)
    f = f0 * (f1 / f0) ** (t / dur)
    return estereo(np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 30) * v)


def blip(f, dur=0.05, v=0.3):
    t = t_(dur)
    return estereo(np.sin(2 * np.pi * f * t) * np.exp(-t * 60) * np.minimum(1, t / 0.002) * v)


def campanita(f, dur=1.4, v=0.3):
    t = t_(dur)
    y = sum(a * np.sin(2 * np.pi * f * r * t) * np.exp(-t * d) for r, a, d in ((1, 1, 2.2), (2.76, 0.3, 5), (5.4, 0.12, 9)))
    return estereo(y * np.minimum(1, t / 0.002) * v)


def pisada(v=0.3, semilla=0):
    t = t_(0.06)
    n = np.random.RandomState(semilla).randn(len(t))
    k = np.ones(40) / 40
    n = np.convolve(n, k, "same")
    return estereo(n / np.abs(n).max() * np.exp(-t * 70) * v)


# ------------------------------------------------------------------ biblioteca
def biblioteca():
    B = {}
    B["ladridos"] = [tramo("0612-small-dog-barking", a, b + 0.05) for a, b in ((9.30, 9.49), (13.26, 13.46), (18.87, 19.06), (22.77, 22.97))]
    B["ladrido_doble"] = [tramo("0612-small-dog-barking", 0.14, 0.78), tramo("0612-small-dog-barking", 16.48, 17.16)]
    B["yip"] = tramo("0682-barking-of-a-spitz", 0.68, 1.15)
    B["aullido"] = tramo("2450-dog-singing-1", 0.08, 1.75, fade=0.25)
    B["jadeo"] = tramo("1547-dogs-breathing", 0.0, 1.8, fade=0.5)
    B["whoosh_cortos"] = [tramo(n, 0.0, d) for n, d in (("1795-whoosh-3", 0.91), ("1797-whoosh-5", 0.54), ("1798-whoosh-10", 0.46), ("1799-whoosh-6", 0.52), ("1800-whoosh-7", 0.89))]
    B["whoosh_largos"] = [tramo("1796-whoosh-4", 0.0, 1.04), tramo("0572-whoosh-1", 0.0, 1.05), tramo("0573-whoosh-2", 0.0, 1.25)]
    B["burbujas"] = golpes("1074-bubbles-burst", -30, 15, 80, 0.12)[:10]
    B["corcho"] = tramo("0211-champagne-cork", 0.0, 0.6)
    B["espantasuegras"] = tramo("1553-party-horn-1", 0.04, 0.9)
    B["boings"] = [tramo(n, 0.08, 0.9, fade=0.2) for n in ("2277-boing-cartoon-1", "2278-boing-cartoon-2", "2280-boing-cartoon-4")]
    B["pagina"] = tramo("0362-page-turn", 0.0, 1.7, fade=0.2)
    B["teclas"] = [g for g in golpes("1731-quick-imac-keyboard", -28, 10, 40, 0.09) if len(g) < 0.09 * SR][:24]
    B["toque"] = golpes("0447-iphone-touch", -30, 10, 80, 0.12)[:4]
    B["madera"] = golpes("0466-woodblock", -30, 10, 80, 0.25)[:6]
    B["toc"] = golpes("0374-knock-light-door", -30, 20, 60, 0.3)[:3]
    B["marcador"] = tramo("0807-whiteboard-marker", 0.17, 0.82)
    B["lapiz"] = tramo("3233-pencil-2", 2.05, 4.2, fade=0.15)
    B["notif"] = [tramo(f"206{i}-notification-{i - 2}", 0.0, 0.4) for i in (3, 4, 5, 6)]
    B["mensaje_in"] = tramo("1111-message-1", 0.0, 1.5, fade=0.3)
    B["mensaje_largo"] = tramo("1112-message-2", 0.0, 1.6, fade=0.4)
    B["idea"] = [tramo("1398-idea-1", 0.0, 1.6, fade=0.3), tramo("1399-idea-2", 0.0, 1.5, fade=0.3)]
    B["campanitas"] = [tramo(n, 0.0, d, fade=0.4) for n, d in (("2079-chimes-dream-1", 2.29), ("2080-chimes-dream-2", 1.44), ("2087-chimes-butterfly-1", 2.08), ("2088-chimes-butterfly-2", 2.29), ("2089-chimes-butterfly-3", 2.25))]
    B["campana_bici"] = tramo("0275-bell-bike-2", 0.0, 1.2, fade=0.3)
    B["sonar"] = tramo("1416-sonar-1", 0.0, 1.85, fade=0.4)
    B["beso"] = tramo("2196-kiss-1", 0.05, 0.31)
    B["escaner"] = tramo("1414-scanner-fast", 1.27, 7.3, fade=0.2)
    B["bip"] = tramo("1417-beep-cash-register", 0.08, 0.2)
    B["camara"] = tramo("0448-iphone-camera", 0.2, 0.9, fade=0.15)
    B["reloj"] = golpes("0007-clock", -30, 20, 200, 0.25)[:4]
    B["latido"] = tramo("0243-heartbeat-1", 0.0, 0.78, fade=0.1)
    B["gotas"] = golpes("1384-drops-of-water-1", -30, 30, 120, 0.3)[:5]
    B["radio"] = norm("0313-crackling-radio")
    B["chillido"] = [tramo("0879-squeaker-toy-2", 0.08, 0.72), tramo("3333-toy-squeak-3", 0.02, 0.5)]
    B["aplausos"] = tramo("1765-applause-1", 0.0, 3.2, fade=1.2)
    return B


# ------------------------------------------------------------------ marcas -> sonidos
def sonidos_de(c, B, rnd):
    """Devuelve [(señal, desfase_segundos, ganancia)] para una marca. El desfase negativo adelanta (barridos)."""
    k = c["kind"]
    elige = lambda lst: lst[rnd.randint(len(lst))]
    var = lambda a=1.5: rnd.uniform(-a, a)
    if k == "whoosh_in":
        w = tono(elige(B["whoosh_cortos"]), var(2))
        return [(w, -pico(w), 0.42)]
    if k == "swipe":
        w = tono(elige(B["whoosh_cortos"]), 2 + var(1))
        return [(w, -pico(w) + 0.1, 0.45)]
    if k in ("trans_whip", "trans_whipUp"):
        w = elige(B["whoosh_largos"])
        return [(w, -pico(w) + c.get("dur", 0.55) * 0.35, 0.7), (golpe_grave(55, 0.3, 0.5), c.get("dur", 0.55) * 0.6, 0.6)]
    if k == "trans_circle":
        return [(glissando(320, 1100, 0.45, 0.22), 0.0, 1.0), (elige(B["campanitas"][:2]), 0.05, 0.35)]
    if k == "trans_paw":
        return [(elige(B["chillido"]), 0.0, 0.42), (elige(B["whoosh_largos"]), 0.0, 0.45), (burbuja(700, 220, 0.12, 0.6), 0.25, 0.6)]
    if k == "trans_zoom":
        w = tono(elige(B["whoosh_largos"]), 3)
        return [(w, -pico(w) + 0.15, 0.6), (boom(0.6), 0.3, 0.5)]
    if k == "boom":
        w = tono(elige(B["whoosh_cortos"]), -5)
        return [(boom(1.0), 0.05, 0.75), (w, -pico(w) + 0.05, 0.35)]
    if k == "pop":
        return [(tono(elige(B["burbujas"]), var(3) + 2), 0.0, 0.55), (burbuja(rnd.uniform(700, 1100), 250, 0.07, 0.35), 0.0, 0.5)]
    if k == "pop_soft":
        return [(tono(elige(B["burbujas"]), 4 + var(2)), 0.0, 0.3)]
    if k == "pop_big":
        return [(B["corcho"], -0.01, 0.55), (burbuja(500, 160, 0.12, 0.5), 0.0, 0.5)]
    if k == "boing":
        return [(elige(B["boings"]), 0.0, 0.42)]
    if k == "polaroid":
        p = tono(B["pagina"][: int(0.45 * SR)], 4 + var(1.5))
        return [(p, -0.05, 0.22), (tono(elige(B["madera"]), 6), 0.0, 0.12)]
    if k == "drop":
        return [(tono(elige(B["madera"]), var(2) - 2), 0.0, 0.5), (golpe_grave(85, 0.2, 0.6), 0.0, 0.5)]
    if k == "paper":
        return [(B["pagina"], 0.0, 0.6), (golpe_grave(60, 0.3, 0.4), 0.85, 0.5)]
    if k == "marker":
        return [(B["marcador"], 0.0, 0.55)]
    if k == "typing":
        n, cps = c.get("n", 10), c.get("cps", 20)
        return [(tono(elige(B["teclas"]), var(1)), i / cps, 0.32) for i in range(n)]
    if k == "typing_dots":
        return [(blip(1300, 0.04, 0.5), 0.0, 0.25), (blip(1500, 0.04, 0.5), 0.22, 0.22), (blip(1700, 0.04, 0.5), 0.44, 0.2)]
    if k == "msg_out":
        return [(B["notif"][0], 0.0, 0.5)]
    if k == "msg_in":
        return [(B["mensaje_in"], 0.0, 0.45)]
    if k == "notif":
        return [(B["mensaje_largo"], 0.0, 0.5), (B["notif"][2], 0.1, 0.4)]
    if k == "burst":
        return [(B["corcho"], 0.0, 0.6), (B["espantasuegras"], 0.08, 0.5), (B["campanitas"][2], 0.12, 0.45)]
    if k == "stamp":
        return [(golpe_grave(62, 0.4, 1.0), 0.0, 0.85), (tono(elige(B["toc"]), -4), 0.0, 0.7)]
    if k == "pencil":
        d = min(c.get("dur", 1.1) + 0.3, 2.1)
        x = B["lapiz"][: int(d * SR)].copy()
        f = int(0.12 * SR)
        x[-f:] *= np.linspace(1, 0, f)[:, None]
        return [(x, 0.0, 0.5)]
    if k == "swoosh_up":
        w = tono(elige(B["whoosh_cortos"]), 4)
        return [(w, -pico(w) + 0.2, 0.35)]
    if k == "glitch":
        out = []
        r = B["radio"]
        for i in range(7):
            ini = rnd.randint(0, len(r) - int(0.15 * SR))
            seg = r[ini: ini + int(rnd.uniform(0.04, 0.12) * SR)].copy()
            seg *= np.hanning(len(seg))[:, None]
            out.append((seg, i * c.get("dur", 1.6) * 0.09, 0.55 * (1 - i / 9)))
            out.append((blip(rnd.uniform(300, 2400), 0.03, 0.6), i * c.get("dur", 1.6) * 0.09 + 0.02, 0.25))
        return out
    if k == "ring":
        d, n = c.get("dur", 2.0), 14
        out = [(blip(600 * (2.2 ** (i / n)), 0.035, 0.6), d * (1 - (1 - i / n) ** 2), 0.22) for i in range(n)]
        return out + [(B["idea"][0], d, 0.5)]
    if k == "scan":
        d = c.get("dur", 3.2)
        x = B["escaner"][: int(min(d * 1.6, 5.5) * SR)].copy()
        f = int(0.3 * SR)
        x[-f:] *= np.linspace(1, 0, f)[:, None]
        return [(x, 0.0, 0.3)] + [(B["bip"], 0.4 + i * d * 0.3, 0.2) for i in range(4)]
    if k == "magic":
        return [(B["campanitas"][0], 0.0, 0.45), (glissando(400, 1600, 0.6, 0.12), 0.0, 1.0)]
    if k == "fill":
        return [(tono(g, i * 2), i * 0.22, 0.4) for i, g in enumerate(B["gotas"][:4])]
    if k == "shimmer":
        return [(B["campanitas"][4], 0.0, 0.22)]
    if k == "steps":
        return [(pisada(0.5, i), i * c.get("every", 0.18), 0.35) for i in range(c.get("steps", 9))]
    if k in ("twinkle", "sparkle"):
        notas = [2093, 2637, 3136, 2349, 2794]
        return [(campanita(notas[rnd.randint(5)], 1.0, 0.25), i * 0.13 + rnd.uniform(0, 0.05), 0.5) for i in range(4)]
    if k == "sonar":
        per, hasta = c.get("period", 1.6), c.get("until", 6)
        n = max(1, int(hasta / per))
        return [(B["sonar"], i * per, 0.22 * (0.85 ** i)) for i in range(min(n, 5))]
    if k == "camera":
        return [(B["camara"], -0.02, 0.85)]
    if k == "clock":
        hasta = c.get("until", 2.4)
        return [(tono(B["reloj"][i % 2], 2 if i % 2 else 0), i * 0.5, 0.45) for i in range(int(hasta / 0.5))]
    if k == "pin":
        return [(tono(B["gotas"][0], 3), 0.0, 0.5), (burbuja(1200, 500, 0.06, 0.3), 0.0, 0.5)]
    if k == "bell":
        return [(B["campana_bici"], 0.0, 0.5)]
    if k == "shield":
        return [(B["idea"][1], 0.0, 0.45)]
    if k == "kiss":
        return [(B["beso"], 0.0, 0.5)]
    if k == "logo":
        acorde = [1047, 1319, 1568, 2093]
        return [(B["campanitas"][0], 0.0, 0.45), (elige(B["whoosh_cortos"]), -0.1, 0.25)] + [(campanita(f, 1.6, 0.3), 0.35 + i * 0.07, 0.6) for i, f in enumerate(acorde)]
    if k == "button":
        return [(B["toque"][0], 0.0, 0.5), (B["notif"][3], 0.05, 0.35)]
    if k == "heartbeat":
        return [(B["latido"], 0.0, 0.9)]
    if k == "bark":
        return [(tono(elige(B["ladridos"]), var(1)), 0.0, 0.75)]
    if k == "bark_double":
        return [(elige(B["ladrido_doble"]), 0.0, 0.75)]
    if k == "yip":
        return [(tono(B["yip"], 2), 0.0, 0.5)]
    if k == "howl":
        return [(B["aullido"], 0.0, 0.5)]
    if k == "pant":
        return [(B["jadeo"], 0.0, 0.32)]
    if k == "applause":
        return [(B["aplausos"], 0.0, 0.22)]
    return []


def colocar(buf, sig, t, ganancia, pan):
    ang = (np.clip(pan, -1, 1) + 1) * np.pi / 4
    g = np.array([np.cos(ang), np.sin(ang)]) * np.sqrt(2) * ganancia
    i = int(round(t * SR))
    if i < 0:
        sig = sig[-i:]
        i = 0
    j = min(len(buf), i + len(sig))
    if j > i:
        buf[i:j] += sig[: j - i] * g


def suavizar(env, ataque_ms, relajo_ms):
    a = np.exp(-1 / (SR * ataque_ms / 1000))
    r = np.exp(-1 / (SR * relajo_ms / 1000))
    out = np.zeros_like(env)
    v = 0.0
    # se procesa por bloques de 1 ms para que sea rápido
    paso = SR // 1000
    for i in range(0, len(env), paso):
        x = env[i: i + paso].max()
        coef = a ** paso if x > v else r ** paso
        v = coef * v + (1 - coef) * x
        out[i: i + paso] = v
    return out


def main(video, montar=False):
    global N
    N = SR * DURACION.get(video, 60)
    cues = json.load(open(os.path.join(BASE, "build", f"cues-{video}.json")))
    B = biblioteca()
    rnd = np.random.RandomState(SEMILLA.get(video, 7))
    efectos = np.zeros((N, 2))
    for c in cues:
        pan = ((c.get("x", 540) or 540) - 540) / 540 * 0.55
        for sig, desfase, g in sonidos_de(c, B, rnd):
            colocar(efectos, sig, c["t"] + desfase, g, pan)
    musica = leer(os.path.join(BASE, "audio", f"musica-{video}.wav"))[:N]
    musica = np.pad(musica, ((0, N - len(musica)), (0, 0)))
    # la música se hace a un lado (hasta -6 dB) cuando suena un efecto fuerte
    env = suavizar(np.abs(efectos).max(axis=1), 15, 350)
    reduccion = 1 - 0.5 * np.clip(env / 0.5, 0, 1)
    mezcla = musica * 0.72 * reduccion[:, None] + efectos
    f = int(SR * 0.6)
    mezcla[-f:] *= np.linspace(1, 0, f)[:, None]
    lim = np.abs(mezcla).max()
    if lim > 0.98:
        mezcla = np.tanh(mezcla / lim * 1.2) / np.tanh(1.2) * 0.98
    os.makedirs(os.path.join(BASE, "audio", "mezcla"), exist_ok=True)
    escribir(os.path.join(BASE, "audio", "mezcla", f"{video}-efectos.wav"), np.clip(efectos, -0.99, 0.99))
    escribir(os.path.join(BASE, "audio", "mezcla", f"{video}-musica.wav"), musica * 0.72)
    crudo = os.path.join(BASE, "audio", "mezcla", f"{video}-mezcla-cruda.wav")
    escribir(crudo, mezcla)
    final = os.path.join(BASE, "audio", "mezcla", f"{video}-mezcla.wav")
    # volumen estándar de redes: -14 LUFS, pico real -1 dB
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", crudo, "-af", "alimiter=limit=0.70:attack=3:release=60:level=disabled,loudnorm=I=-14:TP=-2.5:LRA=11", "-ar", "48000", final], check=True)
    print(video, len(cues), "marcas; pico efectos %.2f" % np.abs(efectos).max())
    if montar:
        mp4 = os.path.join(BASE, "out", SALIDA.get(video, f"guauwoow-{video}") + ".mp4")
        tmp = mp4[:-4] + "-con-audio.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", mp4, "-i", final, "-map", "0:v:0", "-map", "1:a:0",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", str(DURACION.get(video, 60)),
                        "-movflags", "+faststart", tmp], check=True)
        os.replace(tmp, mp4)
        print("audio montado en", mp4)


if __name__ == "__main__":
    main(sys.argv[1], "--montar" in sys.argv)
