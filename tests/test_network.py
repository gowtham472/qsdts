"""Policy, routing, and the end-to-end transfer under attack."""

import numpy as np
import pytest

from qsdts.channel import QuantumBackend
from qsdts.network import Action, Policy, QuantumNetwork, demo_topology

DATA = b"Quantum secure direct communication across a routed network. " * 2


class TestPolicy:
    @pytest.mark.parametrize(
        ("qber", "action"),
        [(0.00, Action.CONTINUE), (0.049, Action.CONTINUE), (0.05, Action.HARDEN),
         (0.079, Action.HARDEN), (0.08, Action.REROUTE), (0.109, Action.REROUTE),
         (0.11, Action.ABORT), (0.25, Action.ABORT)],
    )
    def test_thresholds(self, qber, action):
        assert Policy().evaluate(qber) is action

    def test_hysteresis_holds_harden_until_well_below(self):
        p = Policy()
        assert p.evaluate(0.045, currently_hardened=True) is Action.HARDEN
        assert p.evaluate(0.035, currently_hardened=True) is Action.CONTINUE


class TestRouting:
    def test_shortest_route_is_preferred(self):
        assert demo_topology().route("Alice", "Bob") == ["Alice", "R1", "Bob"]

    def test_compromised_link_is_excluded(self):
        net = demo_topology()
        net.link_state("R1", "Bob").compromised = True
        assert net.route("Alice", "Bob") == ["Alice", "R1", "R3", "Bob"]

    def test_rising_qber_makes_a_link_expensive_before_it_is_cut(self):
        net = demo_topology()
        net.link_state("R1", "Bob").window.extend([0.07, 0.07, 0.07])
        assert net.route("Alice", "Bob") != ["Alice", "R1", "Bob"]

    def test_no_path_when_every_route_is_compromised(self):
        net = QuantumNetwork()
        net.add_link("A", "B")
        net.link_state("A", "B").compromised = True
        assert net.route("A", "B") is None


@pytest.mark.slow
class TestTransfer:
    def test_clean_network_delivers_and_verifies(self):
        rep = demo_topology().transfer(DATA, "Alice", "Bob", QuantumBackend(seed=1),
                                       np.random.default_rng(1))
        assert rep.verified
        assert rep.aborts == 0 and rep.reroutes == 0

    def test_mid_transfer_attack_is_routed_around_and_file_still_verifies(self):
        rep = demo_topology().transfer(DATA, "Alice", "Bob", QuantumBackend(seed=2),
                                       np.random.default_rng(2),
                                       attacks={2: ("R1", "Bob", 1.0)})
        assert rep.verified
        assert rep.aborts >= 1 and rep.reroutes >= 1
        assert ["Alice", "R1", "R3", "Bob"] in rep.paths

    def test_no_message_bits_ever_reach_a_tapped_link(self):
        rep = demo_topology().transfer(DATA, "Alice", "Bob", QuantumBackend(seed=3),
                                       np.random.default_rng(3),
                                       attacks={1: ("Alice", "R1", 1.0)})
        assert rep.aborts >= 1
        assert rep.message_bits_on_aborted_sessions == 0

    def test_without_the_controller_the_same_attack_kills_the_transfer(self):
        rep = demo_topology(adaptive=False).transfer(
            DATA, "Alice", "Bob", QuantumBackend(seed=2), np.random.default_rng(2),
            attacks={2: ("R1", "Bob", 1.0)})
        assert not rep.delivered

    def test_attack_on_every_route_fails_safely(self):
        net = QuantumNetwork()
        net.add_link("A", "B")
        rep = net.transfer(DATA, "A", "B", QuantumBackend(seed=4), np.random.default_rng(4),
                           attacks={0: ("A", "B", 1.0)})
        assert not rep.delivered
        assert rep.message_bits_on_aborted_sessions == 0
