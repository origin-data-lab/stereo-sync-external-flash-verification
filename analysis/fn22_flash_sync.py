#!/usr/bin/env python3
# NOTE: device-specific readers in this file are withheld (see CODE_AVAILABILITY.md).
"""ODL Field Note #22 - left/right camera synchronisation checked with an external flash.

A PC monitor shows a page that switches a panel between black and white at random 70-250 ms
intervals. Both eyes of the stereo rig film it. For every frame we know, from the H.264 SEI,
the exposure start (us) and exposure duration (us). A frame whose exposure window straddles a
switch records a partial brightness; the fraction f of the exposure that saw "white" places the
switch inside that window:

    rise  (black -> white):  t_switch = exposure_start + exposure * (1 - f)
    fall  (white -> black):  t_switch = exposure_start + exposure * f

Each eye estimates the same physical switch from its own timestamps. If the rig is synchronised and
its timestamps are honest, t_left - t_right ~ 0. A photometric bias (gain/gamma mismatch between eyes)
moves rise and fall estimates in opposite directions, so we report the mean of the rise median and the
fall median ("symmetric estimate") and give the spread over several assumed response curves (gamma).

usage:
  python3 fn22_flash_sync.py extract <records_dir> <segment> <cache_dir>      # SEI + 160x120 gray, both eyes
  python3 fn22_flash_sync.py analyse <cache_dir> <segment> <label> <out_dir> [gamma ...]
"""
import os, re, sys, json, struct, subprocess
import numpy as np
from scipy import ndimage as ndi

W, H, BANDS = 160, 120, 5


def sei_rows(vid):
    """Per-frame SEI of the R8 stream: svh_pts, exposure_start_us, exposure_us, strobe_seq, flags."""
    raise NotImplementedError('Origin Data Lab device-specific reader withheld; results are in assets/tables. Contact founder@origindatalab.io')


def gray(vid):
    p = subprocess.run(['ffmpeg', '-v', 'error', '-i', vid, '-vf', f'scale={W}:{H}:flags=area,format=gray',
                        '-f', 'rawvideo', '-vsync', 'passthrough', 'pipe:1'], capture_output=True)
    f = np.frombuffer(p.stdout, np.uint8); n = len(f) // (W * H)
    return f[:n * W * H].reshape(n, H, W)


def extract(rec_dir, seg, cache):
    os.makedirs(cache, exist_ok=True)
    for eye in ('left', 'right'):
        v = os.path.join(rec_dir, f'{seg}_{eye}_raw.mp4')
        np.savez_compressed(os.path.join(cache, f'{seg}_{eye}.npz'), sei=sei_rows(v), img=gray(v))


def pair_by_exposure_start(sl, sr, tol_us=2000):
    """Nearest exposure start (not PTS, not strobe counter - see Field Note #18)."""
    j = np.clip(np.searchsorted(sr[:, 1], sl[:, 1]), 1, len(sr) - 1)
    jj = np.where(np.abs(sr[j, 1] - sl[:, 1]) < np.abs(sr[j - 1, 1] - sl[:, 1]), j, j - 1)
    ok = np.abs(sl[:, 1] - sr[jj, 1]) < tol_us
    return np.flatnonzero(ok), jj[ok]


def flash_roi(g):
    """Pixels that toggle most often = the flashing panel (largest connected blob, eroded)."""
    act = (np.abs(np.diff(g, axis=0)) > 25).mean(0)
    m = act > 0.5 * act.max()
    lab, k = ndi.label(m); sz = ndi.sum(m, lab, range(1, k + 1))
    m = lab == (1 + int(np.argmax(sz)))
    return ndi.binary_erosion(m, iterations=2)


def partial_edges(r, s, gamma):
    """Frames that straddle a switch, with full 'off' and 'on' frames on both sides (2 each)."""
    lin = lambda v: (np.clip(v, 0, 255) / 255.) ** gamma
    e = s[:, 2].astype(float); n = len(r)
    lo, hi = np.percentile(r, 5), np.percentile(r, 95); on = r > (lo + hi) / 2
    out = {}
    for i in range(2, n - 2):
        for typ in ('rise', 'fall'):
            a, b = (~on, on) if typ == 'rise' else (on, ~on)
            if not (a[i - 2] and a[i - 1] and b[i + 1] and b[i + 2]):
                continue
            if typ == 'rise':
                off, onv, eo, e1 = r[i - 1], r[i + 1], e[i - 1], e[i + 1]
            else:
                off, onv, eo, e1 = r[i + 1], r[i - 1], e[i + 1], e[i - 1]
            if onv - off < 0.3 * (hi - lo):
                continue
            # linear light is proportional to exposure: rescale neighbours to this frame's exposure
            l_off = lin(off) / eo * e[i]; l_on = lin(onv) / e1 * e[i]
            f = float((lin(r[i]) - l_off) / (l_on - l_off))
            t = s[i, 1] + s[i, 2] * (1 - f) if typ == 'rise' else s[i, 1] + s[i, 2] * f
            out[(typ, i)] = (f, float(t))
    return out, on


def analyse(cache, seg, label, out_dir, gammas):
    os.makedirs(out_dir, exist_ok=True)
    D = {e: np.load(os.path.join(cache, f'{seg}_{e}.npz')) for e in ('left', 'right')}
    il, ir = pair_by_exposure_start(D['left']['sei'], D['right']['sei'])
    S = {'left': D['left']['sei'][il], 'right': D['right']['sei'][ir]}
    G = {'left': D['left']['img'][il].astype(np.float32), 'right': D['right']['img'][ir].astype(np.float32)}
    roi, series, bands = {}, {}, {}
    for e in G:
        m = flash_roi(G[e]); roi[e] = m; series[e] = G[e][:, m].mean(1)
        ys = np.nonzero(m)[0]; cut = np.linspace(ys.min(), ys.max() + 1, BANDS + 1); yy = np.arange(H)[:, None]
        bands[e] = [G[e][:, m & (yy >= cut[k]) & (yy < cut[k + 1])].mean(1) for k in range(BANDS)]
    sl, sr = S['left'], S['right']
    summary = dict(recording=label, segment=seg, frames_left=int(len(D['left']['sei'])),
                   frames_right=int(len(D['right']['sei'])), pairs=int(len(il)),
                   sei_start_diff_median_us=float(np.median(sl[:, 1] - sr[:, 1])),
                   sei_start_diff_p99_abs_us=float(np.percentile(np.abs(sl[:, 1] - sr[:, 1]), 99)),
                   sei_start_diff_max_abs_us=int(np.abs(sl[:, 1] - sr[:, 1]).max()),
                   exposure_left_median_us=float(np.median(sl[:, 2])), exposure_right_median_us=float(np.median(sr[:, 2])),
                   exposure_left_range_us=[int(sl[:, 2].min()), int(sl[:, 2].max())],
                   exposure_diff_median_us=float(np.median(sl[:, 2] - sr[:, 2])),
                   pts_equal_fraction=float((sl[:, 0] == sr[:, 0]).mean()),
                   pts_diff_max_abs_us=int(np.abs(sl[:, 0] - sr[:, 0]).max()),
                   roi_left_px=int(roi['left'].sum()), roi_right_px=int(roi['right'].sum()))
    _, onL = partial_edges(series['left'], sl, 1.0); _, onR = partial_edges(series['right'], sr, 1.0)
    act = np.flatnonzero(np.diff(onL.astype(int)) != 0); a0, a1 = act.min(), act.max() + 1
    summary['flash_window_s'] = round(float((sl[a1, 1] - sl[a0, 1]) / 1e6), 1)
    summary['flashes_detected'] = int((np.diff(onL.astype(int)) == 1).sum())
    summary['state_disagree_frames'] = int((onL[a0:a1 + 1] != onR[a0:a1 + 1]).sum())
    summary['state_frames_in_window'] = int(a1 - a0 + 1)
    rng = np.random.default_rng(0); gam_rows, edge_rows, band_rows = [], [], []
    for g in gammas:
        for key in ['all'] + [f'band{k}' for k in range(BANDS)]:
            rL = series['left'] if key == 'all' else bands['left'][int(key[-1])]
            rR = series['right'] if key == 'all' else bands['right'][int(key[-1])]
            eL, _ = partial_edges(rL, sl, g); eR, _ = partial_edges(rR, sr, g)
            rows = []
            for k in sorted(set(eL) & set(eR), key=lambda x: x[1]):
                fL, tL = eL[k]; fR, tR = eR[k]
                if 0.05 < fL < 0.95 and 0.05 < fR < 0.95:
                    rows.append((k[0], k[1], fL, fR, tL, tR, tL - tR))
            R_ = np.array([x[6] for x in rows if x[0] == 'rise']); F_ = np.array([x[6] for x in rows if x[0] == 'fall'])
            sym = (np.median(R_) + np.median(F_)) / 2
            bs = [(np.median(rng.choice(R_, len(R_))) + np.median(rng.choice(F_, len(F_)))) / 2 for _ in range(2000)]
            d = np.array([x[6] for x in rows])
            row = dict(recording=label, gamma=g, region=key, edges=len(rows), rises=len(R_), falls=len(F_),
                       rise_median_us=round(float(np.median(R_)), 1), fall_median_us=round(float(np.median(F_)), 1),
                       symmetric_us=round(float(sym), 1), ci95_low_us=round(float(np.percentile(bs, 2.5)), 1),
                       ci95_high_us=round(float(np.percentile(bs, 97.5)), 1),
                       mad_us=round(float(np.median(np.abs(d - np.median(d)))), 1),
                       p95_abs_us=round(float(np.percentile(np.abs(d), 95)), 1))
            (gam_rows if key == 'all' else band_rows).append(row)
            if key == 'all' and g == 1.0:
                for x in rows:
                    edge_rows.append(dict(recording=label, edge=x[0], frame=int(x[1]), f_left=round(x[2], 4), f_right=round(x[3], 4),
                                          exposure_left_us=int(sl[x[1], 2]), exposure_right_us=int(sr[x[1], 2]),
                                          t_left_us=round(x[4] - sl[0, 1], 1), t_right_us=round(x[5] - sl[0, 1], 1),
                                          dt_us=round(x[6], 1)))
    np.savez_compressed(os.path.join(out_dir, f'{label}_series.npz'), left=series['left'], right=series['right'],
                        sei_left=sl, sei_right=sr, roi_left=roi['left'], roi_right=roi['right'],
                        frame_left=G['left'][len(il) // 2].astype(np.uint8), frame_right=G['right'][len(il) // 2].astype(np.uint8))
    json.dump(dict(summary=summary, gamma=gam_rows, bands=band_rows, edges=edge_rows),
              open(os.path.join(out_dir, f'{label}_result.json'), 'w'), indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == '__main__':
    if sys.argv[1] == 'extract':
        extract(*sys.argv[2:5])
    else:
        analyse(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], [float(x) for x in sys.argv[6:]] or [1.0])
