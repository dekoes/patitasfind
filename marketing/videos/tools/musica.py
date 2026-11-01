"""Música original sintetizada para los videos de GuauWoow (sin muestras de terceros: libre de derechos).
Uso: python musica.py adopcion|perdido|instagram  -> ../audio/musica-<video>.wav (48 kHz, estéreo; 60 s, o 30 s para instagram)"""
import sys

import numpy as np

from audio_util import SR, escribir

DUR = 60.0
N = int(SR * DUR)


def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def tiempo(seg):
    return np.arange(int(SR * seg)) / SR


# ------------------------------------------------------------------ instrumentos
def pluck(f, dur=1.6, brillo=0.8, caida=1.4, semilla=0):
    """Cuerda pulsada (ukulele/guitarra) aditiva: armónicos agudos se apagan antes."""
    t = tiempo(dur)
    y = np.zeros_like(t)
    for k in range(1, 16):
        fk = f * k * (1 + 0.0003 * k * k)
        if fk > 15000:
            break
        amp = (1 / k ** 1.15) * (1 if k == 1 else brillo)
        y += amp * np.sin(2 * np.pi * fk * t + 0.37 * k) * np.exp(-t * caida * (1 + 0.55 * (k - 1)))
    rnd = np.random.RandomState(semilla + int(f))
    y += rnd.randn(len(t)) * np.exp(-t * 90) * 0.04
    y *= np.minimum(1, t / 0.003)
    return y * 0.32


def glock(f, dur=2.2):
    t = tiempo(dur)
    parciales = [(1, 1.0, 1.4), (2.76, 0.32, 4.0), (5.40, 0.14, 7.5), (8.93, 0.06, 12.0)]
    y = sum(a * np.sin(2 * np.pi * f * r * t) * np.exp(-t * d) for r, a, d in parciales)
    y *= np.minimum(1, t / 0.0015)
    return y * 0.28


def pad(notas, dur, ataque=0.5, relajo=0.8, brillo=4.0):
    t = tiempo(dur + relajo)
    env = np.minimum(1, t / ataque) * np.clip((dur + relajo - t) / relajo, 0, 1)
    izq = np.zeros_like(t)
    der = np.zeros_like(t)
    for m in notas:
        for det, canal in ((-7, 0), (6, 1), (0, 2)):
            f = hz(m) * 2 ** (det / 1200)
            v = np.zeros_like(t)
            for k in range(1, 10):
                v += np.sin(2 * np.pi * f * k * t + k) / k * np.exp(-k / brillo)
            if canal == 0:
                izq += v
            elif canal == 1:
                der += v
            else:
                izq += v * 0.5
                der += v * 0.5
    return np.stack([izq * env, der * env], axis=1) * 0.035


def bajo(f, dur):
    t = tiempo(dur + 0.08)
    y = np.sin(2 * np.pi * f * t) + 0.35 * np.sin(4 * np.pi * f * t) + 0.12 * np.sin(6 * np.pi * f * t)
    env = np.minimum(1, t / 0.006) * (0.55 + 0.45 * np.exp(-t * 6))
    env *= np.clip((dur + 0.08 - t) / 0.08, 0, 1)
    return np.tanh(y * env * 1.3) * 0.30


def ruido(n, semilla):
    return np.random.RandomState(semilla).randn(n)


def pasabanda(x, lo, hi):
    X = np.fft.rfft(x)
    fr = np.fft.rfftfreq(len(x), 1 / SR)
    m = 1 / (1 + (lo / np.maximum(fr, 1)) ** 4) / (1 + (fr / hi) ** 4)
    return np.fft.irfft(X * m, len(x))


def bombo(v=1.0):
    t = tiempo(0.45)
    f = 46 + 120 * np.exp(-t * 32)
    y = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 8.5)
    y += ruido(len(t), 1) * np.exp(-t * 380) * 0.18
    return np.tanh(y * 1.4) * 0.55 * v


def palmas(v=1.0, semilla=3):
    t = tiempo(0.32)
    n = pasabanda(ruido(len(t), semilla), 900, 4200)
    env = np.zeros_like(t)
    for d in (0.0, 0.011, 0.022):
        env += np.where(t >= d, np.exp(-(t - d) * 180), 0)
    env += np.where(t >= 0.022, np.exp(-(t - 0.022) * 22) * 0.35, 0)
    return n * env / np.abs(n).max() * 0.32 * v


def platillito(v=1.0, abierto=False, semilla=5):
    t = tiempo(0.35 if abierto else 0.09)
    n = pasabanda(ruido(len(t), semilla), 6500, 15000)
    return n / np.abs(n).max() * np.exp(-t * (14 if abierto else 75)) * 0.13 * v


def shaker(v=1.0, semilla=7):
    t = tiempo(0.12)
    n = pasabanda(ruido(len(t), semilla), 3500, 11000)
    env = np.minimum(1, t / 0.012) * np.exp(-t * 38)
    return n / np.abs(n).max() * env * 0.09 * v


def chasquido(v=1.0):
    t = tiempo(0.12)
    n = pasabanda(ruido(len(t), 11), 1500, 6000)
    return (n / np.abs(n).max() * np.exp(-t * 110) + 0.3 * np.sin(2 * np.pi * 2200 * t) * np.exp(-t * 160)) * 0.22 * v


def subida(dur=2.0):
    """Barrido de ruido que sube (antes de los cambios grandes)."""
    t = tiempo(dur)
    n = pasabanda(ruido(len(t), 13), 2000, 12000)
    env = (t / dur) ** 2.4
    tono = np.sin(2 * np.pi * np.cumsum(300 + 1500 * (t / dur) ** 2) / SR) * 0.15
    return (n / np.abs(n).max() * 0.6 + tono) * env * 0.16


def platillo_inverso(dur=1.4):
    t = tiempo(dur)
    n = pasabanda(ruido(len(t), 17), 3000, 14000)
    return n / np.abs(n).max() * (t / dur) ** 3 * 0.20


# ------------------------------------------------------------------ mezcla
class Pista:
    def __init__(self):
        self.seco = np.zeros((N, 2))
        self.humedo = np.zeros((N, 2))

    def poner(self, sig, t, ganancia=1.0, pan=0.0, rev=0.2):
        if sig.ndim == 1:
            ang = (pan + 1) * np.pi / 4
            sig = np.stack([sig * np.cos(ang), sig * np.sin(ang)], axis=1)
        i = int(t * SR)
        if i >= N:
            return
        j = min(N, i + len(sig))
        self.seco[i:j] += sig[: j - i] * ganancia
        self.humedo[i:j] += sig[: j - i] * ganancia * rev

    def reverb(self, dur=1.9, oscuro=0.9997):
        t = tiempo(dur)
        rnd = np.random.RandomState(21)
        ir = rnd.randn(len(t), 2) * np.exp(-t / 0.42)[:, None]
        # cola más oscura: se recorta el extremo agudo
        ir = np.stack([pasabanda(ir[:, 0], 120, 6000), pasabanda(ir[:, 1], 120, 6000)], axis=1)
        ir /= np.sqrt((ir ** 2).sum(axis=0))
        out = np.zeros_like(self.humedo)
        L = N + len(ir)
        nfft = 1 << (L - 1).bit_length()
        for c in range(2):
            out[:, c] = np.fft.irfft(np.fft.rfft(self.humedo[:, c], nfft) * np.fft.rfft(ir[:, c], nfft), nfft)[:N]
        return self.seco + out * 0.9


# ------------------------------------------------------------------ armonía
ACORDES = {
    'C': [60, 64, 67], 'G': [59, 62, 67], 'Am': [57, 60, 64], 'F': [57, 60, 65], 'Em': [59, 64, 67],
    'Dm': [57, 62, 65], 'E': [56, 59, 64], 'Gsus': [60, 62, 67],
}
RAIZ = {'C': 36, 'G': 31, 'Am': 33, 'F': 29, 'Em': 28, 'Dm': 26, 'E': 28, 'Gsus': 31}


def melodia(acorde, compas, semilla, plantilla):
    """Frase de glockenspiel con notas del acorde (una octava arriba) y movimiento cercano."""
    rnd = np.random.RandomState(semilla + compas * 7)
    tonos = sorted({n + 12 + o for n in ACORDES[acorde] for o in (0, 12)})
    idx = len(tonos) // 2
    notas = []
    for b in plantilla:
        idx = int(np.clip(idx + rnd.choice([-2, -1, 1, 1, 2]), 0, len(tonos) - 1))
        notas.append((b, tonos[idx]))
    return notas


def cancion_adopcion():
    bpm = 104
    beat = 60 / bpm
    compas = beat * 4
    p = Pista()
    prog = ['C', 'G', 'Am', 'F'] * 4 + ['F', 'G', 'Em', 'Am', 'F', 'G', 'C', 'C', 'F', 'G', 'C']
    def seccion(t):
        if t < 4.4: return 'intro'
        if t < 11.0: return 'verso'
        if t < 25.8: return 'groove'
        if t < 33.0: return 'match'
        if t < 40.0: return 'quiebre'
        if t < 54.2: return 'coro'
        return 'final'
    ncomp = int(np.ceil(DUR / compas))
    for c in range(ncomp):
        t0 = c * compas
        if t0 >= DUR - 0.05:
            break
        sec = seccion(t0)
        ac = prog[c % len(prog)] if sec != 'final' else ['F', 'G', 'C', 'C'][min(3, c - int(54.2 // compas))]
        notas = ACORDES[ac]
        # pad
        p.poner(pad(notas, compas * 0.98, ataque=0.6 if sec in ('intro', 'quiebre') else 0.25), t0, 1.0 if sec != 'coro' else 1.3, rev=0.35)
        # rasgueo de ukulele (abajo/arriba)
        if sec != 'intro':
            patron = [(0, 'D', 1.0), (1, 'D', 0.7), (1.5, 'U', 0.55), (2.5, 'U', 0.6), (3, 'D', 0.75), (3.5, 'U', 0.5)]
            if sec == 'quiebre':
                patron = [(0, 'D', 0.9), (2, 'D', 0.7)]
            for b, d, v in patron:
                orden = notas + [notas[0] + 12] if d == 'D' else ([notas[0] + 12] + notas[::-1])
                for k, m in enumerate(orden):
                    p.poner(pluck(hz(m), 1.2, brillo=0.75, caida=2.6 if sec != 'quiebre' else 1.2, semilla=c * 10 + k),
                            t0 + b * beat + k * 0.011, 0.55 * v, pan=-0.25 + 0.15 * k, rev=0.18)
        # bajo
        if sec in ('groove', 'match', 'coro', 'final', 'verso'):
            r = hz(RAIZ[ac] + (12 if sec == 'verso' else 0))
            for b, l in ((0, 1.4), (1.5, 0.45), (2, 1.0), (3.5, 0.45)):
                p.poner(bajo(r if b != 3.5 else r * 1.5, l * beat), t0 + b * beat, 0.9 if sec != 'verso' else 0.6, rev=0.05)
        # batería
        if sec in ('verso', 'groove', 'match', 'coro'):
            for i in range(8):
                p.poner(shaker(0.6 + 0.4 * (i % 2)), t0 + i * beat / 2, 1.0, pan=0.35, rev=0.1)
        if sec in ('groove', 'match', 'coro', 'final'):
            for b in ((0, 2) if sec != 'coro' else (0, 1.5, 2)):
                p.poner(bombo(0.85), t0 + b * beat, 1.0, rev=0.05)
            for b in (1, 3):
                p.poner(palmas(0.9 if sec != 'groove' else 0.7, semilla=c), t0 + b * beat, 1.0, pan=0.1, rev=0.3)
            for i in range(4):
                p.poner(platillito(0.8), t0 + (i + 0.5) * beat, 1.0, pan=-0.3, rev=0.1)
        if sec == 'quiebre':
            for b in (1, 3):
                p.poner(chasquido(), t0 + b * beat, 1.0, pan=0.2, rev=0.35)
        # glockenspiel
        if sec in ('intro', 'match', 'coro', 'final') or (sec == 'groove' and c % 2 == 1):
            plantilla = [0, 0.5, 1, 2, 2.5, 3] if sec != 'intro' else [0, 1, 1.5, 2, 3]
            for b, m in melodia(ac, c, 3, plantilla):
                p.poner(glock(hz(m)), t0 + b * beat, 0.8 if sec != 'groove' else 0.5, pan=0.3, rev=0.45)
    # transiciones musicales
    for tt in (11.0, 26.2, 40.2):
        p.poner(subida(1.6), tt - 1.6, 1.0, rev=0.3)
    for tt in (26.2, 40.2, 54.4):
        p.poner(platillito(1.6, abierto=True), tt, 1.0, rev=0.4)
    # acorde final que se queda sonando
    tf = 57.7
    for k, m in enumerate(ACORDES['C'] + [72, 76, 79]):
        p.poner(pluck(hz(m), 2.4, brillo=0.7, caida=0.9, semilla=99 + k), tf + k * 0.03, 0.5, pan=-0.3 + 0.12 * k, rev=0.5)
        p.poner(glock(hz(m + 12), 2.3), tf + 0.2 + k * 0.09, 0.35, pan=0.3, rev=0.6)
    return p.reverb()


def cancion_perdido():
    bpm = 90
    beat = 60 / bpm
    compas = beat * 4
    p = Pista()
    def seccion(t):
        if t < 4.4: return 'tension'
        if t < 11.0: return 'calma'
        if t < 28.0: return 'busqueda'
        if t < 44.0: return 'esperanza'
        if t < 52.0: return 'reencuentro'
        return 'final'
    progs = {
        'tension': ['Am', 'Am'], 'calma': ['Am', 'F', 'Am', 'F'], 'busqueda': ['Am', 'F', 'C', 'G'],
        'esperanza': ['C', 'G', 'Am', 'F'], 'reencuentro': ['F', 'G', 'C', 'Am'], 'final': ['F', 'G', 'C', 'C'],
    }
    ncomp = int(np.ceil(DUR / compas))
    for c in range(ncomp):
        t0 = c * compas
        if t0 >= DUR - 0.05:
            break
        sec = seccion(t0)
        pr = progs[sec]
        ac = pr[c % len(pr)]
        if sec == 'final' and t0 >= 56.5:
            ac = 'C'
        notas = ACORDES[ac]
        oscuro = sec in ('tension', 'calma')
        p.poner(pad([n - 12 for n in notas] if oscuro else notas, compas * 0.98, ataque=0.8 if oscuro else 0.3, brillo=2.5 if oscuro else 4.5),
                t0, 1.4 if oscuro else (1.5 if sec == 'reencuentro' else 1.0), rev=0.4)
        if sec == 'tension':
            # pulso como latido + tic-tac
            for b in (0, 2):
                p.poner(bombo(0.7), t0 + b * beat, 1.0, rev=0.1)
                p.poner(bombo(0.45), t0 + b * beat + 0.24, 1.0, rev=0.1)
            for i in range(8):
                p.poner(platillito(0.5), t0 + i * beat / 2, 1.0, pan=0.4 if i % 2 else -0.4, rev=0.2)
        # arpegios
        if sec in ('calma', 'busqueda', 'esperanza', 'reencuentro', 'final'):
            tonos = notas + [n + 12 for n in notas]
            paso = 0.5 if sec == 'calma' else 0.25
            for i in range(int(4 / paso)):
                m = tonos[[0, 1, 2, 3, 2, 1][i % 6] if sec != 'calma' else i % len(tonos)]
                p.poner(pluck(hz(m), 1.0, brillo=0.9, caida=3.0 if paso < 0.5 else 1.6, semilla=c * 31 + i),
                        t0 + i * paso * beat, 0.42 if sec != 'calma' else 0.5, pan=-0.4 + 0.8 * ((i % 4) / 3), rev=0.25)
        if sec in ('busqueda', 'esperanza', 'reencuentro', 'final'):
            r = hz(RAIZ[ac])
            for b, l in ((0, 1.5), (2, 1.4)) if sec == 'busqueda' else ((0, 1.4), (1.5, 0.45), (2, 1.0), (3, 0.9)):
                p.poner(bajo(r, l * beat), t0 + b * beat, 0.85, rev=0.05)
            for i in range(16 if sec == 'busqueda' else 8):
                p.poner(platillito(0.55 + 0.3 * (i % 2)), t0 + i * beat / (4 if sec == 'busqueda' else 2), 1.0, pan=-0.3, rev=0.1)
            p.poner(bombo(0.85), t0, 1.0, rev=0.05)
            p.poner(bombo(0.75), t0 + 2 * beat, 1.0, rev=0.05)
            if sec != 'busqueda' or t0 > 19.0:
                for b in (1, 3):
                    p.poner(palmas(0.8, semilla=c), t0 + b * beat, 1.0, pan=0.1, rev=0.3)
        if sec in ('esperanza', 'reencuentro', 'final') and c % 2 == 0 or sec == 'reencuentro':
            for b, m in melodia(ac, c, 5, [0, 1, 1.5, 2, 3]):
                p.poner(glock(hz(m)), t0 + b * beat, 0.7, pan=0.3, rev=0.5)
    for tt in (4.4, 11.2, 28.2, 44.2):
        p.poner(subida(1.8), tt - 1.8, 1.0 if tt != 44.2 else 1.3, rev=0.3)
    p.poner(platillo_inverso(1.6), 44.2 - 1.6, 1.2, rev=0.3)
    for tt in (28.2, 44.2, 52.2):
        p.poner(platillito(1.8, abierto=True), tt, 1.0, rev=0.4)
    tf = 57.4
    for k, m in enumerate(ACORDES['C'] + [72, 76, 79]):
        p.poner(pluck(hz(m), 2.6, brillo=0.7, caida=0.8, semilla=77 + k), tf + k * 0.035, 0.5, pan=-0.3 + 0.12 * k, rev=0.5)
        p.poner(glock(hz(m + 12), 2.5), tf + 0.25 + k * 0.1, 0.35, pan=0.3, rev=0.6)
    return p.reverb()


def cancion_instagram():
    """30 s a 100 BPM (compás de 2.4 s): los cortes del video caen en la rejilla de 0.6 s.
    Arco armónico: tensión en La menor -> búsqueda -> llegada a Do mayor en el reencuentro -> groove de ukulele (adopción) -> cierre."""
    bpm = 100
    beat = 60 / bpm
    compas = beat * 4
    p = Pista()

    def seccion(t):
        if t < 2.4: return 'tension'
        if t < 14.4: return 'busqueda'
        if t < 17.4: return 'reencuentro'
        if t < 26.4: return 'adopcion'
        if t < 28.8: return 'final'
        return 'cierre'

    por_compas = ['Am', 'Am', 'F', 'C', 'G', ('F', 'G'), 'C', 'C', 'G', 'Am', 'F', ('F', 'G'), 'C']

    def acorde(t):
        c = min(int(t // compas + 1e-9), len(por_compas) - 1)
        a = por_compas[c]
        if isinstance(a, tuple):
            a = a[0] if t - c * compas < 2 * beat - 1e-6 else a[1]
        return a

    nb = int(round(DUR / beat))
    # pads: un tramo por cada acorde/sección continuos
    tramos = []
    for b in range(nb):
        t = b * beat
        clave = (acorde(t), seccion(t))
        if tramos and tramos[-1][0] == clave:
            tramos[-1][2] += beat
        else:
            tramos.append([clave, t, beat])
    for (ac, sec), t0, d in tramos:
        notas = ACORDES[ac]
        if sec == 'tension':
            p.poner(pad([n - 12 for n in notas], d, ataque=0.15, brillo=2.5), t0, 1.5, rev=0.4)
        elif sec == 'cierre':
            p.poner(pad(notas + [notas[0] + 12], d, ataque=0.05, relajo=0.6, brillo=4.5), t0, 1.3, rev=0.5)
        else:
            p.poner(pad(notas, d * 0.98, ataque=0.25 if sec != 'reencuentro' else 0.12, brillo=4.5), t0,
                    {'busqueda': 0.9, 'reencuentro': 1.6, 'adopcion': 1.0, 'final': 1.3}[sec], rev=0.35)

    arp = 0
    for b in range(nb):
        t = b * beat
        sec, ac = seccion(t), acorde(t)
        notas = ACORDES[ac]
        bb = b % 4
        raiz = hz(RAIZ[ac])
        if sec == 'tension':
            if bb in (0, 2):
                p.poner(bombo(0.75), t, 1.0, rev=0.1)
                p.poner(bombo(0.45), t + 0.22, 1.0, rev=0.1)
            for i in range(2):
                p.poner(platillito(0.5), t + i * beat / 2, 1.0, pan=0.4 if i else -0.4, rev=0.2)
        elif sec == 'busqueda':
            tonos = notas + [n + 12 for n in notas]
            for i in range(4):
                m = tonos[[0, 1, 2, 3, 4, 3, 2, 1][arp % 8]]
                arp += 1
                p.poner(pluck(hz(m), 0.9, brillo=0.9, caida=3.2, semilla=b * 4 + i), t + i * beat / 4, 0.4, pan=-0.4 + 0.8 * (i / 3), rev=0.22)
                p.poner(platillito(0.5 + 0.35 * (i % 2)), t + i * beat / 4, 1.0, pan=-0.3, rev=0.1)
            for off, l, f in {0: [(0, 1.4, 1)], 1: [(0.5, 0.45, 1)], 2: [(0, 1.0, 1)], 3: [(0, 0.9, 1.5)]}[bb]:
                p.poner(bajo(raiz * f, l * beat), t + off * beat, 0.85, rev=0.05)
            if bb in (0, 2):
                p.poner(bombo(0.85 if bb == 0 else 0.75), t, 1.0, rev=0.05)
            if bb in (1, 3) and t >= 4.8:
                p.poner(palmas(0.8, semilla=b), t, 1.0, pan=0.1, rev=0.3)
        elif sec == 'reencuentro':
            tonos = notas + [n + 12 for n in notas]
            for i in range(2):
                p.poner(pluck(hz(tonos[(b * 2 + i) % 6]), 1.4, brillo=0.8, caida=1.6, semilla=b * 2 + i), t + i * beat / 2, 0.42, pan=-0.3 + 0.6 * i, rev=0.35)
            if bb == 0:
                p.poner(bajo(raiz, 3.6 * beat), t, 0.8, rev=0.1)
                p.poner(bombo(0.7), t, 1.0, rev=0.1)
            if bb == 2:
                p.poner(bombo(0.5), t, 1.0, rev=0.1)
        elif sec in ('adopcion', 'final'):
            golpes = {0: [(0, 'D', 1.0)], 1: [(0, 'D', 0.7), (0.5, 'U', 0.55)], 2: [(0.5, 'U', 0.6)], 3: [(0, 'D', 0.75), (0.5, 'U', 0.5)]}[bb]
            if sec == 'final':
                golpes = {0: [(0, 'D', 1.0)], 1: [(0.5, 'U', 0.5)], 2: [(0, 'D', 0.9)], 3: [(0, 'D', 0.6), (0.5, 'U', 0.5)]}[bb]
            for off, d, v in golpes:
                orden = notas + [notas[0] + 12] if d == 'D' else ([notas[0] + 12] + notas[::-1])
                for k, m in enumerate(orden):
                    p.poner(pluck(hz(m), 1.2, brillo=0.75, caida=2.6, semilla=b * 10 + k), t + off * beat + k * 0.011, 0.55 * v, pan=-0.25 + 0.15 * k, rev=0.18)
            for off, l, f in {0: [(0, 1.4, 1)], 1: [(0.5, 0.45, 1)], 2: [(0, 1.0, 1)], 3: [(0.5, 0.45, 1.5)]}[bb]:
                p.poner(bajo(raiz * f, l * beat), t + off * beat, 0.9, rev=0.05)
            if bb in (0, 2):
                p.poner(bombo(0.85), t, 1.0, rev=0.05)
            if bb == 1:
                p.poner(bombo(0.6), t + beat / 2, 1.0, rev=0.05)
            if bb in (1, 3):
                p.poner(palmas(0.85, semilla=b), t, 1.0, pan=0.1, rev=0.3)
            for i in range(2):
                p.poner(shaker(0.6 + 0.4 * i), t + i * beat / 2, 1.0, pan=0.35, rev=0.1)
                p.poner(platillito(0.7), t + (i + 0.5) * beat / 2, 1.0, pan=-0.3, rev=0.1)

    # glockenspiel: reencuentro, compases impares de la adopción y el final
    for c in range(int(np.ceil(DUR / compas))):
        t0 = c * compas
        sec = seccion(t0)
        if sec in ('reencuentro', 'final') or (sec == 'adopcion' and c % 2 == 1):
            for b, m in melodia(acorde(t0), c, 11, [0, 0.5, 1, 2, 2.5, 3]):
                if t0 + b * beat < 28.8:
                    p.poner(glock(hz(m)), t0 + b * beat, 0.75, pan=0.3, rev=0.45)
    # transiciones musicales
    p.poner(subida(1.0), 2.4 - 1.0, 0.8, rev=0.3)
    p.poner(subida(1.6), 14.4 - 1.6, 1.2, rev=0.3)
    p.poner(platillo_inverso(1.4), 14.4 - 1.4, 1.1, rev=0.3)
    p.poner(subida(1.2), 17.4 - 1.2, 1.0, rev=0.3)
    p.poner(subida(1.4), 26.4 - 1.4, 1.0, rev=0.3)
    for tt in (2.4, 14.4, 17.4, 26.4):
        p.poner(platillito(1.7, abierto=True), tt, 1.0, rev=0.4)
    # acorde final que se queda sonando
    tf = 28.8
    p.poner(bombo(0.9), tf, 1.0, rev=0.2)
    for k, m in enumerate(ACORDES['C'] + [72, 76, 79]):
        p.poner(pluck(hz(m), 1.8, brillo=0.7, caida=1.0, semilla=55 + k), tf + k * 0.03, 0.55, pan=-0.3 + 0.12 * k, rev=0.5)
        p.poner(glock(hz(m + 12), 1.6), tf + 0.12 + k * 0.07, 0.35, pan=0.3, rev=0.6)
    return p.reverb()


if __name__ == "__main__":
    video = sys.argv[1]
    if video == "instagram":
        DUR = 30.0
        N = int(SR * DUR)
    y = {"adopcion": cancion_adopcion, "perdido": cancion_perdido, "instagram": cancion_instagram}[video]()
    # desvanecido final y nivel
    f = int(SR * 0.8)
    y[-f:] *= np.linspace(1, 0, f)[:, None] ** 1.5
    y = np.tanh(y * 1.1) / np.tanh(1.1)
    y *= 0.5 / (np.sqrt((y ** 2).mean()) * 4 + 1e-9)
    y = np.clip(y, -0.98, 0.98)
    escribir(f"../audio/musica-{video}.wav", y)
    print(video, "pico %.2f" % np.abs(y).max(), "rms %.3f" % np.sqrt((y ** 2).mean()))
