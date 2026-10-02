"""Generate notebooks/qsdts_demo.ipynb (the Colab demo).

    python notebooks/make_notebook.py

Kept as code so the notebook is reviewable in diffs and regenerated, not hand
edited.
"""

from pathlib import Path

import nbformat as nbf

REPO = "https://github.com/gowtham472/qsdts"
COLAB = "https://colab.research.google.com/github/gowtham472/qsdts/blob/main/notebooks/qsdts_demo.ipynb"

md = nbf.v4.new_markdown_cell
code = nbf.v4.new_code_cell

cells = [
    md(f"""# QSDTS: keyless quantum-secure file transfer

[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)]({COLAB})

**Team DoodleByte** · Q-Hack India 2026 · Quantum Security & Cryptography

QSDTS sends a file across a network where **the message itself is the quantum state**
(DL04 Quantum Secure Direct Communication), so no key is ever generated, stored or
transmitted. Every link checks for an eavesdropper *before* the message is encoded,
and the network routes around any link that fails.

Everything below runs on Qiskit Aer in about two minutes. Use **Runtime > Run all**.

Source: {REPO}"""),
    md("## Setup"),
    code(f"""try:
    import qsdts
except ImportError:
    %pip install -q "qsdts @ git+{REPO}"
    import qsdts

import numpy as np
import matplotlib.pyplot as plt
from qsdts import dl04, bb84
from qsdts.channel import Link, QuantumBackend
from qsdts.coding import encode_frame, decode_frame
from qsdts.network import demo_topology
print("qsdts", qsdts.__version__)"""),
    md("""## 1. One DL04 session on a clean fibre

Bob prepares random qubits and sends them. Alice measures a random subset to check
for an eavesdropper. Only if the error rate (QBER) is low does she encode the message
on the remaining qubits (I for 0, iY for 1) and send them back. Bob decodes in his own
bases."""),
    code("""be, rng = QuantumBackend(seed=1), np.random.default_rng(1)
r = dl04.send(encode_frame(b"no key was ever created"), Link("Alice", "Bob", depol=0.0), be, rng)
data, ok = decode_frame(r.payload)
print(f"forward check QBER: {100*r.qber_forward:.1f}%   aborted: {r.aborted}")
print(f"Bob decoded: {data.rstrip(bytes(1))!r}   integrity ok: {ok}")
print(f"qubits prepared: {r.qubits_prepared}")"""),
    md("""## 2. An eavesdropper, and the 25% signature

Eve intercepts every qubit and measures it in a random basis. She picks the wrong basis
half the time, and then the bit reads wrong half the time: 0.5 x 0.5 = **25%**.
Pooled over many sessions, the simulation must reproduce that."""),
    code("""be, rng = QuantumBackend(seed=21), np.random.default_rng(21)
errors = sifted = 0
for _ in range(100):
    r = dl04.send(np.zeros(448, np.uint8), Link("A", "B", depol=0.0, eve=1.0), be, rng,
                  proceed_below=1.01)
    errors += round(r.qber_forward * r.sifted_forward)
    sifted += r.sifted_forward
se = (0.25 * 0.75 / sifted) ** 0.5
q = errors / sifted
print(f"measured QBER: {100*q:.2f}%  over {sifted} check bits")
print(f"theory 25%   standard error {100*se:.2f}%   z = {(q - 0.25)/se:+.2f}  (|z| < 3 is consistent)")"""),
    md("""## 3. The invariant: abort *before* encoding

If the check fails, the message must never touch the channel. Here every message bit
is a 1, so encoding would need Y gates. We count them."""),
    code("""from qiskit import QuantumCircuit
calls = {"y": 0}
_orig = QuantumCircuit.y
def counting_y(self, *a, **k):
    calls["y"] += 1
    return _orig(self, *a, **k)
QuantumCircuit.y = counting_y
try:
    r = dl04.send(np.ones(448, np.uint8), Link("A", "B", depol=0.0, eve=1.0),
                  QuantumBackend(seed=3), np.random.default_rng(3))
finally:
    QuantumCircuit.y = _orig
print(f"aborted: {r.aborted}   QBER: {100*r.qber_forward:.1f}%")
print(f"encoding gates created: {calls['y']}   message bits on channel: {r.message_bits_on_channel}")"""),
    md("""## 4. A file across the network, attacked mid-transfer

Five nodes. Each hop is its own DL04 session through a trusted relay. At frame 5 an
eavesdropper taps the R1-Bob fibre. Watch the network detect it and reroute."""),
    code("""data = (b"QSDTS demo: this file crosses a quantum network while an eavesdropper "
        b"taps a link mid-transfer. The network detects it and routes around. ") * 3

def show(e):
    if e.kind in ("abort", "reroute", "fail"):
        q = "" if e.qber is None else f"QBER {100*e.qber:.1f}%  "
        print(f"frame {e.frame+1:2d}  {e.kind.upper():8s} {e.link:10s} {q}{e.detail}")

rep = demo_topology().transfer(data, "Alice", "Bob", QuantumBackend(seed=5),
                               np.random.default_rng(5), attacks={4: ("R1", "Bob", 1.0)},
                               on_event=show)
print()
for p in rep.paths:
    print("path used:", " > ".join(p))
print("SHA-256 sent    ", rep.sha256_sent)
print("SHA-256 received", rep.sha256_received)
print("verified:", rep.verified, "  message bits exposed on aborted sessions:",
      rep.message_bits_on_aborted_sessions)"""),
    code("""import networkx as nx
net = demo_topology()
pos = {"Alice": (0, .5), "R1": (1.6, 1.15), "R2": (1.3, -.35), "R3": (2.75, .35), "Bob": (4.2, .8)}
fig, ax = plt.subplots(figsize=(8, 3.6))
nx.draw_networkx_edges(net.g, pos, ax=ax, edge_color="#bbbbbb", width=2)
for path, col, w in ((rep.paths[0], "#c9b3fb", 5), (rep.paths[-1], "#8041F9", 6)):
    nx.draw_networkx_edges(net.g, pos, edgelist=list(zip(path, path[1:])), ax=ax,
                           edge_color=col, width=w, arrows=True, arrowsize=18)
nx.draw_networkx_edges(net.g, pos, edgelist=[("R1", "Bob")], ax=ax, edge_color="#E5484D",
                       width=3, style="dashed")
nx.draw_networkx_nodes(net.g, pos, ax=ax, node_color="#32145E", node_size=1300)
nx.draw_networkx_labels(net.g, pos, ax=ax, font_color="white", font_weight="bold")
ax.set_title("light: original path   dark: rerouted path   red dashed: tapped link")
ax.axis("off");"""),
    md("""## 5. How strong must an attack be to be caught?

Sweep the fraction of qubits Eve intercepts, with 1% realistic fibre noise. A block is
stopped when its check exceeds 8% QBER."""),
    code("""fracs = [0.0, 0.2, 0.4, 0.6, 1.0]
means, caught = [], []
for i, f in enumerate(fracs):
    be, rng = QuantumBackend(seed=200+i), np.random.default_rng(200+i)
    qs = [dl04.send(encode_frame(b"y"*28), Link("A","B", depol=0.01, eve=f), be, rng)
          for _ in range(12)]
    means.append(100*np.mean([r.qber_forward for r in qs]))
    caught.append(100*np.mean([r.aborted for r in qs]))
    print(f"attack {int(100*f):3d}%   mean QBER {means[-1]:5.1f}%   blocks stopped {caught[-1]:5.1f}%")
fig, ax = plt.subplots(figsize=(6, 3.4))
ax.plot([100*f for f in fracs], means, "o-", color="#8041F9", label="measured QBER")
ax.plot([0, 100], [0.5, 25.5], "--", color="#32145E", label="theory")
ax.axhline(8, color="#E5484D", lw=1, label="reroute threshold 8%")
ax.set_xlabel("qubits intercepted (%)"); ax.set_ylabel("QBER (%)"); ax.legend();"""),
    md("""**Honest limit:** attacks on half the qubits or more are stopped on every block, but a
weak attacker (about 20%) hides inside fibre noise within a single block. Detecting it
across many blocks is our Round 2 research question.

## 6. DL04 vs BB84 on the same channel"""),
    code("""be, rng = QuantumBackend(seed=11), np.random.default_rng(11)
d = dl04.send(encode_frame(b"x"*28), Link("A","B", depol=0.01), be, rng)
b = bb84.exchange(4000, Link("A","B", depol=0.01), be, rng)
print(f"DL04: {448/d.qubits_prepared:.3f} message bits per qubit prepared, "
      f"{448/d.channel_uses:.3f} per fibre transmission")
print(f"BB84: {len(b.key_alice)/b.qubits_prepared:.3f} key bits per qubit (one per transmission)")
print("DL04 wins per qubit prepared but sends each qubit twice; the real difference is that no key exists.")"""),
]

nb = nbf.v4.new_notebook()
nb["cells"] = cells
nb["metadata"] = {
    "kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
    "language_info": {"name": "python"},
    "colab": {"provenance": [], "name": "qsdts_demo.ipynb"},
}
out = Path(__file__).with_name("qsdts_demo.ipynb")
nbf.write(nb, out)
print("wrote", out)
