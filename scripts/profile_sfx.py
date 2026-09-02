#!/usr/bin/env python3
"""Perfil acustico de candidatos a SFX: duracao, pico, forma do envelope (sobe/desce),
centroide espectral medio (brilho) e energia grave. Saida JSON por arquivo."""
import json, os, subprocess, sys, math, glob, wave, array

FF = os.path.expanduser("~/.local/tools/ffmpeg")
FP = os.path.expanduser("~/.local/tools/ffprobe")

def run(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stderr.decode("utf-8", "replace")

def to_wav(src, dst):
    subprocess.run([FF, "-v", "error", "-y", "-i", src, "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", dst], check=True)

def profile(path):
    tmp = path + ".prof.wav"
    try:
        to_wav(path, tmp)
    except Exception as e:
        return {"file": path, "ok": False, "err": str(e)}
    w = wave.open(tmp); n = w.getnframes(); sr = w.getframerate()
    a = array.array("h"); a.frombytes(w.readframes(n)); w.close()
    if n == 0:
        return {"file": path, "ok": False, "err": "vazio"}
    dur = n / float(sr)
    peak = max(1, max(abs(x) for x in a))
    peak_db = 20 * math.log10(peak / 32768.0)
    # envelope RMS em janelas de 20 ms
    win = int(sr * 0.02); env = []
    for i in range(0, n, win):
        seg = a[i:i + win]
        if not seg: break
        env.append(math.sqrt(sum(x * x for x in seg) / float(len(seg))) / 32768.0)
    tot = sum(env) or 1e-9
    # centro de massa temporal da energia (0..1): <0.4 = ataque no comeco (hit/pop), >0.6 = sobe (riser/whoosh crescente)
    t_cm = sum(e * (k + 0.5) / len(env) for k, e in enumerate(env)) / tot
    # tempo ate o pico
    kmax = max(range(len(env)), key=lambda k: env[k]); t_peak = (kmax + 0.5) * 0.02
    # cauda: quanto tempo depois do pico ate cair 20 dB
    thr = env[kmax] * 0.1; k2 = kmax
    while k2 < len(env) and env[k2] > thr: k2 += 1
    tail = (k2 - kmax) * 0.02
    # duracao util: primeiro/ultimo ponto acima de -40 dB do pico
    thr2 = env[kmax] * 0.01
    ks = [k for k, e in enumerate(env) if e > thr2]
    useful = ((ks[-1] - ks[0] + 1) * 0.02) if ks else 0
    # espectro: centroide e razao grave via ffmpeg aspectralstats + bandas
    txt = run([FF, "-v", "info", "-i", tmp, "-af", "aspectralstats=measure=centroid,ametadata=print:file=-", "-f", "null", "-"])
    cents = [float(l.split("=")[1]) for l in txt.splitlines() if "centroid=" in l and l.split("=")[1].strip() not in ("nan", "-nan", "inf")]
    centroid = sum(cents) / len(cents) if cents else 0.0
    def band_rms(lo, hi):
        f = "highpass=f=%d,lowpass=f=%d,astats=measure_overall=RMS_level:measure_perchannel=0" % (lo, hi) if lo > 0 else "lowpass=f=%d,astats=measure_overall=RMS_level:measure_perchannel=0" % hi
        t = run([FF, "-v", "info", "-i", tmp, "-af", f, "-f", "null", "-"])
        for l in t.splitlines():
            if "RMS level dB" in l:
                try: return float(l.split(":")[-1])
                except: return -99.0
        return -99.0
    low = band_rms(0, 150); mid = band_rms(150, 2000); high = band_rms(2000, 20000)
    os.remove(tmp)
    return {"file": os.path.basename(path), "ok": True, "dur_s": round(dur, 3), "useful_s": round(useful, 3), "peak_dbfs": round(peak_db, 1),
            "t_peak_s": round(t_peak, 3), "tail_s": round(tail, 3), "energy_cm": round(t_cm, 2),
            "centroid_hz": round(centroid), "low_db": round(low, 1), "mid_db": round(mid, 1), "high_db": round(high, 1)}

if __name__ == "__main__":
    files = sys.argv[1:] or sorted(glob.glob(os.path.join(os.path.dirname(__file__), "raw", "*")))
    out = [profile(f) for f in files if os.path.isfile(f) and not f.endswith(".prof.wav")]
    print(json.dumps(out, indent=1))
