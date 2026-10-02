"""DL04 Quantum Secure Direct Communication (Deng and Long, PRA 69, 052319, 2004).

The message itself travels on the quantum channel. No key is ever generated.

    Phase 1  PREPARE   Bob prepares N qubits, each in a random state from
                       {|0>, |1>, |+>, |->}, and sends them to Alice.
    Phase 2  CHECK     Alice measures a random subset in random bases and
                       announces positions, bases and results. Bob compares
                       against what he prepared and computes the QBER.
                       If it is too high the session ABORTS here.
    Phase 3  ENCODE    Only if the check passed: Alice encodes each message bit
                       on a remaining qubit, I for 0 and iY for 1, mixes in a
                       few return-check qubits carrying random bits, and sends
                       the block back.
    Phase 4  DECODE    Bob measures each qubit in the basis he prepared it in.
                       Unchanged state reads 0, flipped state reads 1. Alice
                       then reveals the return-check bits so Bob can confirm the
                       return leg.

The security-critical invariant: phase 3 must never run if phase 2 failed. Here
that is structural. Phase 2 and phase 3 are separate circuit executions; the
quantum state is saved at the end of the check and restored only if the
classical decision says PROCEED. An aborted session returns before a single
encoding gate exists, and reports message_bits_on_channel == 0.

iY equals Y up to a global phase, so Y is used. It flips both |0> <-> |1> and
|+> <-> |->, which is why Alice can encode without knowing Bob's basis.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from qiskit import QuantumCircuit

from .channel import Link, QuantumBackend, apply_eve, chunks, read_bits


@dataclass
class DL04Result:
    aborted: bool
    abort_reason: str
    qber_forward: float
    sifted_forward: int
    qber_return: float | None
    payload: np.ndarray | None        # Bob's decoded message bits
    qubits_prepared: int
    channel_uses: int                 # qubit transmissions over the fibre
    message_bits_on_channel: int      # 0 whenever the session aborted
    eve_fraction_forward: float       # ground truth, for analysis only

    @property
    def return_ok(self) -> bool:
        return self.qber_return is not None


def block_layout(n_payload: int, check_frac: float, return_frac: float) -> tuple[int, int, int]:
    """(n_forward_check, n_return_check, n_total) for a payload size."""
    n_ret = max(8, math.ceil(return_frac * n_payload / (1.0 - return_frac)))
    remaining = n_payload + n_ret
    n_chk = max(16, math.ceil(check_frac * remaining / (1.0 - check_frac)))
    return n_chk, n_ret, remaining + n_chk


def send(
    message: np.ndarray,
    link: Link,
    backend: QuantumBackend,
    rng: np.random.Generator,
    *,
    check_frac: float = 0.25,
    return_frac: float = 0.10,
    proceed_below: float = 0.08,
) -> DL04Result:
    """Run one DL04 session carrying `message` (array of 0/1) across `link`.

    proceed_below is the forward-check QBER above which Alice refuses to
    encode. It is set by the security policy, not hard-coded here.
    """
    message = np.asarray(message, dtype=np.uint8)
    n_payload = len(message)
    n_chk, n_ret, n = block_layout(n_payload, check_frac, return_frac)

    # ---- classical randomness, drawn up front ------------------------------
    r = rng.integers(0, 2, n, dtype=np.uint8)     # Bob's bit per qubit
    b = rng.integers(0, 2, n, dtype=np.uint8)     # Bob's basis, 0=Z 1=X
    perm = rng.permutation(n)
    check_idx = np.sort(perm[:n_chk])             # Alice's forward check set
    rest = perm[n_chk:]
    ret_idx = np.sort(rest[:n_ret])               # return-check positions
    pay_idx = rest[n_ret:]                        # payload, in message order
    a = rng.integers(0, 2, n, dtype=np.uint8)     # Alice's check bases
    ret_bits = rng.integers(0, 2, n, dtype=np.uint8)
    eve_fwd = rng.random(n) < link.eve
    eve_bwd = rng.random(n) < link.eve
    eve_basis = rng.integers(0, 2, (2, n), dtype=np.uint8)

    is_check = np.zeros(n, bool)
    is_check[check_idx] = True
    nm = link.noise_model()

    # ---- phases 1-2: prepare, forward pass, Alice's check -------------------
    groups = chunks(n)
    circuits = []
    for g in groups:
        m = len(g)
        qc = QuantumCircuit(m, 2 * m)
        for q, lane in enumerate(g):
            if r[lane]:
                qc.x(q)
            if b[lane]:
                qc.h(q)
            qc.id(q)  # forward fibre
            if eve_fwd[lane]:
                apply_eve(qc, q, m + q, int(eve_basis[0, lane]))
            if is_check[lane]:
                if a[lane]:
                    qc.h(q)
                qc.measure(q, q)
        qc.save_stabilizer(label="state")
        circuits.append(qc)
    res1 = backend.run(circuits, nm)

    alice_out = np.zeros(n, np.uint8)
    saved = []
    for i, g in enumerate(groups):
        bits = read_bits(res1, i, 2 * len(g))
        alice_out[list(g)] = bits[: len(g)]
        saved.append(res1.data(i)["state"])

    # Bob reveals his bases for the checked positions; keep matching ones.
    sift = check_idx[a[check_idx] == b[check_idx]]
    errors = int(np.sum(alice_out[sift] != r[sift]))
    qber_fwd = errors / len(sift) if len(sift) else 1.0

    base = dict(
        qber_forward=qber_fwd,
        sifted_forward=int(len(sift)),
        qubits_prepared=n,
        eve_fraction_forward=float(np.mean(eve_fwd)),
    )

    if len(sift) == 0 or qber_fwd >= proceed_below:
        # ABORT. Nothing below this line has executed: no encoding gate was
        # ever created, so no message bit has touched the channel.
        return DL04Result(
            aborted=True,
            abort_reason="forward check failed" if len(sift) else "no sifted check bits",
            qber_return=None,
            payload=None,
            channel_uses=n,
            message_bits_on_channel=0,
            **base,
        )

    # ---- phases 3-4: encode, return pass, Bob decodes -----------------------
    encode = np.zeros(n, np.uint8)
    encode[pay_idx] = message
    encode[ret_idx] = ret_bits[ret_idx]

    circuits = []
    for i, g in enumerate(groups):
        m = len(g)
        qc = QuantumCircuit(m, 2 * m)
        qc.set_stabilizer(saved[i])
        for q, lane in enumerate(g):
            if is_check[lane]:
                continue  # consumed by Alice's check
            if encode[lane]:
                qc.y(q)
            qc.id(q)  # return fibre
            if eve_bwd[lane]:
                apply_eve(qc, q, m + q, int(eve_basis[1, lane]))
            if b[lane]:
                qc.h(q)
            qc.measure(q, q)
        circuits.append(qc)
    res2 = backend.run(circuits, nm)

    bob_out = np.zeros(n, np.uint8)
    for i, g in enumerate(groups):
        bob_out[list(g)] = read_bits(res2, i, 2 * len(g))[: len(g)]
    decoded = bob_out ^ r

    ret_errors = int(np.sum(decoded[ret_idx] != ret_bits[ret_idx]))
    qber_ret = ret_errors / len(ret_idx)

    return DL04Result(
        aborted=False,
        abort_reason="",
        qber_return=qber_ret,
        payload=decoded[pay_idx].copy(),
        channel_uses=n + (n - n_chk),
        message_bits_on_channel=n_payload,
        **base,
    )
