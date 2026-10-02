"""QSDTS: Quantum Secure Data Transfer System.

A simulation framework for DL04 Quantum Secure Direct Communication over a
multi-hop routed network, with QBER-driven adaptive rerouting and a BB84
baseline sharing the same channel model.

Layers (each depends only on the one below it):

  channel   Qiskit Aer quantum channel: fibre noise and an eavesdropper
  dl04      the DL04 QSDC protocol, check-before-encode enforced
  bb84      BB84 key distribution, the baseline
  coding    Hamming(7,4) + CRC-32 framing for noisy channels
  network   topology, QBER monitor, security policy, router, file transfer
"""

__version__ = "0.1.0"
