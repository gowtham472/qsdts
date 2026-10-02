"""Framing for a noisy quantum channel: Hamming(7,4) + CRC-32.

A real fibre flips some bits. Hamming(7,4) corrects any single flip in each
7-bit codeword; CRC-32 then catches anything Hamming could not fix, and the
frame is retransmitted. Each hop checks integrity independently.
"""

from __future__ import annotations

import zlib

import numpy as np

FRAME_DATA_BYTES = 28  # 28 data + 4 CRC = 32 bytes = 256 bits -> 448 coded bits

# Systematic Hamming(7,4): codeword = [d1 d2 d3 d4 p1 p2 p3]
_G = np.array(
    [
        [1, 0, 0, 0, 1, 1, 0],
        [0, 1, 0, 0, 1, 0, 1],
        [0, 0, 1, 0, 0, 1, 1],
        [0, 0, 0, 1, 1, 1, 1],
    ],
    dtype=np.uint8,
)
_H = np.array(
    [
        [1, 1, 0, 1, 1, 0, 0],
        [1, 0, 1, 1, 0, 1, 0],
        [0, 1, 1, 1, 0, 0, 1],
    ],
    dtype=np.uint8,
)
# syndrome (as int) -> column index of the flipped bit
_SYNDROME_TO_POS = {
    int(_H[0, j]) << 2 | int(_H[1, j]) << 1 | int(_H[2, j]): j for j in range(7)
}


def bytes_to_bits(data: bytes) -> np.ndarray:
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8))


def bits_to_bytes(bits: np.ndarray) -> bytes:
    return np.packbits(np.asarray(bits, dtype=np.uint8)).tobytes()


def hamming_encode(bits: np.ndarray) -> np.ndarray:
    bits = np.asarray(bits, dtype=np.uint8)
    assert len(bits) % 4 == 0, "Hamming(7,4) needs a multiple of 4 bits"
    return (bits.reshape(-1, 4) @ _G % 2).astype(np.uint8).ravel()


def hamming_decode(coded: np.ndarray) -> np.ndarray:
    words = np.asarray(coded, dtype=np.uint8).reshape(-1, 7).copy()
    syn = words @ _H.T % 2
    for i, s in enumerate(syn):
        key = int(s[0]) << 2 | int(s[1]) << 1 | int(s[2])
        if key:
            words[i, _SYNDROME_TO_POS[key]] ^= 1
    return words[:, :4].ravel()


def encode_frame(data: bytes) -> np.ndarray:
    assert len(data) <= FRAME_DATA_BYTES
    padded = data.ljust(FRAME_DATA_BYTES, b"\0")
    crc = zlib.crc32(padded).to_bytes(4, "big")
    return hamming_encode(bytes_to_bits(padded + crc))


def decode_frame(coded: np.ndarray) -> tuple[bytes, bool]:
    raw = bits_to_bytes(hamming_decode(coded))
    data, crc = raw[:FRAME_DATA_BYTES], raw[FRAME_DATA_BYTES:]
    return data, zlib.crc32(data).to_bytes(4, "big") == crc


def coded_frame_bits() -> int:
    return (FRAME_DATA_BYTES + 4) * 8 * 7 // 4
