"""Layers 2-3: the network, and what it does when security degrades.

Each hop runs an independent DL04 session. A relay decodes the frame and
re-encodes it for the next hop, which means the relay sees plaintext. That is
the trusted-relay model every deployed quantum network uses (Tokyo,
Beijing-Shanghai); removing it needs quantum repeaters.

Every DL04 forward check yields a QBER measurement for that link. A monitor
smooths those per link, and a four-state policy acts on them:

    QBER <  5%        CONTINUE   normal operation
    5%  <= QBER < 8%  HARDEN     check more qubits per block
    8%  <= QBER < 11% REROUTE    stop using the link, route around it
    QBER >= 11%       ABORT      beyond the provable-security bound

Eavesdropping becomes a routing event: the transfer moves off a tapped link and
completes, instead of failing. Rerouting starts from the node currently holding
the frame, so plaintext never crosses the compromised link.
"""

from __future__ import annotations

import hashlib
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

import networkx as nx
import numpy as np

from . import dl04
from .channel import Link, QuantumBackend
from .coding import FRAME_DATA_BYTES, decode_frame, encode_frame


class Action(str, Enum):
    CONTINUE = "CONTINUE"
    HARDEN = "HARDEN"
    REROUTE = "REROUTE"
    ABORT = "ABORT"


@dataclass
class Policy:
    harden_at: float = 0.05
    reroute_at: float = 0.08
    abort_at: float = 0.11
    unharden_below: float = 0.04       # hysteresis: leave HARDEN only below this
    check_frac: float = 0.25
    hardened_check_frac: float = 0.50

    def evaluate(self, qber: float, currently_hardened: bool = False) -> Action:
        if qber >= self.abort_at:
            return Action.ABORT
        if qber >= self.reroute_at:
            return Action.REROUTE
        if qber >= self.harden_at:
            return Action.HARDEN
        if currently_hardened and qber >= self.unharden_below:
            return Action.HARDEN
        return Action.CONTINUE


@dataclass
class LinkState:
    window: deque = field(default_factory=lambda: deque(maxlen=5))
    hardened: bool = False
    compromised: bool = False

    def estimate(self) -> float:
        return float(np.mean(self.window)) if self.window else 0.0


@dataclass
class Event:
    frame: int
    kind: str          # hop | abort | reroute | harden | retransmit | delivered | fail
    link: str
    qber: float | None = None
    detail: str = ""


@dataclass
class TransferReport:
    delivered: bool
    sha256_sent: str
    sha256_received: str
    frames: int
    hops_attempted: int
    aborts: int
    reroutes: int
    retransmissions: int
    qubits_prepared: int
    message_bits_on_aborted_sessions: int
    seconds: float
    paths: list[list[str]] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)

    @property
    def verified(self) -> bool:
        return self.delivered and self.sha256_sent == self.sha256_received


class QuantumNetwork:
    def __init__(self, policy: Policy | None = None, adaptive: bool = True):
        self.g = nx.Graph()
        self.policy = policy or Policy()
        self.adaptive = adaptive
        self.state: dict[frozenset, LinkState] = {}

    # ---- topology -----------------------------------------------------------
    def add_link(self, u: str, v: str, km: float = 10.0, depol: float = 0.010) -> Link:
        link = Link(u, v, km=km, depol=depol)
        self.g.add_edge(u, v, link=link)
        self.state[frozenset((u, v))] = LinkState()
        return link

    def link(self, u: str, v: str) -> Link:
        return self.g[u][v]["link"]

    def link_state(self, u: str, v: str) -> LinkState:
        return self.state[frozenset((u, v))]

    def tap(self, u: str, v: str, fraction: float = 1.0) -> None:
        """Place an intercept-resend eavesdropper on a link."""
        self.link(u, v).eve = fraction

    # ---- routing --------------------------------------------------------------
    def _cost(self, u: str, v: str, attrs: dict) -> float | None:
        st = self.link_state(u, v)
        if self.adaptive and st.compromised:
            return None  # excluded from routing entirely
        q = st.estimate() if self.adaptive else 0.0
        # Cost rises sharply as measured QBER approaches the abort bound, so
        # traffic drifts off a degrading link before it has to be cut.
        headroom = max(1e-3, 1.0 - q / self.policy.abort_at)
        return attrs["link"].km / headroom**2

    def route(self, src: str, dst: str) -> list[str] | None:
        try:
            return nx.shortest_path(self.g, src, dst, weight=self._cost)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    # ---- transfer -------------------------------------------------------------
    def transfer(
        self,
        data: bytes,
        src: str,
        dst: str,
        backend: QuantumBackend,
        rng: np.random.Generator,
        *,
        attacks: dict[int, tuple[str, str, float]] | None = None,
        max_retries: int = 6,
        on_event=None,
    ) -> TransferReport:
        """Send `data` from src to dst, frame by frame, hop by hop.

        attacks maps a frame index to (u, v, fraction): the eavesdropper is
        switched on just before that frame, i.e. mid-transfer.
        """
        t0 = time.perf_counter()
        attacks = attacks or {}
        frames = [data[i : i + FRAME_DATA_BYTES] for i in range(0, len(data), FRAME_DATA_BYTES)]
        received = bytearray()
        rep = TransferReport(
            delivered=False, sha256_sent=hashlib.sha256(data).hexdigest(), sha256_received="",
            frames=len(frames), hops_attempted=0, aborts=0, reroutes=0, retransmissions=0,
            qubits_prepared=0, message_bits_on_aborted_sessions=0, seconds=0.0,
        )

        def log(ev: Event) -> None:
            rep.events.append(ev)
            if on_event:
                on_event(ev)

        for fi, chunk in enumerate(frames):
            if fi in attacks:
                u, v, frac = attacks[fi]
                self.tap(u, v, frac)

            coded = encode_frame(chunk)
            node = src
            travelled = [src]
            frame = b""
            while node != dst:
                path = self.route(node, dst)
                if path is None:
                    log(Event(fi, "fail", node, detail="no secure path remains"))
                    rep.seconds = time.perf_counter() - t0
                    return rep

                nxt = path[1]
                link, st = self.link(node, nxt), self.link_state(node, nxt)
                check = self.policy.hardened_check_frac if st.hardened else self.policy.check_frac

                delivered_hop = False
                for _ in range(max_retries):
                    rep.hops_attempted += 1
                    res = dl04.send(
                        coded, link, backend, rng,
                        check_frac=check,
                        proceed_below=self.policy.reroute_at if self.adaptive else self.policy.abort_at,
                    )
                    rep.qubits_prepared += res.qubits_prepared
                    st.window.append(res.qber_forward)
                    action = self.policy.evaluate(res.qber_forward, st.hardened)

                    if res.aborted:
                        rep.aborts += 1
                        rep.message_bits_on_aborted_sessions += res.message_bits_on_channel
                        log(Event(fi, "abort", link.name, res.qber_forward,
                                  f"{action.value}: message never encoded"))
                        if self.adaptive:
                            st.compromised = True
                            rep.reroutes += 1
                            alt = self.route(node, dst)
                            log(Event(fi, "reroute", link.name, res.qber_forward,
                                      f"{node} routes around {link.name} via "
                                      + ("-".join(alt) if alt else "nothing")))
                        break

                    if action is Action.HARDEN and not st.hardened:
                        st.hardened = True
                        log(Event(fi, "harden", link.name, res.qber_forward, "check fraction raised"))
                    elif action is Action.CONTINUE and st.hardened:
                        st.hardened = False

                    frame, ok = decode_frame(res.payload)
                    if ok:
                        log(Event(fi, "hop", link.name, res.qber_forward))
                        delivered_hop = True
                        break
                    rep.retransmissions += 1
                    log(Event(fi, "retransmit", link.name, res.qber_forward, "CRC failed"))

                if delivered_hop:
                    node = nxt
                    travelled.append(nxt)
                elif not self.adaptive or not st.compromised:
                    log(Event(fi, "fail", link.name, detail="hop could not be completed"))
                    rep.seconds = time.perf_counter() - t0
                    return rep

            if not rep.paths or rep.paths[-1] != travelled:
                rep.paths.append(travelled)
            received += frame[: len(chunk)]
            log(Event(fi, "delivered", dst))

        rep.delivered = True
        rep.sha256_received = hashlib.sha256(bytes(received)).hexdigest()
        rep.seconds = time.perf_counter() - t0
        return rep


def demo_topology(depol: float = 0.010, adaptive: bool = True) -> QuantumNetwork:
    """Five nodes, two disjoint routes plus a cross link.

          R1 ---------- Bob
         /  \\          /
    Alice    \\        /
         \\    R3 ----
          R2 /

    Primary route Alice-R1-Bob is shortest. When R1-Bob is tapped, R1 routes
    around it via R3, so the frame never crosses the tapped fibre.
    """
    net = QuantumNetwork(adaptive=adaptive)
    net.add_link("Alice", "R1", km=10, depol=depol)
    net.add_link("R1", "Bob", km=10, depol=depol)
    net.add_link("Alice", "R2", km=12, depol=depol)
    net.add_link("R2", "R3", km=12, depol=depol)
    net.add_link("R1", "R3", km=8, depol=depol)
    net.add_link("R3", "Bob", km=10, depol=depol)
    return net
