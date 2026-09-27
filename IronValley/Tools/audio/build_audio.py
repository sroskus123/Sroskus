#!/usr/bin/env python3
"""IRON VALLEY — offline audio build (Python 3 + numpy + scipy + soundfile/libsndfile with MP3).

Reads the SHA-256 pinned third-party recordings from Tools/audio/_src/ (fetch_sources.py), cuts, filters,
normalises them to the loudness plan below, synthesises what could not be sourced legally, and writes
  Web/public/assets/audio/<name>.mp3     runtime files (mono or stereo, 44.1 kHz, VBR MP3)
  Web/src/data/audio_bank.json            sound key -> variation files + measured stats + source ids
  Tools/audio/_out/review_*.png           waveform + spectrogram sheets for objective review (not shipped)

Loudness plan (file level, before the runtime mix):
  own rifle shot (close)       true peak  -3 dBFS
  own pistol shot (close)      true peak  -4 dBFS
  distant shot variants        true peak  -6 dBFS   (runtime distance attenuation on top)
  outdoor tails                true peak  -9 dBFS
  impacts / near-miss          true peak  -8 / -6 dBFS
  weapon mechanics             true peak -10 dBFS   (dry fire -14)
  cloth / gear                 true peak -12 .. -16 dBFS
  footsteps                    active RMS -24 dBFS  ("active" = 10 ms windows within 30 dB of the maximum)
  ambience (wind bed, birds)   RMS        -36 dBFS

Everything marked `synth=True` below is procedural synthesis ("procedurální syntéza — prozatímní").
Deterministic: fixed RNG seeds, so a rebuild produces identical PCM (the MP3 encoder is deterministic too).

    python3 Tools/audio/build_audio.py [--src DIR] [--no-png]
"""
import argparse
import json
import os
import sys

import numpy as np
import soundfile as sf
from scipy import signal

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
OUT_AUDIO = os.path.join(ROOT, 'Web', 'public', 'assets', 'audio')
OUT_BANK = os.path.join(ROOT, 'Web', 'src', 'data', 'audio_bank.json')
OUT_REVIEW = os.path.join(HERE, '_out')
SR = 44100

SRC = os.path.join(HERE, '_src')
BANK = {}      # key -> list of file names
FILES = {}     # file name -> stats / provenance
GROUPS = {}    # review group -> list of (file, pcm)


# ----------------------------------------------------------------------------------------- helpers

def load(rel):
    """PCM float64 (n, ch) at SR."""
    x, sr = sf.read(os.path.join(SRC, rel), always_2d=True, dtype='float64')
    if sr != SR:
        g = np.gcd(sr, SR)
        x = signal.resample_poly(x, SR // g, sr // g, axis=0)
    return x


def mono(x):
    return x.mean(axis=1, keepdims=True) if x.shape[1] > 1 else x


def seg(x, t0, t1):
    return x[int(round(t0 * SR)):int(round(t1 * SR))].copy()


def hp(x, fc, order=2):
    sos = signal.butter(order, fc, 'highpass', fs=SR, output='sos')
    return signal.sosfilt(sos, x, axis=0)


def lp(x, fc, order=2):
    sos = signal.butter(order, fc, 'lowpass', fs=SR, output='sos')
    return signal.sosfilt(sos, x, axis=0)


def bp(x, f1, f2, order=2):
    sos = signal.butter(order, [f1, f2], 'bandpass', fs=SR, output='sos')
    return signal.sosfilt(sos, x, axis=0)


def fade(x, fin=0.001, fout=0.05, fout_start=None):
    """Cosine fade-in over fin s; cosine fade-out over the last fout s (or from fout_start to the end)."""
    y = x.copy()
    n = len(y)
    a = int(fin * SR)
    if a > 0:
        y[:a] *= (0.5 - 0.5 * np.cos(np.linspace(0, np.pi, a)))[:, None]
    b0 = int(fout_start * SR) if fout_start is not None else n - int(fout * SR)
    b0 = max(0, min(n, b0))
    m = n - b0
    if m > 0:
        y[b0:] *= (0.5 + 0.5 * np.cos(np.linspace(0, np.pi, m)))[:, None]
    return y


def onset(x, thr_db=-36.0, pre=0.003):
    """Index a little before the first 1 ms window within thr_db of the maximum."""
    m = np.abs(mono(x)[:, 0])
    w = max(1, int(SR * 0.001))
    env = np.sqrt(np.convolve(m ** 2, np.ones(w) / w, 'same'))
    idx = np.argmax(env > env.max() * 10 ** (thr_db / 20))
    return max(0, idx - int(pre * SR))


def true_peak(x):
    return float(np.max(np.abs(signal.resample_poly(x, 4, 1, axis=0)))) + 1e-12


def active_rms(x, win=0.01, rel_db=30.0):
    m = mono(x)[:, 0]
    w = max(1, int(SR * win))
    env = np.sqrt(np.convolve(m ** 2, np.ones(w) / w, 'same'))
    act = env > env.max() * 10 ** (-rel_db / 20)
    return float(np.sqrt(np.mean(m[act] ** 2))) + 1e-12


def rms(x):
    return float(np.sqrt(np.mean(mono(x)[:, 0] ** 2))) + 1e-12


def db(v):
    return 20 * np.log10(max(v, 1e-12))


def norm_peak(x, target_db):
    return x * (10 ** (target_db / 20) / true_peak(x))


def norm_active_rms(x, target_db, ceiling_db=-1.0):
    y = x * (10 ** (target_db / 20) / active_rms(x))
    tp = true_peak(y)
    if db(tp) > ceiling_db:  # never clip: lower the whole file (reported in the stats)
        y *= 10 ** (ceiling_db / 20) / tp
    return y


def norm_rms(x, target_db, ceiling_db=-1.0):
    y = x * (10 ** (target_db / 20) / rms(x))
    tp = true_peak(y)
    if db(tp) > ceiling_db:
        y *= 10 ** (ceiling_db / 20) / tp
    return y


def pitch(x, factor):
    """Resample so the sound plays `factor` times higher (and shorter)."""
    up, down = int(round(1000 / factor)), 1000
    g = np.gcd(up, down)
    return signal.resample_poly(x, up // g, down // g, axis=0)


def pad_mix(*parts):
    """Sum (offset_s, pcm (n,ch)) layers; mono layers broadcast to the widest channel count."""
    ch = max(p.shape[1] for _, p in parts)
    n = max(int(round(o * SR)) + len(p) for o, p in parts)
    y = np.zeros((n, ch))
    for o, p in parts:
        i = int(round(o * SR))
        y[i:i + len(p)] += p if p.shape[1] == ch else np.repeat(p, ch, axis=1)
    return y


def emit(key, name, x, *, source, synth=False, quality=0.4, group=None, note=''):
    """Write one variation file and record it."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    tp = true_peak(x)
    assert db(tp) <= -0.5, f'{name}: true peak {db(tp):.2f} dBFS (would clip)'
    os.makedirs(OUT_AUDIO, exist_ok=True)
    path = os.path.join(OUT_AUDIO, name + '.mp3')
    sf.write(path, x.astype(np.float32), SR, format='MP3', subtype='MPEG_LAYER_III', bitrate_mode='VARIABLE', compression_level=quality)
    BANK.setdefault(key, []).append(name + '.mp3')
    FILES[name + '.mp3'] = {
        'key': key,
        'duration': round(len(x) / SR, 3),
        'channels': int(x.shape[1]),
        'truePeakDb': round(db(tp), 1),
        'rmsDb': round(db(rms(x)), 1),
        'activeRmsDb': round(db(active_rms(x)), 1),
        'bytes': os.path.getsize(path),
        'source': source,
        'synth': bool(synth),
        'note': note,
    }
    GROUPS.setdefault(group or key.split('_')[0], []).append((name, x))


# ----------------------------------------------------------------------------------------- synthesis

def rng(seed):
    return np.random.default_rng(seed)


def n_wave(duration_s, amp=1.0, rise_s=8e-6, os_factor=8):
    """Sonic-boom style N-wave (bullet shock wave): jump to +amp, linear fall to -amp over duration, jump back.
    Built at os_factor x SR and decimated (anti-aliased)."""
    fs = SR * os_factor
    n = int(duration_s * fs) + 1
    body = np.linspace(amp, -amp, n)
    r = max(2, int(rise_s * fs))
    ramp_up = np.linspace(0, amp, r)
    ramp_dn = np.linspace(-amp, 0, r)
    w = np.concatenate([np.zeros(8 * os_factor), ramp_up, body, ramp_dn, np.zeros(8 * os_factor)])
    return signal.resample_poly(w, 1, os_factor)[:, None]


def swept_noise(dur, f_start, f_end, q=1.2, seed=0):
    """Band-passed noise whose centre frequency sweeps exponentially f_start -> f_end (Doppler-like), block-wise."""
    r = rng(seed)
    n = int(dur * SR)
    x = r.standard_normal(n)
    y = np.zeros(n)
    blk = 256
    zi = None
    for i in range(0, n, blk):
        t = i / max(1, n - 1)
        fc = f_start * (f_end / f_start) ** t
        bw = fc / q
        lo, hi = max(40.0, fc - bw / 2), min(SR / 2 - 100, fc + bw / 2)
        sos = signal.butter(2, [lo, hi], 'bandpass', fs=SR, output='sos')
        if zi is None or zi.shape[0] != sos.shape[0]:
            zi = np.zeros((sos.shape[0], 2))
        y[i:i + blk], zi = signal.sosfilt(sos, x[i:i + blk], zi=zi)
    return y[:, None]


def env_exp(n, attack_s, tau_s):
    t = np.arange(n) / SR
    a = np.clip(t / max(attack_s, 1e-5), 0, 1)
    return (a * np.exp(-np.maximum(t - attack_s, 0) / tau_s))[:, None]


def grains(dur, count, f_lo, f_hi, tau, seed, gmin=0.0008, gmax=0.004):
    """Granular debris: `count` short windowed noise bursts, band-limited, amplitudes decaying with time."""
    r = rng(seed)
    n = int(dur * SR)
    y = np.zeros((n, 1))
    times = np.sort(r.exponential(tau * 0.8, count))
    times = times[times < dur - gmax]
    for t0 in times:
        g = int(r.uniform(gmin, gmax) * SR)
        burst = r.standard_normal(g) * np.hanning(g)
        f1 = r.uniform(f_lo, (f_lo + f_hi) / 2)
        f2 = min(SR / 2 - 200, f1 * r.uniform(1.6, 3.0))
        burst = signal.sosfilt(signal.butter(2, [f1, f2], 'bandpass', fs=SR, output='sos'), burst)
        i = int(t0 * SR)
        y[i:i + g, 0] += burst * np.exp(-t0 / tau) * r.uniform(0.3, 1.0)
    return y


def modal(freqs, taus, amps, dur, seed=0):
    r = rng(seed)
    t = np.arange(int(dur * SR)) / SR
    y = np.zeros_like(t)
    for f, tau, a in zip(freqs, taus, amps):
        if f >= 0.45 * SR:  # would alias
            continue
        y += a * np.sin(2 * np.pi * f * t + r.uniform(0, 2 * np.pi)) * np.exp(-t / tau)
    return y[:, None]


def periodic_noise(n, slope_db_oct, f_lo, f_hi, seed):
    """Loopable coloured noise: random-phase spectrum with a power-law magnitude, inverse FFT (circular = seamless loop)."""
    r = rng(seed)
    f = np.fft.rfftfreq(n, 1 / SR)
    mag = np.zeros_like(f)
    band = (f >= f_lo) & (f <= f_hi)
    mag[band] = (f[band] / 100.0) ** (slope_db_oct / 6.02)
    # soft band edges
    mag *= 1 / (1 + (f_lo / np.maximum(f, 1)) ** 4) * 1 / (1 + (f / f_hi) ** 4)
    spec = mag * np.exp(1j * r.uniform(0, 2 * np.pi, len(f)))
    x = np.fft.irfft(spec, n)
    return x / (np.std(x) + 1e-12)


# ----------------------------------------------------------------------------------------- builds

def build_weapons():
    src = 'ffsl'
    # Firing reports: The Free Firearm Sound Library (CC0), 96 kHz / 24-bit field recordings.
    d32 = load('ffsl/D_32P.wav')  # AR-15 5.56x45, near, front of shooter, stereo L/R
    d24 = load('ffsl/D_24P.wav')  # AR-15, mid distance, front of shooter (bullet crack arrives before the report)
    x39 = load('ffsl/X_39P.wav')  # Walther PPQ 9 mm, near
    x31 = load('ffsl/X_31P.wav')  # Walther PPQ 9 mm, mid distance
    shots_d32 = [0.703, 5.646]
    shots_d24 = [0.548, 3.909]
    shots_x39 = [1.406, 6.443, 10.659]
    shots_x31 = [1.084, 5.242]

    def report(x, t, length, fade_from, target, stereo=True):
        a = seg(x, t - 0.02, t + length + 0.02)
        a = a[onset(a, -30, pre=0.003):][:int(length * SR)]
        if not stereo:
            a = mono(a)
        a = hp(a, 25)
        a = fade(a, 0.0005, fout_start=fade_from)
        return norm_peak(a, target)

    for i, t in enumerate(shots_d32):
        emit('rifle_close', f'rifle_close_{i + 1}', report(d32, t, 0.55, 0.30, -3.0), source=f'{src}:D_32P.wav@{t:.3f}s', quality=0.3, group='weapons')
    for i, t in enumerate(shots_x39):
        emit('pistol_close', f'pistol_close_{i + 1}', report(x39, t, 0.45, 0.24, -4.0), source=f'{src}:X_39P.wav@{t:.3f}s', quality=0.3, group='weapons')
    for i, t in enumerate(shots_d24):
        emit('rifle_distant', f'rifle_distant_{i + 1}', report(d24, t, 1.5, 0.9, -6.0, stereo=False), source=f'{src}:D_24P.wav@{t:.3f}s', quality=0.45, group='weapons')
    for i, t in enumerate(shots_x31):
        emit('pistol_distant', f'pistol_distant_{i + 1}', report(x31, t, 1.3, 0.8, -6.0, stereo=False), source=f'{src}:X_31P.wav@{t:.3f}s', quality=0.45, group='weapons')

    # Outdoor tail: the reflections / reverberation of the mid-distance take, without its direct report.
    def tail(x, t, start, length, target):
        a = seg(x, t + start, t + start + length)
        a = lp(hp(a, 60), 6000)
        a = fade(a, 0.03, fout_start=length * 0.45)
        return norm_peak(a, target)

    for i, t in enumerate(shots_d24):
        emit('rifle_tail', f'rifle_tail_{i + 1}', tail(d24, t, 0.10, 1.45, -9.0), source=f'{src}:D_24P.wav@{t + 0.10:.3f}s (reflections only)', quality=0.5, group='weapons')
    emit('pistol_tail', 'pistol_tail_1', tail(x31, shots_x31[0], 0.09, 1.2, -9.0), source=f'{src}:X_31P.wav@{shots_x31[0] + 0.09:.3f}s (reflections only)', quality=0.5, group='weapons')


def build_mechanics():
    lfa = mono(load('lfa/equipment_clicks3.wav'))            # real bolt-action rifle, stapler, tape measure (CC0)
    ar = mono(load('springy/assaultriflereload1_0.wav'))     # airsoft rifle reload (CC0)
    pr = mono(load('springy/gunreload1.wav'))                # airsoft pistol reload (CC0)

    def cut(x, t0, t1, target, hpf=120, fin=0.002, fout=0.04, trim_db=-20):
        a = hp(seg(x, t0, t1), hpf)
        a = a[onset(a, trim_db, pre=0.004):]  # the sound starts at the event (no silent lead-in)
        a = fade(a, fin, fout)
        return norm_peak(a, target)

    emit('rifle_mag_out', 'rifle_mag_out', cut(ar, 0.12, 0.52, -10), source='springy:assaultriflereload1_0.wav@0.12-0.52s', group='mechanics')
    emit('rifle_mag_in', 'rifle_mag_in', cut(ar, 1.00, 1.24, -10), source='springy:assaultriflereload1_0.wav@1.00-1.24s', group='mechanics')
    emit('rifle_bolt_release', 'rifle_bolt_release', cut(lfa, 18.026, 18.21, -10, hpf=80, trim_db=-12), source='lfa:equipment_clicks3.wav@18.026-18.21s', group='mechanics')
    emit('rifle_charge_pull', 'rifle_charge_pull', cut(lfa, 1.449, 1.707, -11), source='lfa:equipment_clicks3.wav@1.449-1.707s', group='mechanics')
    emit('rifle_charge_release', 'rifle_charge_release', cut(lfa, 0.854, 1.094, -10, hpf=80, trim_db=-12), source='lfa:equipment_clicks3.wav@0.854-1.094s', group='mechanics')
    emit('pistol_mag_out', 'pistol_mag_out', cut(pr, 0.08, 0.32, -11), source='springy:gunreload1.wav@0.08-0.32s', group='mechanics')
    emit('pistol_mag_in', 'pistol_mag_in', cut(pr, 0.64, 0.82, -11, hpf=200), source='springy:gunreload1.wav@0.64-0.82s', group='mechanics')
    emit('pistol_slide_pull', 'pistol_slide_pull', cut(lfa, 18.807, 19.08, -12), source='lfa:equipment_clicks3.wav@18.807-19.08s', group='mechanics')
    emit('pistol_slide_release', 'pistol_slide_release', cut(lfa, 16.292, 16.448, -10, hpf=100, trim_db=-12), source='lfa:equipment_clicks3.wav@16.292-16.448s', group='mechanics')
    emit('rifle_dry', 'rifle_dry', cut(lfa, 0.186, 0.347, -14, hpf=300, trim_db=-12), source='lfa:equipment_clicks3.wav@0.186-0.347s', group='mechanics')
    emit('pistol_dry', 'pistol_dry', cut(lfa, 5.085, 5.176, -14, hpf=300, trim_db=-12), source='lfa:equipment_clicks3.wav@5.085-5.176s', group='mechanics')

    # weapon switch: cloth / webbing and a latch (Kenney RPG Audio, CC0)
    for i, f in enumerate(['cloth1', 'cloth2', 'cloth3']):
        a = hp(mono(load(f'kenney_rpg/{f}.ogg')), 120)
        a = fade(a[onset(a, -30, pre=0.01):], 0.003, 0.08)
        emit('switch_cloth', f'switch_cloth_{i + 1}', norm_peak(a, -16), source=f'kenney_rpg:{f}.ogg', group='gear')
    belt = hp(mono(load('kenney_rpg/beltHandle1.ogg')), 150)
    latch = hp(mono(load('kenney_rpg/metalLatch.ogg')), 200)
    emit('switch_draw_rifle', 'switch_draw_rifle', norm_peak(fade(pad_mix((0, belt), (0.16, latch * 0.35)), 0.002, 0.05), -12), source='kenney_rpg:beltHandle1.ogg + metalLatch.ogg', group='gear')
    leather = hp(mono(load('kenney_rpg/handleSmallLeather.ogg')), 150)
    click = seg(hp(mono(load('kenney_rpg/metalClick.ogg')), 300), 0.24, 0.40)
    emit('switch_draw_pistol', 'switch_draw_pistol', norm_peak(fade(pad_mix((0, leather), (0.19, click * 0.6)), 0.002, 0.05), -13), source='kenney_rpg:handleSmallLeather.ogg + metalClick.ogg', group='gear')


def build_steps():
    def step(rel, maxlen=0.30, hpf=60, fout=0.10):
        a = mono(load(rel))
        a = a[onset(a, -34, pre=0.002):][:int(maxlen * SR)]
        a = hp(a, hpf)
        a = fade(a, 0.001, min(fout, len(a) / SR * 0.5))
        return norm_active_rms(a, -24.0)

    fz = [f'{s}{i}' for s in 'LR' for i in (1, 2, 3)]
    for i, f in enumerate(fz):
        emit('step_concrete', f'step_concrete_{i + 1}', step(f'fantozzi/Fantozzi-Stone{f}.ogg'), source=f'fantozzi:Fantozzi-Stone{f}.ogg', group='steps')
    for i, f in enumerate(fz):
        emit('step_dirt', f'step_dirt_{i + 1}', step(f'fantozzi/Fantozzi-Sand{f}.ogg', maxlen=0.32), source=f'fantozzi:Fantozzi-Sand{f}.ogg', group='steps')
    for i in range(6):
        emit('step_gravel', f'step_gravel_{i + 1}', step(f'cdogs/gravel/{i}.ogg', maxlen=0.26), source=f'cdogs:gravel/{i}.ogg', group='steps')
    for i in range(5):
        emit('step_grass', f'step_grass_{i + 1}', step(f'kenney_impact/footstep_grass_00{i}.ogg', maxlen=0.22), source=f'kenney_impact:footstep_grass_00{i}.ogg', group='steps')
    # wood: Kenney RPG Audio boot steps (heel + toe) over the Kenney wood-floor thump (resonant body), both CC0
    for i in range(6):
        boot = mono(load(f'kenney_rpg/footstep0{i}.ogg'))
        boot = hp(boot[onset(boot, -34, pre=0.002):][:int(0.26 * SR)], 70)
        body = mono(load(f'kenney_impact/footstep_wood_00{i % 5}.ogg'))
        body = lp(body[onset(body, -34, pre=0.002):][:int(0.12 * SR)], 1800)
        a = fade(pad_mix((0, boot), (0, body * 0.5)), 0.001, 0.09)
        emit('step_wood', f'step_wood_{i + 1}', norm_active_rms(a, -24.0), source=f'kenney_rpg:footstep0{i}.ogg + kenney_impact:footstep_wood_00{i % 5}.ogg', group='steps')
    for i in range(6):
        emit('step_metal', f'step_metal_{i + 1}', step(f'cdogs/metal/{i}.ogg', maxlen=0.30), source=f'cdogs:metal/{i}.ogg', group='steps')

    # jump / land layers (played together with the surface step at runtime)
    c4 = hp(mono(load('kenney_rpg/cloth4.ogg')), 150)
    b2 = hp(mono(load('kenney_rpg/beltHandle2.ogg')), 200)
    emit('jump_gear', 'jump_gear_1', norm_peak(fade(pad_mix((0, c4), (0.05, b2 * 0.3)), 0.002, 0.08), -16), source='kenney_rpg:cloth4.ogg + beltHandle2.ogg', group='gear')
    cb = hp(mono(load('kenney_rpg/clothBelt2.ogg')), 150)
    emit('jump_gear', 'jump_gear_2', norm_peak(fade(cb, 0.002, 0.1), -16), source='kenney_rpg:clothBelt2.ogg', group='gear')
    cbt = hp(mono(load('kenney_rpg/clothBelt.ogg')), 150)
    emit('traverse_gear', 'traverse_gear_1', norm_peak(fade(cbt, 0.002, 0.1), -15), source='kenney_rpg:clothBelt.ogg', group='gear')
    for i in range(2):
        th = lp(mono(load(f'kenney_impact/impactSoft_heavy_00{i}.ogg')), 500)[:int(0.28 * SR)]
        emit('land_thump', f'land_thump_{i + 1}', norm_peak(fade(th, 0.001, 0.12), -12), source=f'kenney_impact:impactSoft_heavy_00{i}.ogg (low-passed 500 Hz)', group='steps')


def build_impacts():
    # Bullet impacts: Kenney Impact Sounds (CC0) material bodies, pitched up (small, fast object), plus
    # procedural layers (impact crack, debris grains, dirt spray, glass shards) -> derivative + synthesis.
    def crack(seed, dur=0.004, hpf=1500, amp=1.0):
        r = rng(seed)
        n = int(dur * SR)
        return hp(r.standard_normal((n, 1)) * env_exp(n, 0.0001, dur / 4), hpf) * amp

    for i in range(3):
        body = pitch(mono(load(f'kenney_impact/impactGeneric_light_00{i}.ogg')), 1.25)[:int(0.12 * SR)]
        deb = grains(0.22, 40, 1500, 9000, 0.06, seed=100 + i)
        a = pad_mix((0, crack(10 + i) * 0.9), (0.0005, body * 0.8), (0.002, deb * 0.9))
        emit('impact_concrete', f'impact_concrete_{i + 1}', norm_peak(fade(hp(a, 90), 0.0003, 0.06), -8), source=f'kenney_impact:impactGeneric_light_00{i}.ogg + synth crack/debris', synth=True, group='impacts')
    for i in range(3):
        body = pitch(mono(load(f'kenney_impact/impactMetal_light_00{i}.ogg')), 1.15)[:int(0.32 * SR)]
        ping = modal([2900 + 300 * i, 5100 + 200 * i, 7900], [0.09, 0.05, 0.03], [0.5, 0.35, 0.2], 0.3, seed=20 + i)
        a = pad_mix((0, crack(30 + i, hpf=2500) * 0.8), (0.0005, body), (0.001, ping * 0.4))
        emit('impact_metal', f'impact_metal_{i + 1}', norm_peak(fade(hp(a, 150), 0.0003, 0.1), -8), source=f'kenney_impact:impactMetal_light_00{i}.ogg + synth ping', synth=True, group='impacts')
    for i in range(3):
        body = pitch(mono(load(f'kenney_impact/impactWood_light_00{i}.ogg')), 1.2)[:int(0.16 * SR)]
        spl = grains(0.12, 22, 900, 6000, 0.035, seed=200 + i, gmax=0.006)
        a = pad_mix((0, crack(40 + i, hpf=1200) * 0.7), (0.0005, body), (0.003, spl * 0.7))
        emit('impact_wood', f'impact_wood_{i + 1}', norm_peak(fade(hp(a, 100), 0.0003, 0.05), -8), source=f'kenney_impact:impactWood_light_00{i}.ogg + synth splinters', synth=True, group='impacts')
    for i in range(3):
        body = lp(pitch(mono(load(f'kenney_impact/impactSoft_medium_00{i}.ogg')), 1.1), 900)[:int(0.1 * SR)]
        r = rng(300 + i)
        n = int(0.22 * SR)
        spray = lp(hp(r.standard_normal((n, 1)), 300), 2200) * env_exp(n, 0.002, 0.05)
        deb = grains(0.2, 25, 600, 3500, 0.05, seed=310 + i)
        a = pad_mix((0, body), (0.001, spray * 0.5), (0.004, deb * 0.5))
        emit('impact_dirt', f'impact_dirt_{i + 1}', norm_peak(fade(hp(a, 70), 0.0003, 0.07), -9), source=f'kenney_impact:impactSoft_medium_00{i}.ogg + synth dirt spray', synth=True, group='impacts')
    for i in range(2):
        body = pitch(mono(load(f'kenney_impact/impactGlass_light_00{i}.ogg')), 1.1)[:int(0.2 * SR)]
        r = rng(400 + i)
        shards = np.zeros((int(0.35 * SR), 1))
        for k in range(14):
            t0 = r.exponential(0.06)
            if t0 > 0.3:
                continue
            f0 = r.uniform(3000, 9000)
            m = modal([f0, f0 * 1.58, f0 * 2.31], [0.02, 0.012, 0.008], [1, 0.5, 0.3], 0.05, seed=410 + k)
            j = int(t0 * SR)
            shards[j:j + len(m)] += m[:len(shards) - j] * np.exp(-t0 / 0.08) * r.uniform(0.2, 0.7)
        a = pad_mix((0, crack(50 + i, hpf=3000)), (0.0005, body * 0.8), (0.002, shards * 0.5))
        emit('impact_glass', f'impact_glass_{i + 1}', norm_peak(fade(hp(a, 300), 0.0003, 0.08), -8), source=f'kenney_impact:impactGlass_light_00{i}.ogg + synth shards', synth=True, group='impacts')
    for i in range(3):
        body = lp(mono(load(f'kenney_impact/impactPunch_medium_00{i}.ogg')), 3500)
        body = body[onset(body, -20):][:int(0.16 * SR)]
        emit('impact_flesh', f'impact_flesh_{i + 1}', norm_peak(fade(hp(body, 80), 0.0005, 0.06), -12), source=f'kenney_impact:impactPunch_medium_00{i}.ogg (low-passed, shortened)', group='impacts')


def build_nearmiss():
    # Supersonic bullet passing the listener: N-wave shock (Whitham: T ~ 1.82 M d r^1/4 / (c (M^2-1)^3/8 l^1/4) ~ 0.12-0.2 ms
    # for 5.56 mm at 1-3 m), ground reflection 2-3 ms later, a short turbulent wake whoosh with a falling (Doppler)
    # centre frequency and a faint terrain slap. Procedural synthesis (provisional).
    for i, (T, refl, slap) in enumerate([(150e-6, 0.0022, 0.055), (180e-6, 0.0029, 0.071), (130e-6, 0.0018, 0.088)]):
        nw = n_wave(T)
        gr = lp(n_wave(T * 1.15), 9000) * 0.55
        wake = swept_noise(0.16, 7000, 1800, q=1.0, seed=500 + i) * env_exp(int(0.16 * SR), 0.004, 0.045) * 0.35
        sl = lp(hp(n_wave(T * 3) * 0.25, 300), 2500)
        a = pad_mix((0, nw), (refl, gr), (0.001, wake), (slap, sl))
        emit('nearmiss_crack', f'nearmiss_crack_{i + 1}', norm_peak(fade(hp(a, 150), 0.0002, 0.03), -6), source='procedural synthesis (N-wave + wake)', synth=True, group='nearmiss')
    # 9 mm is barely supersonic: weak shock, dominant wake "whiz"
    for i in range(2):
        nw = n_wave(90e-6) * 0.35
        wake = swept_noise(0.22, 4200 - 400 * i, 1100, q=1.6, seed=520 + i) * env_exp(int(0.22 * SR), 0.03, 0.06) * 0.6
        a = pad_mix((0, nw), (0.0, wake))
        emit('nearmiss_whiz', f'nearmiss_whiz_{i + 1}', norm_peak(fade(hp(a, 200), 0.0005, 0.05), -8), source='procedural synthesis (weak N-wave + Doppler wake)', synth=True, group='nearmiss')


def build_casings():
    # Spent brass on a hard floor: modal synthesis of a thin brass tube (free-free beam ratios 1 : 2.76 : 5.40),
    # 2-4 bounces with shrinking energy and intervals (restitution ~0.5), each with a contact click. Procedural (provisional).
    for kind, f1, length in [('rifle', 3150, 0.36), ('pistol', 4700, 0.3)]:
        for v in range(2):
            r = rng(600 + v + (10 if kind == 'pistol' else 0))
            y = np.zeros((int(length * SR), 1))
            t, e, gap = 0.0, 1.0, r.uniform(0.07, 0.1)
            for b in range(4):
                if t >= length - 0.06:
                    break
                jit = r.uniform(0.97, 1.03)
                m = modal([f1 * jit, f1 * 2.76 * jit, f1 * 5.40 * jit], [0.07, 0.035, 0.02], [1.0, 0.55, 0.3], 0.12, seed=620 + b + v)
                clk = hp(r.standard_normal((int(0.0012 * SR), 1)), 3000) * 0.6
                j = int(t * SR)
                seg_ = pad_mix((0, clk), (0, m))[:len(y) - j]
                y[j:j + len(seg_)] += seg_ * e
                t += gap
                gap *= 0.62
                e *= 0.45
            emit(f'casing_{kind}', f'casing_{kind}_{v + 1}', norm_peak(fade(hp(y, 1500), 0.0002, 0.05), -18), source='procedural synthesis (modal brass)', synth=True, group='casings')


def build_ambience():
    # Wind bed: loopable (circular FFT noise, gusts with an integer number of cycles per loop), stereo
    # (independent noise per channel, shared gust envelope), spectrum ~ -4.5 dB/oct from 100 Hz, plus a faint
    # gust-dependent rustle band. Procedural synthesis (provisional) — no licence-clean wind recording was reachable.
    dur = 16.0
    n = int(dur * SR)
    t = np.arange(n) / SR
    r = rng(700)
    gust = np.zeros(n)
    for k in (1, 2, 3, 5, 7):
        gust += r.uniform(0.3, 1.0) / k ** 0.5 * np.sin(2 * np.pi * k / dur * t + r.uniform(0, 2 * np.pi))
    gust = (gust - gust.min()) / (gust.max() - gust.min())
    base = 0.45 + 0.55 * gust ** 1.5
    chans = []
    for c in range(2):
        low = periodic_noise(n, -4.5, 35, 6000, seed=710 + c)
        rustle = periodic_noise(n, -3.0, 900, 7000, seed=720 + c)
        shift = int(0.35 * SR) * c  # the gust front reaches the ears at slightly different times
        env = np.roll(base, shift)
        chans.append(low * env + rustle * 0.18 * np.roll(gust, shift) ** 3)
    w = np.stack(chans, axis=1)
    emit('amb_wind', 'amb_wind_loop', norm_rms(w, -36.0), source='procedural synthesis (loopable wind)', synth=True, quality=0.55, group='ambience')

    # Distant birds: InspectorJ's robin (CC BY 4.0) cut into phrases, 2 kHz high-pass (removes the recorder's hum band),
    # air-absorption low-pass (~60 m), short fades.
    robin = mono(load('librosa/robin.hq.ogg'))
    for i, (a0, a1) in enumerate([(0.05, 0.78), (0.78, 1.26), (1.26, 2.25)]):
        a = lp(hp(seg(robin, a0, a1), 2000, order=4), 8000)
        a = fade(a, 0.02, 0.08)
        emit('amb_bird', f'amb_bird_{i + 1}', norm_active_rms(a, -34.0), source=f'librosa:robin.hq.ogg@{a0}-{a1}s', quality=0.55, group='ambience')


# ----------------------------------------------------------------------------------------- review

def review_png():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    os.makedirs(OUT_REVIEW, exist_ok=True)
    for g, items in GROUPS.items():
        n = len(items)
        fig, axes = plt.subplots(n, 2, figsize=(13, 1.55 * n + 0.4), squeeze=False)
        for i, (name, x) in enumerate(items):
            m = mono(x)[:, 0]
            s = FILES[name + '.mp3']
            ax = axes[i][0]
            ax.plot(np.arange(len(m)) / SR, m, lw=0.4)
            ax.set_ylim(-1, 1)
            ax.set_title(f"{name}  {s['duration']:.3f}s  TP {s['truePeakDb']} dBFS  RMS {s['rmsDb']}  act {s['activeRmsDb']}  {s['channels']}ch  {s['bytes'] // 1024} KiB", fontsize=7)
            nper = 1024 if len(m) > SR * 0.8 else 256
            f, tt, S = signal.spectrogram(m, SR, nperseg=nper, noverlap=nper * 3 // 4)
            axes[i][1].pcolormesh(tt, f, 10 * np.log10(S + 1e-14), shading='auto', vmin=-130, vmax=-30, cmap='magma')
            axes[i][1].set_ylim(0, 20000)
            for a in axes[i]:
                a.tick_params(labelsize=6)
        fig.tight_layout()
        fig.savefig(os.path.join(OUT_REVIEW, f'review_{g}.png'), dpi=62)
        plt.close(fig)


def main():
    global SRC
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', default=SRC)
    ap.add_argument('--no-png', action='store_true')
    args = ap.parse_args()
    SRC = args.src
    if os.path.isdir(OUT_AUDIO):
        for f in os.listdir(OUT_AUDIO):
            if f.endswith('.mp3'):
                os.remove(os.path.join(OUT_AUDIO, f))
    build_weapons()
    build_mechanics()
    build_steps()
    build_impacts()
    build_nearmiss()
    build_casings()
    build_ambience()
    total = sum(v['bytes'] for v in FILES.values())
    bank = {
        '_comment': 'GENERATED by Tools/audio/build_audio.py — do not edit. Sound key -> variation files in assets/audio/, with measured stats. Provenance: Shared/audio/SOURCES.md.',
        'basePath': 'assets/audio/',
        'sounds': BANK,
        'files': FILES,
        'totalBytes': total,
    }
    with open(OUT_BANK, 'w', encoding='utf8') as fh:
        json.dump(bank, fh, indent=1, ensure_ascii=False)
        fh.write('\n')
    if not args.no_png:
        review_png()
    print(f'{len(FILES)} files, {len(BANK)} sound keys, {total / 1024:.0f} KiB total -> {OUT_AUDIO}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
