"""Every number in the QSDTS deck comes from this script.

    python experiments/run_experiments.py

Writes results/results.json (all measured values) and results/*.png. Seeds are
fixed, so a rerun reproduces the same figures exactly.

E0  Validation   intercept-resend QBER vs the 25% theoretical value
E1  Efficiency   DL04 vs BB84, per qubit prepared and per channel use
E2  Detection    QBER and per-block detection rate vs attack strength
E3  Invariant    message bits exposed by every aborted session (must be 0)
E4  Adaptivity   file transfer under a mid-transfer attack, controller on/off
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from qsdts import bb84, dl04  # noqa: E402
from qsdts.channel import Link, QuantumBackend  # noqa: E402
from qsdts.coding import coded_frame_bits, encode_frame  # noqa: E402
from qsdts.network import Policy, demo_topology  # noqa: E402

OUT = ROOT / "results"
OUT.mkdir(exist_ok=True)
P = coded_frame_bits()  # 448
NOISE = 0.010
EXPOSED: list[int] = []  # message bits on the channel, one entry per aborted session


def pooled_qber(eve: float, sessions: int, seed: int, depol: float = 0.0) -> dict:
    be, rng = QuantumBackend(seed=seed), np.random.default_rng(seed)
    e = s = 0
    for _ in range(sessions):
        r = dl04.send(np.zeros(P, np.uint8), Link("A", "B", depol=depol, eve=eve), be, rng,
                      proceed_below=1.01)
        e += round(r.qber_forward * r.sifted_forward)
        s += r.sifted_forward
    return {"qber": e / s, "bits": s, "se": (max(e / s, 1e-9) * (1 - e / s) / s) ** 0.5}


def e0_validation() -> dict:
    print("E0 validation ...", flush=True)
    dl = pooled_qber(1.0, 200, seed=100)
    be, rng = QuantumBackend(seed=7), np.random.default_rng(7)
    e = s = 0
    for _ in range(20):
        r = bb84.exchange(2000, Link("A", "B", depol=0.0, eve=1.0), be, rng)
        e += round(r.qber * r.n_check)
        s += r.n_check
    clean = pooled_qber(0.0, 40, seed=101)
    noisy = pooled_qber(0.0, 60, seed=102, depol=NOISE)
    return {
        "theory": 0.25,
        "dl04_attack": dl,
        "bb84_attack": {"qber": e / s, "bits": s},
        "dl04_clean": clean,
        "dl04_noise_only": noisy,
        "noise_theory": NOISE / 2,
    }


def e1_efficiency() -> dict:
    print("E1 efficiency ...", flush=True)
    be, rng = QuantumBackend(seed=11), np.random.default_rng(11)
    dl_prep, dl_use = [], []
    for _ in range(20):
        r = dl04.send(encode_frame(b"x" * 28), Link("A", "B", depol=NOISE), be, rng)
        if not r.aborted:
            dl_prep.append(P / r.qubits_prepared)
            dl_use.append(P / r.channel_uses)
    bb = []
    for _ in range(20):
        r = bb84.exchange(4000, Link("A", "B", depol=NOISE), be, rng)
        bb.append(len(r.key_alice) / r.qubits_prepared)
    return {
        "dl04_per_qubit": float(np.mean(dl_prep)),
        "dl04_per_channel_use": float(np.mean(dl_use)),
        "bb84_per_qubit": float(np.mean(bb)),
        "bb84_per_channel_use": float(np.mean(bb)),
        "note": "raw secure payload bits before error correction, which costs both equally",
    }


def e2_detection() -> dict:
    print("E2 detection sweep ...", flush=True)
    fracs = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0]
    rows = []
    for i, f in enumerate(fracs):
        be, rng = QuantumBackend(seed=200 + i), np.random.default_rng(200 + i)
        qs, aborted = [], 0
        for _ in range(30):
            r = dl04.send(encode_frame(b"y" * 28), Link("A", "B", depol=NOISE, eve=f), be, rng,
                          proceed_below=Policy().reroute_at)
            qs.append(r.qber_forward)
            if r.aborted:
                aborted += 1
                EXPOSED.append(r.message_bits_on_channel)
        rows.append({"eve": f, "mean": float(np.mean(qs)), "std": float(np.std(qs)),
                     "detect_rate": aborted / 30})
        print(f"   eve={f:.1f}  qber={np.mean(qs):.3f}  detected={aborted}/30", flush=True)
    return {"rows": rows, "sessions_per_point": 30, "noise": NOISE}


def e4_transfer() -> dict:
    print("E4 transfer under attack ...", flush=True)
    data = (b"Quantum Secure Direct Communication: the message is the quantum state. ") * 6
    out = {}
    for adaptive in (True, False):
        trials = []
        for t in range(8):
            rng = np.random.default_rng(300 + t)
            link = [("Alice", "R1"), ("R1", "Bob")][t % 2]
            at = int(rng.integers(1, 6))
            rep = demo_topology(adaptive=adaptive).transfer(
                data, "Alice", "Bob", QuantumBackend(seed=300 + t), rng,
                attacks={at: (*link, 1.0)})
            EXPOSED.append(rep.message_bits_on_aborted_sessions)
            trials.append({"link": "-".join(link), "attack_frame": at,
                           "delivered": rep.delivered, "verified": rep.verified,
                           "reroutes": rep.reroutes, "aborts": rep.aborts,
                           "qubits": rep.qubits_prepared, "seconds": round(rep.seconds, 2)})
        key = "adaptive" if adaptive else "static"
        out[key] = {"trials": trials,
                    "verified": sum(x["verified"] for x in trials), "n": len(trials)}
        print(f"   {key}: {out[key]['verified']}/{len(trials)} verified", flush=True)
    return out


def showcase() -> dict:
    print("Showcase transfer ...", flush=True)
    data = (b"QSDTS demo: this file crosses a quantum network while an eavesdropper "
            b"taps a link mid-transfer. The network detects it and routes around. ") * 3
    rep = demo_topology().transfer(data, "Alice", "Bob", QuantumBackend(seed=5),
                                   np.random.default_rng(5), attacks={4: ("R1", "Bob", 1.0)})
    EXPOSED.append(rep.message_bits_on_aborted_sessions)
    return {
        "bytes": len(data), "frames": rep.frames, "verified": rep.verified,
        "sha256": rep.sha256_received, "aborts": rep.aborts, "reroutes": rep.reroutes,
        "retransmissions": rep.retransmissions, "qubits": rep.qubits_prepared,
        "seconds": round(rep.seconds, 2),
        "paths": [" > ".join(p) for p in rep.paths],
        "events": [{"frame": e.frame, "kind": e.kind, "link": e.link,
                    "qber": e.qber, "detail": e.detail}
                   for e in rep.events if e.kind in ("abort", "reroute", "fail", "harden")],
    }


def main() -> None:
    t0 = time.perf_counter()
    res = {
        "e0_validation": e0_validation(),
        "e1_efficiency": e1_efficiency(),
        "e2_detection": e2_detection(),
        "e4_transfer": e4_transfer(),
        "showcase": showcase(),
    }
    res["e3_invariant"] = {"aborted_sessions_and_transfers": len(EXPOSED),
                           "message_bits_exposed": int(sum(EXPOSED))}
    res["runtime_s"] = round(time.perf_counter() - t0, 1)
    (OUT / "results.json").write_text(json.dumps(res, indent=2))
    print(json.dumps({k: v for k, v in res.items() if k != "e4_transfer"}, indent=2)[:3000])


if __name__ == "__main__":
    main()
