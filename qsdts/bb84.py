"""BB84 (Bennett and Brassard, 1984): the baseline.

BB84 distributes a key; the message then travels classically, encrypted with
that key as a one-time pad. It shares the channel, noise model and eavesdropper
with DL04, so the protocol is the only variable in any comparison.

    Alice prepares random bits in random bases and sends them.
    Bob measures each in a random basis.
    They publicly compare bases and keep the matching positions (sifting).
    A random subset of the sifted bits is revealed to estimate the QBER.
    The rest is the key.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from qiskit import QuantumCircuit

from .channel import Link, QuantumBackend, apply_eve, chunks, read_bits


@dataclass
class BB84Result:
    aborted: bool
    qber: float
    n_check: int
    key_alice: np.ndarray
    key_bob: np.ndarray
    qubits_prepared: int
    channel_uses: int


def exchange(
    n: int,
    link: Link,
    backend: QuantumBackend,
    rng: np.random.Generator,
    *,
    check_frac: float = 0.25,
    abort_above: float = 0.11,
) -> BB84Result:
    bits = rng.integers(0, 2, n, dtype=np.uint8)
    a_basis = rng.integers(0, 2, n, dtype=np.uint8)
    b_basis = rng.integers(0, 2, n, dtype=np.uint8)
    eve = rng.random(n) < link.eve
    eve_basis = rng.integers(0, 2, n, dtype=np.uint8)

    groups = chunks(n)
    circuits = []
    for g in groups:
        m = len(g)
        qc = QuantumCircuit(m, 2 * m)
        for q, lane in enumerate(g):
            if bits[lane]:
                qc.x(q)
            if a_basis[lane]:
                qc.h(q)
            qc.id(q)  # fibre
            if eve[lane]:
                apply_eve(qc, q, m + q, int(eve_basis[lane]))
            if b_basis[lane]:
                qc.h(q)
            qc.measure(q, q)
        circuits.append(qc)
    res = backend.run(circuits, link.noise_model())

    bob = np.zeros(n, np.uint8)
    for i, g in enumerate(groups):
        bob[list(g)] = read_bits(res, i, 2 * len(g))[: len(g)]

    sifted = np.flatnonzero(a_basis == b_basis)
    order = rng.permutation(len(sifted))
    n_chk = max(1, math.ceil(check_frac * len(sifted)))
    chk = sifted[order[:n_chk]]
    key = np.sort(sifted[order[n_chk:]])
    qber = float(np.mean(bits[chk] != bob[chk])) if len(chk) else 1.0

    return BB84Result(
        aborted=qber >= abort_above,
        qber=qber,
        n_check=int(len(chk)),
        key_alice=bits[key].copy(),
        key_bob=bob[key].copy(),
        qubits_prepared=n,
        channel_uses=n,
    )
