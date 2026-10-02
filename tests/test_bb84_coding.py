"""BB84 baseline and the channel coding layer."""

import itertools

import numpy as np
import pytest

from qsdts import bb84
from qsdts.channel import Link, QuantumBackend
from qsdts.coding import (
    FRAME_DATA_BYTES,
    coded_frame_bits,
    decode_frame,
    encode_frame,
    hamming_decode,
    hamming_encode,
)


class TestBB84:
    def test_clean_channel_gives_identical_keys(self):
        r = bb84.exchange(1000, Link("A", "B", depol=0.0), QuantumBackend(seed=1),
                          np.random.default_rng(1))
        assert r.qber == 0.0 and not r.aborted
        assert np.array_equal(r.key_alice, r.key_bob)

    def test_sifting_keeps_about_half(self):
        r = bb84.exchange(4000, Link("A", "B", depol=0.0), QuantumBackend(seed=2),
                          np.random.default_rng(2))
        # half survive sifting, a quarter of those are spent on the check
        assert len(r.key_alice) / 4000 == pytest.approx(0.5 * 0.75, abs=0.03)

    def test_intercept_resend_is_detected(self):
        r = bb84.exchange(4000, Link("A", "B", depol=0.0, eve=1.0), QuantumBackend(seed=3),
                          np.random.default_rng(3))
        assert r.qber == pytest.approx(0.25, abs=0.04)
        assert r.aborted


class TestHamming:
    def test_round_trip(self):
        bits = np.random.default_rng(0).integers(0, 2, 64, dtype=np.uint8)
        assert np.array_equal(hamming_decode(hamming_encode(bits)), bits)

    def test_corrects_every_single_bit_error_in_every_codeword(self):
        for word in itertools.product([0, 1], repeat=4):
            code = hamming_encode(np.array(word, np.uint8))
            for pos in range(7):
                bad = code.copy()
                bad[pos] ^= 1
                assert tuple(hamming_decode(bad)) == word


class TestFrames:
    def test_frame_size_is_448_coded_bits(self):
        assert coded_frame_bits() == 448
        assert len(encode_frame(b"x")) == 448

    def test_frame_round_trip(self):
        data = b"q" * FRAME_DATA_BYTES
        assert decode_frame(encode_frame(data)) == (data, True)

    def test_scattered_single_errors_are_corrected(self):
        coded = encode_frame(b"hello quantum")
        bad = coded.copy()
        bad[::7] ^= 1  # one flip in every codeword
        data, ok = decode_frame(bad)
        assert ok and data.rstrip(b"\0") == b"hello quantum"

    def test_crc_rejects_uncorrectable_damage(self):
        coded = encode_frame(b"hello quantum")
        bad = coded.copy()
        bad[0:3] ^= 1  # three flips in one codeword defeats Hamming
        _, ok = decode_frame(bad)
        assert not ok
