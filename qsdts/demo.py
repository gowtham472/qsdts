"""Live demo: a file crosses a quantum network while an eavesdropper attacks it.

    python -m qsdts.demo            full run (about 15 s)
    python -m qsdts.demo --quick    fewer frames

What happens, in order:

1. One DL04 session on a clean fibre: the message comes back exactly.
2. The same session with an eavesdropper: the check fails, the session aborts,
   and zero message bits were ever encoded.
3. A file transfer across a five-node network. Partway through, an
   eavesdropper taps the R1-Bob fibre. The network detects it, reroutes through
   R3, and the file arrives with its SHA-256 hash verified.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np

from . import dl04
from .channel import Link, QuantumBackend
from .coding import decode_frame, encode_frame
from .network import demo_topology

USE_COLOR = sys.stdout.isatty() or os.environ.get("FORCE_COLOR")


def c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if USE_COLOR else s


PINK, PURPLE, RED, DIM, BOLD = "38;5;211", "38;5;99", "38;5;203", "2", "1"


def say(s: str = "", pause: float = 0.0) -> None:
    print(s, flush=True)
    if pause:
        time.sleep(pause)


def step_clean(be, rng, pause):
    say(c(BOLD, "1. DL04 on a clean fibre"))
    msg = b"no key was ever created"
    r = dl04.send(encode_frame(msg), Link("Alice", "Bob", depol=0.0), be, rng)
    data, ok = decode_frame(r.payload)
    say(f"   check QBER {100 * r.qber_forward:.1f}%  ->  {c(PURPLE, 'PROCEED')}")
    say(f"   Bob decodes: {c(PINK, repr(data.rstrip(bytes(1)).decode()))}  integrity "
        f"{c(PURPLE, 'OK') if ok else c(RED, 'FAILED')}", pause)


def step_attack(be, rng, pause):
    say(c(BOLD, "2. Same session, eavesdropper on the fibre"))
    r = dl04.send(encode_frame(b"secret"), Link("Alice", "Bob", depol=0.0, eve=1.0), be, rng)
    say(f"   check QBER {c(RED, f'{100 * r.qber_forward:.1f}%')} on {r.sifted_forward} "
        f"sifted bits  ->  {c(RED, 'ABORT')}")
    say(f"   message bits ever encoded: {c(PINK, str(r.message_bits_on_channel))}", pause)


def step_network(seed, quick, pause):
    say(c(BOLD, "3. File transfer across the network, attacked mid-transfer"))
    text = (b"QSDTS demo: this file crosses a quantum network while an eavesdropper "
            b"taps a link mid-transfer. The network detects it and routes around. ")
    data = text if quick else text * 3
    attack_at = 1 if quick else 4
    say(c(DIM, f"   {len(data)} bytes, {(len(data) + 27) // 28} frames, "
               f"eavesdropper switches on at frame {attack_at + 1}"))

    def on_event(e):
        tag = {"hop": c(DIM, "hop     "), "abort": c(RED, "ABORT    "),
               "reroute": c(PINK, "REROUTE  "), "delivered": c(PURPLE, "delivered"),
               "retransmit": c(DIM, "retry    "), "harden": c(PINK, "HARDEN   "),
               "fail": c(RED, "FAIL     ")}[e.kind]
        if e.kind == "hop":
            return
        q = "" if e.qber is None else f"QBER {100 * e.qber:5.1f}%  "
        say(f"   frame {e.frame + 1:2d}  {tag}  {e.link:<10} {q}{c(DIM, e.detail)}")

    # A fresh, seeded stream, so this step reproduces the recorded run in
    # results/results.json exactly (same QBER, same frames, same hash).
    be, rng = QuantumBackend(seed=seed), np.random.default_rng(seed)
    rep = demo_topology().transfer(data, "Alice", "Bob", be, rng,
                                   attacks={attack_at: ("R1", "Bob", 1.0)}, on_event=on_event)
    say()
    for p in rep.paths:
        say(f"   path used: {' > '.join(p)}")
    ok = rep.verified
    say(f"   SHA-256 sent     {rep.sha256_sent[:32]}...")
    say(f"   SHA-256 received {rep.sha256_received[:32]}...  "
        f"{c(PURPLE, 'VERIFIED') if ok else c(RED, 'MISMATCH')}")
    say(f"   aborts {rep.aborts}, reroutes {rep.reroutes}, message bits exposed on "
        f"aborted sessions: {c(PINK, str(rep.message_bits_on_aborted_sessions))}", pause)
    return ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quick", action="store_true", help="shorter file")
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--pause", type=float, default=0.0, help="seconds between steps")
    args = ap.parse_args(argv)

    be, rng = QuantumBackend(seed=args.seed), np.random.default_rng(args.seed)
    say(c(PINK, "QSDTS") + c(DIM, "  quantum secure direct communication, simulated on Qiskit Aer"))
    say()
    step_clean(be, rng, args.pause)
    say()
    step_attack(be, rng, args.pause)
    say()
    ok = step_network(args.seed, args.quick, args.pause)
    say()
    say(c(PURPLE, "No key was generated, stored or transmitted at any point."))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
