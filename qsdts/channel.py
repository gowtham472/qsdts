"""Layer 0: the quantum channel, on Qiskit Aer.

Every qubit is a real wire in a Qiskit circuit. A block of qubits is simulated
with Aer's stabilizer method, which is exact here because every operation the
protocols use is Clifford (X, H, Y, measurement) and fibre noise is modelled
as a depolarizing channel, which is a Pauli channel.

Two properties matter for the security argument:

* Eve is a measurement, not a coin flip. An intercept-resend attack is a
  mid-circuit measurement in a basis Eve picks at random. The collapse that
  measurement causes is exactly what she would resend, so the disturbance she
  introduces is produced by quantum mechanics, not assumed.

* A protocol can pause on the classical channel. Aer saves the stabilizer state
  at the end of one circuit and restores it at the start of the next. DL04 uses
  this to finish its eavesdropping check, decide on the classical channel, and
  only then encode the message onto the same qubits.

Qubits within a block never interact, so blocks are split into independent
chunks to keep each stabilizer tableau small.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import qiskit_aer.library  # noqa: F401  registers save_stabilizer / set_stabilizer
from qiskit import QuantumCircuit
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel, depolarizing_error

CHUNK = 64  # qubits per simulated circuit


@dataclass
class Link:
    """One fibre between two nodes.

    depol: Qiskit depolarizing parameter per pass, lambda in
           (1 - lambda) rho + lambda I/2. A qubit measured in either basis is
           flipped with probability lambda/2, so 0.010 means 0.5% per pass.
    eve:   fraction of qubits an eavesdropper intercepts and resends (0..1).
    """

    u: str
    v: str
    km: float = 10.0
    depol: float = 0.010
    eve: float = 0.0

    @property
    def name(self) -> str:
        return f"{self.u}-{self.v}"

    def noise_model(self) -> NoiseModel:
        nm = NoiseModel()
        if self.depol > 0:
            # Noise is attached only to the `id` gate, which stands for the
            # fibre. State preparation, encoding and measurement are ideal, so
            # every error in the simulation comes from the channel or from Eve.
            nm.add_all_qubit_quantum_error(depolarizing_error(self.depol, 1), ["id"])
        return nm


class QuantumBackend:
    """Thin wrapper over AerSimulator. Seeded, so every run is reproducible."""

    def __init__(self, seed: int | None = None):
        self.sim = AerSimulator(method="stabilizer")
        self._seed = seed
        self._calls = 0
        self.circuits_run = 0

    def run(self, circuits: list[QuantumCircuit], noise_model: NoiseModel):
        self._calls += 1
        seed = None if self._seed is None else self._seed * 100_003 + self._calls
        self.circuits_run += len(circuits)
        return self.sim.run(
            circuits, shots=1, noise_model=noise_model, seed_simulator=seed
        ).result()


def chunks(n: int, size: int = CHUNK) -> list[range]:
    return [range(s, min(s + size, n)) for s in range(0, n, size)]


def read_bits(result, index: int, n_clbits: int) -> np.ndarray:
    """Classical bits of circuit `index` from a shots=1 result, clbit 0 first."""
    key = next(iter(result.get_counts(index)))
    key = key.replace(" ", "")
    return np.array([int(key[-1 - j]) for j in range(n_clbits)], dtype=np.uint8)


def apply_eve(qc: QuantumCircuit, q: int, clbit: int, basis: int) -> None:
    """Intercept-resend on qubit q: measure in Eve's basis (0=Z, 1=X).

    The post-measurement state is the state Eve resends, so no explicit
    re-preparation is needed. Undoing the basis change after the measurement
    leaves the qubit in the eigenstate of Eve's basis she observed.
    """
    if basis:
        qc.h(q)
    qc.measure(q, clbit)
    if basis:
        qc.h(q)
