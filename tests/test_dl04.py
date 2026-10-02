"""DL04: the protocol's correctness and its one security-critical invariant."""

import numpy as np
import pytest
from qiskit import QuantumCircuit

from qsdts import dl04
from qsdts.channel import Link, QuantumBackend
from qsdts.coding import decode_frame, encode_frame


def run(link, msg=None, seed=1, **kw):
    msg = np.zeros(448, np.uint8) if msg is None else msg
    return dl04.send(msg, link, QuantumBackend(seed=seed), np.random.default_rng(seed), **kw)


def test_clean_channel_delivers_the_message_exactly():
    msg = encode_frame(b"no key was ever created")
    res = run(Link("A", "B", depol=0.0), msg)
    assert not res.aborted
    assert np.array_equal(res.payload, msg)
    assert decode_frame(res.payload) == (b"no key was ever created".ljust(28, b"\0"), True)


def test_clean_channel_measures_zero_qber_in_both_directions():
    res = run(Link("A", "B", depol=0.0))
    assert res.qber_forward == 0.0
    assert res.qber_return == 0.0


def test_every_random_message_round_trips_on_a_clean_channel():
    rng = np.random.default_rng(3)
    for seed in range(5):
        msg = rng.integers(0, 2, 448, dtype=np.uint8)
        res = run(Link("A", "B", depol=0.0), msg, seed=seed)
        assert np.array_equal(res.payload, msg)


def test_full_intercept_resend_is_caught_and_aborts():
    res = run(Link("A", "B", depol=0.0, eve=1.0))
    assert res.aborted
    assert res.payload is None


def test_abort_precedes_encoding(monkeypatch):
    """THE invariant. If the check fails, no encoding gate may ever be built.

    Every Y gate the protocol applies is counted. An aborted session must
    create none, and must report zero message bits on the channel.
    """
    calls = {"y": 0}
    original = QuantumCircuit.y

    def counting_y(self, *args, **kwargs):
        calls["y"] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(QuantumCircuit, "y", counting_y)
    msg = np.ones(448, np.uint8)  # every bit is a 1, so encoding would need Y gates
    res = run(Link("A", "B", depol=0.0, eve=1.0), msg)

    assert res.aborted
    assert calls["y"] == 0, "an encoding gate was created after a failed check"
    assert res.message_bits_on_channel == 0


def test_encoding_does_happen_when_the_check_passes(monkeypatch):
    """Guards the test above against passing vacuously."""
    calls = {"y": 0}
    original = QuantumCircuit.y

    def counting_y(self, *args, **kwargs):
        calls["y"] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(QuantumCircuit, "y", counting_y)
    res = run(Link("A", "B", depol=0.0), np.ones(448, np.uint8))
    assert not res.aborted
    assert calls["y"] >= 448


def test_intercept_resend_produces_the_theoretical_25_percent():
    """Eve picks the wrong basis half the time; when she does, Bob reads wrong
    half the time. 0.5 x 0.5 = 0.25. Pooled over many sessions the measured
    rate must agree."""
    be, rng = QuantumBackend(seed=21), np.random.default_rng(21)
    errors = sifted = 0
    for _ in range(40):
        r = dl04.send(np.zeros(448, np.uint8), Link("A", "B", depol=0.0, eve=1.0),
                      be, rng, proceed_below=1.01)
        errors += round(r.qber_forward * r.sifted_forward)
        sifted += r.sifted_forward
    # Tolerance is statistical, not a guess: three standard errors of a
    # binomial proportion at p = 0.25 for the number of bits actually checked.
    se = (0.25 * 0.75 / sifted) ** 0.5
    assert abs(errors / sifted - 0.25) < 3 * se


def test_partial_attack_scales_the_error_rate():
    be, rng = QuantumBackend(seed=4), np.random.default_rng(4)

    def pooled(frac):
        e = s = 0
        for _ in range(20):
            r = dl04.send(np.zeros(448, np.uint8), Link("A", "B", depol=0.0, eve=frac),
                          be, rng, proceed_below=1.01)
            e += round(r.qber_forward * r.sifted_forward)
            s += r.sifted_forward
        return e / s

    assert pooled(0.4) == pytest.approx(0.10, abs=0.025)


def test_noise_alone_does_not_trigger_an_abort():
    """Ordinary fibre noise must stay well under the reroute threshold."""
    aborts = sum(run(Link("A", "B", depol=0.01), seed=s).aborted for s in range(8))
    assert aborts == 0


def test_return_leg_attack_is_detected_by_the_return_check():
    """An eavesdropper only on the way back cannot read the message (she does
    not know Bob's states) but she does disturb it, and the return check sees
    that."""
    link = Link("A", "B", depol=0.0, eve=1.0)
    be, rng = QuantumBackend(seed=9), np.random.default_rng(9)
    res = dl04.send(np.zeros(448, np.uint8), link, be, rng, proceed_below=1.01)
    assert res.qber_return > 0.1


def test_accounting_is_consistent():
    res = run(Link("A", "B", depol=0.0))
    n_chk, n_ret, n = dl04.block_layout(448, 0.25, 0.10)
    assert res.qubits_prepared == n
    assert res.channel_uses == n + (n - n_chk)
    assert res.message_bits_on_channel == 448


def test_harder_check_uses_more_qubits():
    small = dl04.block_layout(448, 0.25, 0.10)[2]
    large = dl04.block_layout(448, 0.50, 0.10)[2]
    assert large > small


def test_session_is_reproducible_for_a_seed():
    a = run(Link("A", "B", depol=0.01), seed=5)
    b = run(Link("A", "B", depol=0.01), seed=5)
    assert a.qber_forward == b.qber_forward
    assert np.array_equal(a.payload, b.payload)
