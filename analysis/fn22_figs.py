#!/usr/bin/env python3
"""Figures and tables for ODL Field Note #22 from the outputs of fn22_flash_sync.py.
usage: python3 fn22_figs.py <out_dir> <records_dir> <fig_dir> <table_dir>"""
import os, sys, json, csv, subprocess
import numpy as np, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

out, rec_dir, fig_dir, tab_dir = sys.argv[1:5]
os.makedirs(fig_dir, exist_ok=True); os.makedirs(tab_dir, exist_ok=True)
plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False, 'figure.dpi': 150})
CL, CR, C1, C2 = '#2563eb', '#ea580c', '#0f766e', '#7c3aed'
R = {k: json.load(open(f'{out}/{k}_result.json')) for k in ('rec1', 'rec2')}
Z = {k: np.load(f'{out}/{k}_series.npz') for k in ('rec1', 'rec2')}
NAME = {'rec1': 'Recording 1 (exposure steady, 10.04 ms)', 'rec2': 'Recording 2 (auto-exposure active, L 0.5 ms shorter)'}

# ---------- tables
def wcsv(name, rows):
    with open(os.path.join(tab_dir, name), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
summ = []
for k in R:
    s = dict(R[k]['summary']); s['exposure_left_range_us'] = '-'.join(map(str, s['exposure_left_range_us']))
    g1 = [g for g in R[k]['gamma'] if g['gamma'] == 1.0][0]
    s.update(optical_dt_symmetric_us_gamma1=g1['symmetric_us'], optical_ci95_us_gamma1=f"{g1['ci95_low_us']} to {g1['ci95_high_us']}",
             optical_dt_range_over_gamma_us=f"{min(g['symmetric_us'] for g in R[k]['gamma'])} to {max(g['symmetric_us'] for g in R[k]['gamma'])}",
             edges_used_gamma1=g1['edges'])
    summ.append(s)
wcsv('summary.csv', summ)
wcsv('gamma_sensitivity.csv', R['rec1']['gamma'] + R['rec2']['gamma'])
wcsv('row_bands.csv', R['rec1']['bands'] + R['rec2']['bands'])
wcsv('edges_gamma1.csv', R['rec1']['edges'] + R['rec2']['edges'])

# ---------- 1. setup frame with ROI
seg = R['rec1']['summary']['segment']; imgs = []
for eye in ('left', 'right'):
    p = subprocess.run(['ffmpeg', '-v', 'error', '-ss', '30', '-i', os.path.join(rec_dir, f'{seg}_{eye}_raw.mp4'), '-frames:v', '1',
                        '-vf', 'scale=800:600', '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1'], capture_output=True)
    imgs.append(np.frombuffer(p.stdout, np.uint8).reshape(600, 800, 3))
fig, ax = plt.subplots(1, 2, figsize=(10, 4.1))
for a, im, eye, c in zip(ax, imgs, ('left', 'right'), (CL, CR)):
    m = Z['rec1'][f'roi_{eye}']; ys, xs = np.nonzero(m); s = 800 / 160
    a.imshow(im); a.add_patch(Rectangle((xs.min() * s, ys.min() * s), (xs.max() - xs.min() + 1) * s, (ys.max() - ys.min() + 1) * s, fill=False, lw=2, ec=c))
    a.set_title(f'{eye.capitalize()} eye — flash panel region ({m.sum()} px at 160×120)', fontsize=9); a.axis('off')
fig.tight_layout(); fig.savefig(f'{fig_dir}/fn22_setup.png'); plt.close(fig)

# ---------- 2. method schematic
fig, ax = plt.subplots(figsize=(9, 2.9))
ax.axvspan(0, 40, color='#f1f5f9'); ax.axvspan(13.4, 40, color='#fde68a', alpha=.6)
ax.text(5, 2.75, 'panel black', fontsize=9); ax.text(26, 2.75, 'panel white', fontsize=9, ha='center')
for y, c, lab, st, ex in ((1.8, CL, 'left exposure', 8.0, 10.0), (0.8, CR, 'right exposure', 8.014, 10.0)):
    ax.add_patch(Rectangle((st, y - .25), ex, .5, color=c, alpha=.85)); ax.text(st - .5, y, lab, ha='right', va='center', fontsize=9)
ax.axvline(13.4, color='k', ls='--', lw=1); ax.text(13.6, 0.15, 'switch', fontsize=9)
ax.annotate('', xy=(18, 2.2), xytext=(13.4, 2.2), arrowprops=dict(arrowstyle='<->'))
ax.text(15.7, 2.32, 'f × exposure', ha='center', fontsize=9)
ax.text(28, 1.4, 'rise:  t = start + exposure·(1−f)\nfall:   t = start + exposure·f\nf = share of the exposure that saw white\n(from brightness vs. neighbouring full frames)', fontsize=9, va='center')
ax.set_xlim(-6, 40); ax.set_ylim(0, 3.1); ax.set_yticks([]); ax.set_xlabel('time (ms)')
ax.spines['left'].set_visible(False); fig.tight_layout(); fig.savefig(f'{fig_dir}/fn22_method.png'); plt.close(fig)

# ---------- 3. time series window
z = Z['rec1']; sl, sr = z['sei_left'], z['sei_right']; t0 = sl[0, 1]
i0 = int(np.flatnonzero(np.abs(np.diff(z['left'])) > 30)[40]); idx = np.arange(i0 - 5, i0 + 55)
def norm(r):
    lo, hi = np.percentile(r, 5), np.percentile(r, 95); return (r - lo) / (hi - lo)
fig, ax = plt.subplots(figsize=(10, 3.2))
for r, s, c, lab, off in ((z['left'], sl, CL, 'left', 0), (z['right'], sr, CR, 'right', 0)):
    mid = (s[idx, 1] + s[idx, 2] / 2 - t0) / 1000
    ax.plot(mid, norm(r)[idx], 'o-', ms=3.5, lw=1, color=c, label=f'{lab} eye (panel brightness)')
for i in idx:
    ax.add_patch(Rectangle(((sl[i, 1] - t0) / 1000, -0.17), sl[i, 2] / 1000, 0.06, color=CL, alpha=.6, lw=0))
ax.text((sl[idx[0], 1] - t0) / 1000, -0.27, 'left exposure windows', fontsize=8, color=CL)
ax.set_ylim(-0.32, 1.25); ax.set_xlabel('time since recording start (ms, exposure midpoint)'); ax.set_ylabel('normalised brightness')
ax.legend(frameon=False, loc='upper right', fontsize=8, ncol=2)
ax.set_title('Two seconds of Recording 1: intermediate values are frames whose exposure straddled a switch', fontsize=9)
fig.tight_layout(); fig.savefig(f'{fig_dir}/fn22_timeseries.png'); plt.close(fig)

# ---------- 4. per-edge dt distribution (gamma 1)
fig, ax = plt.subplots(1, 2, figsize=(10, 3.3), sharey=True)
bins = np.arange(-1000, 1001, 40)
for a, k in zip(ax, ('rec1', 'rec2')):
    E = R[k]['edges']; g1 = [g for g in R[k]['gamma'] if g['gamma'] == 1.0][0]
    for typ, c in (('rise', C1), ('fall', C2)):
        d = np.clip([e['dt_us'] for e in E if e['edge'] == typ], -999, 999)
        a.hist(d, bins=bins, alpha=.6, color=c, label=f'{typ} (n={len(d)}, median {np.median([e["dt_us"] for e in E if e["edge"]==typ]):.0f} µs)')
    a.axvline(g1['symmetric_us'], color='k', lw=1.2); a.axvline(R[k]['summary']['sei_start_diff_median_us'], color='#dc2626', ls=':', lw=1.5)
    a.set_title(f"{NAME[k]}: symmetric {g1['symmetric_us']:.0f} µs", fontsize=9); a.set_xlabel('left − right switch time per edge (µs)')
    a.legend(frameon=False, fontsize=8)
ax[0].set_ylabel('edges'); ax[1].text(0.98, 0.55, 'black: rise/fall mean\nred dotted: SEI exposure-start diff.', transform=ax[1].transAxes, ha='right', fontsize=8)
fig.tight_layout(); fig.savefig(f'{fig_dir}/fn22_dt_distribution.png'); plt.close(fig)

# ---------- 5. gamma sensitivity
fig, ax = plt.subplots(figsize=(7.5, 3.4))
for k, c, dx in (('rec1', C1, -0.02), ('rec2', C2, 0.02)):
    G = R[k]['gamma']; g = np.array([x['gamma'] for x in G]) + dx; y = np.array([x['symmetric_us'] for x in G])
    lo = y - np.array([x['ci95_low_us'] for x in G]); hi = np.array([x['ci95_high_us'] for x in G]) - y
    ax.errorbar(g, y, yerr=[lo, hi], fmt='o-', color=c, capsize=3, label=NAME[k])
ax.axhline(-14, color='#dc2626', ls=':', label='SEI exposure-start difference (−14 µs)'); ax.axhline(0, color='#94a3b8', lw=.8)
ax.axhspan(-150, 150, color='#e2e8f0', alpha=.5, zorder=0)
ax.set_xlabel('assumed sensor response (gamma)'); ax.set_ylabel('optical left − right (µs)')
ax.set_ylim(-400, 200); ax.legend(frameon=False, fontsize=8, loc='lower left')
ax.set_title('Optical estimate stays within ±150 µs (grey) whatever response curve is assumed', fontsize=9)
fig.tight_layout(); fig.savefig(f'{fig_dir}/fn22_gamma_sensitivity.png'); plt.close(fig)
print('ok')
