#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EditClean - compose_shots.py (v4.0, 05/09/2026) -- estilo dinamico aprovado pelo Gabriel no GPT-6 Astra
("Simplesmente incrivel nota 10").

Compoe, quadro a quadro, a BASE (render sem legenda, sem insercao, sem push-down) + a CAMADA DE
LEGENDA (do captions.ass, via matte de dois fundos) + os SHOTS de shots.json. Formas de mostrar:

  split      imagem grande no alto (caixa 1000x600 sobre fundo desfocado), pessoa recortada embaixo,
             legenda desce para a COSTURA por crossfade (nunca viaja pela tela). Entrada 0,30 s com
             rastro de movimento (10 subpassos), saida 0,26 s. Pelo menos UMA por video (regra 21).
  fullpan    imagem em tela cheia com pan horizontal e zoom lento (foto larga). Pessoa some.
  clip       b-roll em video, tela cheia (cover, ancora horizontal) com zoom lento; fit=width mostra
             o quadro 16:9 inteiro numa faixa sobre o proprio quadro desfocado (titulos, telas).
  highlight  pagina/tabela em tela cheia sobre a base desfocada e escura, marca-texto amarelo que
             cresce sobre 'marks' e zoom lento ate 'focus' (linha do 92,7%).
  PROIBIDO   qualquer coisa NA FRENTE DO ROSTO (o antigo 'card'): regra 20.

Uso: compose_shots.py --base base.mp4 --shots shots.json --ass captions.ass --fonts <dir>
                      --subject subject.json --out comp.mp4 [--crf 14]
"""
import argparse, json, os, re, subprocess, sys, math
import numpy as np
from PIL import Image, ImageFilter, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))


def _bin(name):
    for c in (os.path.expanduser("~/.local/tools/" + name), "/opt/homebrew/bin/" + name, "/usr/local/bin/" + name):
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return name


FF, FP = _bin("ffmpeg"), _bin("ffprobe")
W_, H_ = 1080, 1920
HT = 940                       # costura da tela dividida
BOX = (40, 40, 1040, 640)      # caixa da imagem nitida no split
CAP_XFADE = 0.14
ALLOWED = ("split", "fullpan", "clip", "highlight")


def ease_out(p): return 1 - (1 - p) ** 3
def ease_in_out(p): return 3 * p * p - 2 * p * p * p
def smooth(p): return p * p * (3 - 2 * p)
def clamp(x, a, b): return max(a, min(b, x))


def probe(path):
    o = subprocess.run([FP, "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=nb_frames,r_frame_rate,duration,width,height", "-of", "json", path],
                       capture_output=True, text=True).stdout
    st = json.loads(o)["streams"][0]; n, d = st["r_frame_rate"].split("/")
    return int(st.get("nb_frames") or 0), float(n) / float(d), float(st.get("duration") or 0), int(st["width"]), int(st["height"])


def cover_resize(im, w, h, anchor=(0.5, 0.5)):
    s = max(w / im.width, h / im.height)
    r = im.resize((max(w, int(im.width * s + 0.5)), max(h, int(im.height * s + 0.5))), Image.LANCZOS)
    x0 = int((r.width - w) * anchor[0]); y0 = int((r.height - h) * anchor[1])
    return r.crop((x0, y0, x0 + w, y0 + h))


def caption_geometry(ass_path):
    """Ancora \\pos(x,Y) e corpo maximo do .ass -> (Y base, Y na costura). O bloco visivel comeca
    ~0,48*fs abaixo da ancora (medido: 66 px em fs 138)."""
    txt = open(ass_path, encoding="utf-8", errors="replace").read()
    ys = [int(m) for m in re.findall(r"\\pos\(\d+,(\d+)\)", txt)]
    fs = [int(m) for m in re.findall(r"\\fs(\d+)", txt)]
    base_y = int(np.median(ys)) if ys else 1055
    # corpo da SANS (o mais frequente), nao o maximo: o serifado 1,55x e minoria e puxava a legenda
    # para cima de mais (medido: ancora 553 punha o bloco em 575-776, em cima da imagem; 589 -> 655)
    body = max(set(fs), key=fs.count) if fs else 138
    off = int(0.48 * body)
    split_y = BOX[3] + 15 - off
    return base_y, split_y


def person_window_top(subject_path):
    """janela da base mostrada na regiao da pessoa: centra o rosto (subject.json) na regiao [HT, H)."""
    try:
        s = json.load(open(subject_path, encoding="utf-8"))
        cy = float((s.get("measured") or {}).get("face_center_y_pct") or s.get("face_center_y_pct") or 0.348)
    except Exception:
        cy = 0.348
    top = int(cy * H_ - (H_ - HT) / 2.0)
    return int(clamp(top, 0, HT))


class Shot:
    ZC = 1.08   # decodifica 8% maior: sobra para o zoom lento

    def __init__(self, cfg, root, fps):
        self.cfg = cfg; self.id = cfg["id"]; self.mode = cfg["mode"]
        if self.mode not in ALLOWED:
            raise SystemExit("shot %s: modo '%s' nao existe ou e proibido (regra 20: nada na frente do rosto). Use %s"
                             % (self.id, self.mode, "/".join(ALLOWED)))
        self.a, self.b = float(cfg["start"]), float(cfg["end"]); self.fps = fps
        self.rin = float(cfg.get("ramp_in", 0.30 if self.mode == "split" else 0.22))
        self.rout = float(cfg.get("ramp_out", 0.26 if self.mode == "split" else 0.20))
        path = cfg["path"] if os.path.isabs(cfg["path"]) else os.path.join(root, cfg["path"])
        if not os.path.isfile(path):
            raise SystemExit("shot %s: arquivo nao existe: %s" % (self.id, path))
        self.frames = None
        if self.mode == "clip":
            self._load_clip(path, float(cfg.get("clip_in", 0.0)))
            return
        self.im = Image.open(path).convert("RGB")
        if self.mode == "split":
            bw, bh = BOX[2] - BOX[0], BOX[3] - BOX[1]
            s = min(bw / self.im.width, bh / self.im.height)
            self.sharp = self.im.resize((int(self.im.width * s), int(self.im.height * s)), Image.LANCZOS)
            bg = cover_resize(self.im, W_ // 4, HT // 4).filter(ImageFilter.GaussianBlur(9)).resize((W_, HT), Image.BILINEAR)
            self.bg = (np.array(bg).astype(np.float32) * 0.42).astype(np.uint8)
        elif self.mode == "fullpan":
            zmax = max(cfg.get("zoom", [1.0, 1.08])); hh = int(H_ * zmax) + 4; s = hh / self.im.height
            self.big = self.im.resize((int(self.im.width * s), hh), Image.LANCZOS)
        elif self.mode == "highlight":
            cw = int(cfg.get("page_w", 1000)); s = cw / self.im.width
            self.page = self.im.resize((cw, int(self.im.height * s)), Image.LANCZOS)
            self.marks = [(int(x0 * cw), int(y0 * self.page.height), int(x1 * cw), int(y1 * self.page.height))
                          for x0, y0, x1, y1 in cfg.get("marks", [])]

    def _load_clip(self, path, clip_in):
        need = self.b - self.a + 0.5
        ax = float(self.cfg.get("anchor_x", 0.5))
        if self.cfg.get("fit") == "width":
            cw, ch = 1280, 720
            vf = "scale=%d:%d,fps=%g" % (cw, ch, self.fps)
        else:
            cw, ch = int(W_ * self.ZC), int(H_ * self.ZC)
            vf = "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d:(iw-%d)*%.3f:(ih-%d)/2,fps=%g" % (cw, ch, cw, ch, cw, ax, ch, self.fps)
        raw = subprocess.run([FF, "-v", "error", "-ss", "%.3f" % clip_in, "-t", "%.3f" % need, "-i", path, "-vf", vf,
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout
        nf = len(raw) // (cw * ch * 3)
        if nf < int((self.b - self.a) * self.fps) - 2:
            raise SystemExit("shot %s: o clipe %s acabou antes (%d quadros para %.2f s a partir de %.2f s)"
                             % (self.id, os.path.basename(path), nf, self.b - self.a, clip_in))
        self.frames = np.frombuffer(raw[:nf * cw * ch * 3], np.uint8).reshape(nf, ch, cw, 3)
        self.cw, self.ch = cw, ch
        print("  clip %s: %d quadros de %s (in %.2f s, ancora x %.2f%s)" % (self.id, nf, os.path.basename(path), clip_in, ax,
                                                                          ", faixa 16:9" if self.cfg.get("fit") == "width" else ""))

    def progress(self, t):
        if t < self.a or t > self.b: return 0.0
        if self.rin > 0 and t < self.a + self.rin: return ease_out((t - self.a) / self.rin)
        if self.rout > 0 and t > self.b - self.rout: return ease_in_out((self.b - t) / self.rout)
        return 1.0

    def u(self, t): return clamp((t - self.a) / max(0.1, self.b - self.a), 0, 1)

    def full_frame(self, t, base):
        u = self.u(t)
        if self.mode == "clip":
            i = clamp(int(round((t - self.a) * self.fps)), 0, len(self.frames) - 1)
            z0, z1 = self.cfg.get("zoom", [1.0, 1.06]); z = z0 + (z1 - z0) * smooth(u)
            if self.cfg.get("fit") == "width":
                fr = Image.fromarray(self.frames[i]); band_h = int(W_ * fr.height / fr.width)
                band = fr.resize((int(W_ * z), int(band_h * z)), Image.BILINEAR)
                bx = (band.width - W_) // 2; by = (band.height - band_h) // 2
                band = band.crop((bx, by, bx + W_, by + band_h))
                bg = cover_resize(fr, W_ // 4, H_ // 4).filter(ImageFilter.GaussianBlur(10)).resize((W_, H_), Image.BILINEAR)
                canvas = Image.fromarray((np.array(bg).astype(np.float32) * 0.38).astype(np.uint8))
                cy = int(H_ * float(self.cfg.get("band_cy", 0.36)))
                sh = Image.new("L", (W_ + 120, band_h + 120), 0); ImageDraw.Draw(sh).rectangle((60, 60, 60 + W_, 60 + band_h), fill=160)
                sh = sh.filter(ImageFilter.GaussianBlur(24))
                canvas.paste((0, 0, 0), (-60, cy - band_h // 2 - 42, -60 + sh.width, cy - band_h // 2 - 42 + sh.height), mask=sh)
                canvas.paste(band, (0, cy - band_h // 2))
                return np.array(canvas)
            vw, vh = int(W_ * self.ZC / z), int(H_ * self.ZC / z)
            x0 = (self.cw - vw) // 2; y0 = (self.ch - vh) // 2
            return np.array(Image.fromarray(self.frames[i][y0:y0 + vh, x0:x0 + vw]).resize((W_, H_), Image.BILINEAR))
        if self.mode == "fullpan":
            z0, z1 = self.cfg.get("zoom", [1.0, 1.08]); z = z0 + (z1 - z0) * smooth(u)
            hh = int(H_ * z); s = hh / self.big.height; ww = int(self.big.width * s)
            img = self.big.resize((ww, hh), Image.BILINEAR) if (ww, hh) != self.big.size else self.big
            pan = self.cfg.get("pan", "lr")
            px = (smooth(u) if pan == "lr" else 1 - smooth(u)) if pan in ("lr", "rl") else 0.5
            x0 = int((ww - W_) * px); y0 = (hh - H_) // 2
            return np.array(img.crop((x0, y0, x0 + W_, y0 + H_)))
        if self.mode == "highlight":
            # fundo: a propria base desfocada e escura (preto puro dispara 'frames_pretos' na validacao)
            bg = Image.fromarray(base).resize((W_ // 6, H_ // 6), Image.BILINEAR).filter(ImageFilter.GaussianBlur(6)).resize((W_, H_), Image.BILINEAR)
            canvas = Image.fromarray((np.array(bg).astype(np.float32) * 0.30).astype(np.uint8))
            su = smooth(u); zoom_to = float(self.cfg.get("zoom_to", 1.05)); z = 1.0 + (zoom_to - 1.0) * su
            pw0, ph0 = self.page.width, self.page.height; page = self.page.copy()
            if self.marks:
                d = ImageDraw.Draw(page, "RGBA"); per = 0.6 / len(self.marks)
                for k, (x0, y0, x1, y1) in enumerate(self.marks):
                    pk = clamp((u - k * per) / per * 1.4, 0, 1)
                    if pk > 0:
                        d.rectangle((x0, y0, int(x0 + (x1 - x0) * smooth(pk)), y1), fill=(255, 214, 0, 120))
            pw, ph = int(pw0 * z), int(ph0 * z)
            page = page.resize((pw, ph), Image.BILINEAR) if z != 1.0 else page
            fx, fy = pw0 / 2.0, ph0 / 2.0
            if self.cfg.get("focus"):
                a0, b0, a1, b1 = self.cfg["focus"]; fx = (a0 + a1) / 2 * pw0; fy = (b0 + b1) / 2 * ph0
            ax = (pw0 / 2.0) * (1 - su) + fx * su; ay = (ph0 / 2.0) * (1 - su) + fy * su
            y_top0 = int(H_ * float(self.cfg.get("band_cy", 0.30)))
            ty = (y_top0 + ph0 / 2.0) * (1 - su) + H_ * 0.42 * su
            sh = Image.new("L", (pw + 120, ph + 120), 0); ImageDraw.Draw(sh).rectangle((60, 60, 60 + pw, 60 + ph), fill=150)
            sh = sh.filter(ImageFilter.GaussianBlur(24))
            x = int(W_ / 2.0 - ax * z); y = int(ty - ay * z) - int(20 * su)
            canvas.paste((0, 0, 0), (x - 60, y - 60 + 18, x - 60 + sh.width, y - 60 + 18 + sh.height), mask=sh)
            canvas.paste(page, (x, y))
            return np.array(canvas)
        raise ValueError(self.mode)

    def split_region(self, t):
        u = self.u(t); z = 1.0 + 0.045 * u
        sw, shh = int(self.sharp.width * z), int(self.sharp.height * z)
        img = self.sharp.resize((sw, shh), Image.BILINEAR) if z != 1.0 else self.sharp
        reg = Image.fromarray(self.bg.copy())
        cx = (BOX[0] + BOX[2]) // 2; cy = (BOX[1] + BOX[3]) // 2 - int(10 * u)
        x = cx - sw // 2; y = cy - shh // 2
        sh = Image.new("L", (sw + 80, shh + 80), 0); ImageDraw.Draw(sh).rectangle((40, 40, 40 + sw, 40 + shh), fill=150)
        sh = sh.filter(ImageFilter.GaussianBlur(18))
        reg.paste((0, 0, 0), (x - 40, y - 26, x - 40 + sh.width, y - 26 + sh.height), mask=sh)
        reg.paste(img, (x, y))
        return np.array(reg)


def zoom_blur_mix(a, b, p, strength=0.10):
    A = Image.fromarray(a); B = Image.fromarray(b)
    def zoomed(im, z):
        w, h = int(W_ * z), int(H_ * z); r = im.resize((w, h), Image.BILINEAR)
        x0, y0 = (w - W_) // 2, (h - H_) // 2; return r.crop((x0, y0, x0 + W_, y0 + H_))
    za = zoomed(A, 1 + strength * p).filter(ImageFilter.GaussianBlur(10 * p))
    zb = zoomed(B, 1 + strength * (1 - p)).filter(ImageFilter.GaussianBlur(10 * (1 - p)))
    return (np.array(za).astype(np.float32) * (1 - p) + np.array(zb).astype(np.float32) * p).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True); ap.add_argument("--shots", required=True)
    ap.add_argument("--ass", required=True); ap.add_argument("--fonts", required=True)
    ap.add_argument("--subject", default=None); ap.add_argument("--out", required=True)
    ap.add_argument("--crf", default="14"); ap.add_argument("--preset", default="medium")
    args = ap.parse_args()
    nframes, fps, dur, _, _ = probe(args.base)
    root = os.path.dirname(os.path.abspath(args.shots))
    shots = [Shot(s, root, fps) for s in json.load(open(args.shots, encoding="utf-8"))["shots"]]
    if not any(s.mode == "split" for s in shots):
        print("  !! nenhum shot 'split' (regra 21: pelo menos uma tela dividida por video)", file=sys.stderr)
    cap_base, cap_split = caption_geometry(args.ass)
    win_top = person_window_top(args.subject) if args.subject else 178
    print("base %d quadros @%g (%.2f s) | legenda ancora %d -> costura %d | janela da pessoa a partir de %d px | shots: %s"
          % (nframes, fps, dur, cap_base, cap_split, win_top, [(s.id, s.mode, round(s.a, 2), round(s.b, 2)) for s in shots]))

    vf = "subtitles=filename='%s':fontsdir='%s'" % (args.ass.replace("'", "\\'"), args.fonts)
    def cap_pipe(color):
        return subprocess.Popen([FF, "-v", "error", "-f", "lavfi", "-i", "color=c=%s:s=%dx%d:r=%g:d=%.3f" % (color, W_, H_, fps, dur),
                                 "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, bufsize=10 ** 8)
    capK, capW = cap_pipe("black"), cap_pipe("white")
    src = subprocess.Popen([FF, "-v", "error", "-i", args.base, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, bufsize=10 ** 8)
    enc = subprocess.Popen([FF, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (W_, H_), "-r", "%g" % fps, "-i", "-",
                            "-i", args.base, "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-crf", args.crf, "-preset", args.preset,
                            "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", args.out], stdin=subprocess.PIPE)
    fsz = W_ * H_ * 3; n = 0
    while True:
        buf = src.stdout.read(fsz)
        if len(buf) < fsz: break
        k = capK.stdout.read(fsz); w = capW.stdout.read(fsz)
        t = n / fps
        base = np.frombuffer(buf, np.uint8).reshape(H_, W_, 3)
        act = [s for s in shots if s.progress(t) > 0]
        shot = max(act, key=lambda s: s.progress(t)) if act else None
        p = shot.progress(t) if shot else 0.0
        cap_mix = 1.0
        if shot is None:
            out = base
        elif shot.mode == "split":
            steps = 10 if p < 1.0 else 1
            acc = np.zeros((H_, W_, 3), np.float32)
            for si in range(steps):
                ts = t + ((si - (steps - 1) / 2.0) / (steps - 1) / fps if steps > 1 else 0.0)
                ps = shot.progress(ts) if steps > 1 else p
                yt = int(round(HT * ps)); ws = int(round(win_top * ps)); hh = H_ - yt
                fr = np.empty((H_, W_, 3), np.uint8); fr[yt:H_] = base[ws:ws + hh]
                if yt > 0: fr[0:yt] = shot.split_region(max(ts, shot.a))[HT - yt:HT]
                acc += fr
            out = (acc / steps).astype(np.uint8)
            if t < shot.a + shot.rin: cap_mix = 1.0 - clamp((t - shot.a) / CAP_XFADE, 0, 1)
            elif t > shot.b - shot.rout: cap_mix = clamp((t - (shot.b - shot.rout)) / CAP_XFADE, 0, 1)
            else: cap_mix = 0.0
        else:
            full = shot.full_frame(t, base)
            out = zoom_blur_mix(base, full, p) if p < 1.0 else full
        if k and w and len(k) == fsz and len(w) == fsz:
            K = np.frombuffer(k, np.uint8).reshape(H_, W_, 3).astype(np.float32)
            Wt = np.frombuffer(w, np.uint8).reshape(H_, W_, 3).astype(np.float32)
            alpha = np.clip(1.0 - (Wt - K).mean(2) / 255.0, 0, 1)
            if alpha.max() > 0.01:
                outf = out.astype(np.float32)
                def paint(dy, gain):
                    nonlocal outf
                    if gain <= 0.001: return
                    if dy == 0: K2, A2 = K, alpha
                    else:
                        K2 = np.zeros_like(K); A2 = np.zeros_like(alpha)
                        if dy < 0: K2[:H_ + dy] = K[-dy:]; A2[:H_ + dy] = alpha[-dy:]
                        else: K2[dy:] = K[:H_ - dy]; A2[dy:] = alpha[:H_ - dy]
                    outf = K2 * gain + outf * (1.0 - A2 * gain)[..., None]
                paint(0, cap_mix)
                paint(cap_split - cap_base, 1.0 - cap_mix)
                out = np.clip(outf, 0, 255).astype(np.uint8)
        enc.stdin.write(np.ascontiguousarray(out).tobytes()); n += 1
        if n % 480 == 0: print("  %d quadros (%.1f s)" % (n, t), flush=True)
    enc.stdin.close(); enc.wait(); src.kill(); capK.kill(); capW.kill()
    print("pronto: %s (%d quadros)" % (args.out, n))


if __name__ == "__main__":
    main()
