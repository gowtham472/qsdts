"""Deck figures, drawn from results/results.json in the Q-Hack template style.

    python experiments/figures.py

Fonts: IBM Plex Sans (the template's typeface). Palette sampled from the
template: pill pink, Quantum Week purple, mascot indigo, on the template grey.
Purple means secure, red means attacked, so brand pink never reads as danger.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"
# IBM Plex Sans is the presentation typeface. Put its TTFs in deck/fonts/ (or point
# PLEX_DIR at them); without them the charts fall back to the default font.
FONT_DIR = Path(os.environ.get("PLEX_DIR", ROOT / "deck" / "fonts"))

PINK, PURPLE, INDIGO = "#FA7CB5", "#8041F9", "#32145E"
RED, GREY, INK, BG = "#E5484D", "#9A9A9A", "#111111", "#E0E0E0"
CARD = "#F4F4F4"
NL = chr(10)  # newline inside labels

_PLEX = list(FONT_DIR.glob("IBMPlex*.ttf"))
for f in _PLEX:
    font_manager.fontManager.addfont(str(f))
if not _PLEX:
    print(f"note: no IBM Plex fonts in {FONT_DIR}; using the default font")
plt.rcParams.update({
    "font.family": "IBM Plex Sans" if _PLEX else "sans-serif",
    "font.size": 15,
    "axes.edgecolor": "#555555",
    "axes.labelcolor": INK,
    "xtick.color": INK,
    "ytick.color": INK,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "savefig.transparent": True,
    "savefig.dpi": 220,
})


def save(fig, name):
    fig.savefig(RES / name, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    print("wrote", name)


# ----------------------------------------------------------------------------- charts
def chart_qber(res):
    rows = res["e2_detection"]["rows"]
    x = [100 * r["eve"] for r in rows]
    y = [100 * r["mean"] for r in rows]
    e = [100 * r["std"] for r in rows]
    base = 100 * res["e2_detection"]["noise"] / 2

    fig, ax = plt.subplots(figsize=(8.2, 4.6))
    bands = [(0, 5, "#FFFFFF", "CONTINUE"), (5, 8, "#FDE3EF", "HARDEN"),
             (8, 11, "#FBC2DC", "REROUTE"), (11, 32, "#F7A0C6", "ABORT")]
    for lo, hi, c, lab in bands:
        ax.axhspan(lo, hi, color=c, alpha=0.85, lw=0, zorder=0)
        ax.text(105.5, (lo + min(hi, 31)) / 2, lab, va="center", ha="left",
                fontsize=11, color=INDIGO, fontweight="semibold")
    xs = [0, 104]
    ax.plot(xs, [base, base + 26], ls="--", color=INDIGO, lw=1.6,
            label="theory: 25% x attack fraction + fibre noise", zorder=2)
    ax.errorbar(x, y, yerr=e, fmt="o", color=PURPLE, ms=8, capsize=4, lw=1.6,
                label="measured on Qiskit Aer (30 sessions per point)", zorder=3)
    ax.set_xlim(-3, 104)
    ax.set_ylim(0, 31)
    ax.set_xlabel("Qubits intercepted by the eavesdropper (%)")
    ax.set_ylabel("Measured QBER (%)")
    ax.legend(loc="upper left", frameon=False, fontsize=12)
    save(fig, "chart_qber_attack.png")


def chart_detection(res):
    rows = res["e2_detection"]["rows"]
    x = [f"{int(100 * r['eve'])}%" for r in rows]
    y = [100 * r["detect_rate"] for r in rows]
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    bars = ax.bar(x, y, color=[GREY if v < 50 else PURPLE for v in y], width=0.62)
    for b, v in zip(bars, y, strict=True):
        ax.text(b.get_x() + b.get_width() / 2, v + 2, f"{v:.0f}%", ha="center",
                fontsize=12, color=INK)
    ax.set_ylim(0, 112)
    ax.set_ylabel("Blocks stopped before encoding (%)")
    ax.set_xlabel("Qubits intercepted by the eavesdropper")
    save(fig, "chart_detection.png")


def chart_efficiency(res):
    r = res["e1_efficiency"]
    groups = ["Message bits per\nqubit prepared", "Message bits per\nfibre transmission"]
    dl = [r["dl04_per_qubit"], r["dl04_per_channel_use"]]
    bb = [r["bb84_per_qubit"], r["bb84_per_channel_use"]]
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    import numpy as np

    idx = np.arange(2)
    w = 0.34
    b1 = ax.bar(idx - w / 2, dl, w, color=PURPLE, label="DL04 QSDC (ours)")
    b2 = ax.bar(idx + w / 2, bb, w, color=GREY, label="BB84 + one-time pad")
    for bars in (b1, b2):
        for b in bars:
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.012,
                    f"{b.get_height():.2f}", ha="center", fontsize=13)
    ax.set_xticks(idx, groups)
    ax.set_ylim(0, 0.82)
    ax.set_yticks([0, 0.2, 0.4, 0.6, 0.8])
    ax.legend(frameon=False, loc="upper right", fontsize=12)
    save(fig, "chart_efficiency.png")


# ----------------------------------------------------------------------------- diagrams
POS = {"Alice": (0.0, 0.5), "R1": (1.6, 1.15), "R2": (1.3, -0.35),
       "R3": (2.75, 0.35), "Bob": (4.2, 0.8)}
EDGES = [("Alice", "R1", 10), ("R1", "Bob", 10), ("Alice", "R2", 12),
         ("R2", "R3", 12), ("R1", "R3", 8), ("R3", "Bob", 10)]


def _node(ax, name, color=INDIGO):
    x, y = POS[name]
    ax.add_patch(plt.Circle((x, y), 0.27, color=color, zorder=5))
    ax.text(x, y, name, ha="center", va="center", color="white", fontsize=14,
            fontweight="semibold", zorder=6)


def _edge(ax, a, b, color=GREY, lw=2.0, ls="-", z=1):
    (x1, y1), (x2, y2) = POS[a], POS[b]
    ax.plot([x1, x2], [y1, y2], color=color, lw=lw, ls=ls, zorder=z, solid_capstyle="round")


def _route(ax, path, color, lw=6.5, alpha=1.0, z=3):
    for a, b in zip(path, path[1:], strict=False):
        (x1, y1), (x2, y2) = POS[a], POS[b]
        ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=22,
                                     color=color, lw=lw, alpha=alpha, zorder=z,
                                     shrinkA=24, shrinkB=24))


def diagram_network(res):
    fig, ax = plt.subplots(figsize=(9.4, 4.6))
    for a, b, km in EDGES:
        _edge(ax, a, b)
        (x1, y1), (x2, y2) = POS[a], POS[b]
        if (a, b) != ("R1", "Bob"):
            ax.text((x1 + x2) / 2, (y1 + y2) / 2 - 0.13, f"{km} km", ha="center",
                    fontsize=10, color="#666666")
    _route(ax, ["Alice", "R1", "Bob"], PURPLE, alpha=0.28, lw=5)
    _route(ax, ["Alice", "R1", "R3", "Bob"], PURPLE)
    # tapped link
    (x1, y1), (x2, y2) = POS["R1"], POS["Bob"]
    ax.plot([x1, x2], [y1, y2], color=RED, lw=4, ls=(0, (3, 2)), zorder=4)
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    # Badge sits above the tapped link; the measurement note sits above the badge,
    # clear of R3 and of the rerouted path below the link.
    ax.add_patch(FancyBboxPatch((mx - 0.45, my + 0.16), 0.9, 0.36,
                                boxstyle="round,pad=0.02,rounding_size=0.15",
                                fc=RED, ec="none", zorder=6))
    ax.text(mx, my + 0.34, "Eve taps", ha="center", va="center", color="white",
            fontsize=12, fontweight="semibold", zorder=7)
    q = next(e["qber"] for e in res["showcase"]["events"] if e["kind"] == "abort")
    ax.text(mx, my + 0.62, f"QBER {100 * q:.1f}% > 8%: message never encoded",
            ha="center", va="bottom", color=RED, fontsize=11.5, zorder=7)
    ax.text(3.5, -0.05, "rerouted", ha="center", fontsize=11, color=PURPLE,
            fontweight="semibold", rotation=20)
    for n in POS:
        _node(ax, n)
    ax.set_xlim(-0.45, 4.65)
    ax.set_ylim(-0.75, 2.0)
    ax.set_aspect("equal")
    ax.axis("off")
    save(fig, "diagram_network.png")


def _box(ax, x, y, w, h, text, fc, tc="white", fs=13, weight="semibold", r=0.12):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}",
                                fc=fc, ec="none", zorder=3))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", color=tc,
            fontsize=fs, fontweight=weight, zorder=4, linespacing=1.25)


def _arrow(ax, a, b, color=INDIGO, lw=2.0, style="-|>"):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle=style, mutation_scale=18, color=color,
                                 lw=lw, zorder=2))


def diagram_dl04():
    """Four phases across two lanes (Bob, Alice), with the abort branch."""
    fig, ax = plt.subplots(figsize=(13.6, 4.9))
    lane_b, lane_a = 2.9, 0.4
    for y, name in ((lane_b, "Bob" + NL + "(receiver)"), (lane_a, "Alice" + NL + "(sender)")):
        ax.text(-0.25, y + 0.42, name, ha="right", va="center", fontsize=14,
                fontweight="semibold", color=INDIGO)
        ax.plot([0, 14.2], [y + 0.42, y + 0.42], color="#BDBDBD", lw=1, zorder=0)

    _box(ax, 0.0, lane_b, 3.1, 0.84, "1  PREPARE" + NL + "random |0>, |1>, |+>, |->", INDIGO, fs=12)
    _arrow(ax, (1.6, lane_b), (3.6, lane_a + 0.84))
    ax.text(2.35, 2.05, "qubits", fontsize=11, color="#555555", rotation=-37)

    _box(ax, 3.0, lane_a, 3.1, 0.84, "2  CHECK" + NL + "measure random subset", PURPLE, fs=12)
    _arrow(ax, (6.1, lane_a + 0.42), (6.65, lane_a + 0.42))
    cx, cy = 7.45, lane_a + 0.42
    ax.add_patch(plt.Polygon([(cx - 0.8, cy), (cx, cy + 0.62), (cx + 0.8, cy), (cx, cy - 0.62)],
                             fc="white", ec=INDIGO, lw=2, zorder=3))
    ax.text(cx, cy, "QBER" + NL + "< 8% ?", ha="center", va="center", fontsize=11.5, color=INK, zorder=4)
    _arrow(ax, (cx, cy - 0.62), (cx, -0.75), color=RED)
    ax.text(cx + 0.12, cy - 0.95, "no", fontsize=11, color=RED)
    _box(ax, cx - 1.65, -1.55, 3.3, 0.8, "ABORT" + NL + "message never encoded", RED, fs=12)
    _arrow(ax, (cx + 0.8, cy), (8.85, cy))
    ax.text(cx + 0.88, cy + 0.12, "yes", fontsize=11, color=PURPLE)
    _box(ax, 8.85, lane_a, 2.6, 0.84, "3  ENCODE" + NL + "0 → I     1 → iY", PINK, tc=INK, fs=12)
    _arrow(ax, (10.15, lane_a + 0.84), (11.6, lane_b))
    ax.text(10.35, 2.15, "same qubits" + NL + "sent back", fontsize=11, color="#555555",
            ha="right")
    _box(ax, 11.1, lane_b, 3.1, 0.84, "4  DECODE" + NL + "measure in own basis", INDIGO, fs=12)

    ax.text(7.1, 4.2, "No key is generated, stored or transmitted at any point.",
            ha="center", fontsize=13.5, color=INK, style="italic")
    ax.set_xlim(-1.9, 14.4)
    ax.set_ylim(-1.7, 4.5)
    ax.axis("off")
    save(fig, "diagram_dl04.png")


def diagram_architecture():
    layers = [
        ("4  APPLICATION", "file transfer   ·   SHA-256 verification   ·   event log", PINK, INK),
        ("3  SECURITY CONTROLLER", "QBER monitor   ·   CONTINUE / HARDEN / REROUTE / ABORT", PURPLE, "white"),
        ("2  NETWORK", "nodes   ·   trusted relays   ·   QBER-weighted routing (NetworkX)", PURPLE, "white"),
        ("1  PROTOCOL", "DL04 QSDC   ·   BB84 baseline   ·   Hamming(7,4) + CRC-32", INDIGO, "white"),
        ("0  QUANTUM CORE", "Qiskit Aer circuits   ·   fibre noise   ·   Eve as measurement", INDIGO, "white"),
    ]
    fig, ax = plt.subplots(figsize=(9.6, 5.2))
    h, gap = 0.82, 0.16
    for i, (title, sub, fc, tc) in enumerate(layers):
        y = (len(layers) - 1 - i) * (h + gap)
        ax.add_patch(FancyBboxPatch((0, y), 10, h, boxstyle="round,pad=0,rounding_size=0.18",
                                    fc=fc, ec="none"))
        ax.text(0.35, y + h * 0.64, title, va="center", fontsize=14.5, fontweight="semibold",
                color=tc)
        ax.text(0.35, y + h * 0.27, sub, va="center", fontsize=12, color=tc)
    step = h + gap
    ax.plot([10.2, 10.2], [2 * step + 0.05, 5 * step - gap - 0.05], color="#777777", lw=1.5)
    ax.plot([10.2, 10.2], [0.05, 2 * step - gap - 0.05], color=INDIGO, lw=2.5)
    ax.text(10.35, 3.5 * step - gap / 2, "classical", rotation=90, va="center",
            fontsize=12, color="#555555")
    ax.text(10.35, 1.0 * step - gap / 2, "quantum", rotation=90, va="center",
            fontsize=12, color=INDIGO, fontweight="semibold")
    ax.set_xlim(-0.05, 10.6)
    ax.set_ylim(-0.05, len(layers) * (h + gap))
    ax.axis("off")
    save(fig, "diagram_architecture.png")


def diagram_circuit():
    """The real circuit one DL04 payload qubit goes through, from qsdts/dl04.py."""
    from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister

    q = QuantumRegister(2, "q")
    c = ClassicalRegister(2, "c")
    qc = QuantumCircuit(q, c)
    # Bob prepares: check lane |->, payload lane |+>
    qc.x(0)
    qc.h(0)
    qc.h(1)
    qc.barrier(label="prepare")
    qc.id(0)
    qc.id(1)
    qc.barrier(label="fibre")
    qc.h(0)
    qc.measure(0, 0)
    qc.barrier(label="check")
    qc.y(1)
    qc.barrier(label="encode")
    qc.id(1)
    qc.barrier(label="fibre")
    qc.h(1)
    qc.measure(1, 1)
    style = {
        "fontsize": 15, "subfontsize": 11,
        "displaycolor": {
            "h": [PURPLE, "#FFFFFF"], "x": [INDIGO, "#FFFFFF"], "y": [PINK, INK],
            "id": ["#BDBDBD", INK], "measure": [INDIGO, "#FFFFFF"],
        },
        "backgroundcolor": "#FFFFFF", "barrierfacecolor": "#EDEDED",
        "linecolor": INK, "textcolor": INK, "gatetextcolor": INK, "creglinecolor": "#777777",
    }
    fig = qc.draw("mpl", style=style, fold=-1, plot_barriers=True,
                  initial_state=True, cregbundle=True)

    save(fig, "diagram_circuit.png")


def main():
    res = json.loads((RES / "results.json").read_text())
    chart_qber(res)
    chart_detection(res)
    chart_efficiency(res)
    diagram_network(res)
    diagram_dl04()
    diagram_architecture()
    diagram_circuit()


if __name__ == "__main__":
    sys.exit(main())
