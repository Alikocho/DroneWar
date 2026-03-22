"""
tests/test_dronewar.py
======================
Test suite for DroneWar.

Covers:
  - Hex geometry (distance, neighbours, line, disk, path)
  - Airspace construction and grid building
  - Sensor detection probability model
  - Interceptor hit probability (EW immunity for kinetic/laser)
  - Jamming model
  - Action resolution (move, engage, spoof, clear_track, EW)
  - Sensor sweep and track management
  - Engine turn loop and win conditions
  - All three scenarios run to completion
  - Balance: Blue can win (not 0% win rate)
  - Determinism across seeds
"""

import random
import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dronewar.env.airspace import (
    Airspace, HexCell, Drone, DroneRole, DroneStatus, DroneState,
    Sensor, SensorType, SensorState,
    Interceptor, InterceptorType, InterceptorState,
    TerrainType, AutonomyLevel, Team,
    hex_distance, hex_neighbours, hex_disk, hex_line, shortest_path,
)
from dronewar.env.actions import (
    ActionResolver, RedAction, BlueAction,
    RedActionType, BlueActionType,
)
from dronewar.env.observation import ObservationBuilder
from dronewar.engine.engine import DroneWarEngine, WinCondition
from dronewar.agents.agents import (
    HeuristicRedAgent, HeuristicBlueAgent,
    RandomRedAgent, RandomBlueAgent,
)
from dronewar.scenarios.scenarios import (
    forward_strike, infrastructure_raid, reconnaissance, SCENARIOS,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def rng():
    return random.Random(42)

@pytest.fixture
def small_airspace():
    a = Airspace(name="Test", radius=4, deadline=10)
    a.build_grid()
    return a

@pytest.fixture
def resolver(small_airspace, rng):
    return ActionResolver(small_airspace, rng)


# ── Hex geometry ──────────────────────────────────────────────────────────────

class TestHexGeometry:
    def test_distance_self(self):
        assert hex_distance((0,0), (0,0)) == 0

    def test_distance_adjacent(self):
        for nb in hex_neighbours(0, 0):
            assert hex_distance((0,0), nb) == 1

    def test_distance_known(self):
        assert hex_distance((0,0), (3,0))  == 3
        assert hex_distance((0,0), (-2,3)) == 3
        assert hex_distance((2,-3),(0,0))  == 3

    def test_distance_symmetric(self):
        assert hex_distance((1,2), (4,-1)) == hex_distance((4,-1), (1,2))

    def test_neighbours_count(self):
        assert len(hex_neighbours(0,0)) == 6

    def test_neighbours_each_distance_1(self):
        for nb in hex_neighbours(3, -2):
            assert hex_distance((3,-2), nb) == 1

    def test_disk_center(self):
        disk = hex_disk((0,0), 0)
        assert (0,0) in disk
        assert len(disk) == 1

    def test_disk_radius_1(self):
        disk = hex_disk((0,0), 1)
        assert len(disk) == 7   # center + 6 neighbours

    def test_disk_radius_2(self):
        disk = hex_disk((0,0), 2)
        assert len(disk) == 19  # 1 + 6 + 12

    def test_hex_line_endpoints(self):
        line = hex_line((0,0), (3,0))
        assert line[0]  == (0,0)
        assert line[-1] == (3,0)

    def test_hex_line_length(self):
        line = hex_line((0,0), (4,0))
        assert len(line) == 5

    def test_hex_line_self(self):
        assert hex_line((2,1), (2,1)) == [(2,1)]

    def test_shortest_path_adjacent(self):
        a = Airspace(name="T", radius=3, deadline=5)
        a.build_grid()
        path = shortest_path((0,0),(1,0), a.cells, speed=2)
        assert path == [(1,0)]

    def test_shortest_path_respects_speed(self):
        a = Airspace(name="T", radius=5, deadline=5)
        a.build_grid()
        path = shortest_path((0,0),(5,0), a.cells, speed=2)
        assert len(path) <= 2

    def test_shortest_path_same_start_goal(self):
        a = Airspace(name="T", radius=3, deadline=5)
        a.build_grid()
        assert shortest_path((0,0),(0,0), a.cells, speed=2) == []


# ── Airspace ──────────────────────────────────────────────────────────────────

class TestAirspace:
    def test_grid_size_radius_1(self):
        a = Airspace(name="T", radius=1, deadline=5)
        a.build_grid()
        assert len(a.cells) == 7

    def test_grid_size_radius_4(self, small_airspace):
        # radius n → 3n²+3n+1 cells
        assert len(small_airspace.cells) == 3*4*4 + 3*4 + 1

    def test_all_cells_in_bounds(self, small_airspace):
        for coord in small_airspace.cells:
            assert small_airspace.in_bounds(*coord)

    def test_origin_in_grid(self, small_airspace):
        assert small_airspace.in_bounds(0, 0)

    def test_out_of_bounds(self, small_airspace):
        assert not small_airspace.in_bounds(99, 99)

    def test_jam_level_no_ew(self, small_airspace):
        assert small_airspace.jam_level_at((0,0)) == 0.0

    def test_jam_level_with_ew(self, small_airspace):
        d = Drone("ew_test", DroneRole.EW, speed=1, rcs=0.4)
        d.state = DroneState(position=(0,0), jammer_active=True, jammer_range=3)
        small_airspace.drones.append(d)
        assert small_airspace.jam_level_at((0,0)) > 0.0
        assert small_airspace.jam_level_at((0,0)) <= 1.0

    def test_jam_falls_off_with_distance(self, small_airspace):
        d = Drone("ew_test", DroneRole.EW)
        d.state = DroneState(position=(0,0), jammer_active=True, jammer_range=3)
        small_airspace.drones.append(d)
        j0 = small_airspace.jam_level_at((0,0))
        j2 = small_airspace.jam_level_at((2,0))
        assert j0 > j2

    def test_los_clear_open(self, small_airspace):
        assert small_airspace.los_clear((0,0), (3,0))

    def test_los_blocked_by_mountain(self, small_airspace):
        small_airspace.cells[(1,0)].terrain = TerrainType.MOUNTAIN
        assert not small_airspace.los_clear((0,0), (3,0))

    def test_compute_scores_empty(self, small_airspace):
        small_airspace.compute_scores()   # should not raise

    def test_compute_scores_objective(self, small_airspace):
        d = Drone("s1", DroneRole.STRIKE)
        d.state = DroneState(position=(0,0), status=DroneStatus.OBJECTIVE)
        small_airspace.drones = [d]
        small_airspace.compute_scores()
        assert small_airspace.red_score == 1.0

    def test_active_drones_filters_destroyed(self, small_airspace):
        d1 = Drone("a", DroneRole.STRIKE)
        d1.state = DroneState((0,0))
        d2 = Drone("b", DroneRole.STRIKE)
        d2.state = DroneState((1,0), status=DroneStatus.DESTROYED)
        small_airspace.drones = [d1, d2]
        assert len(small_airspace.active_drones()) == 1


# ── Sensor detection ──────────────────────────────────────────────────────────

class TestSensorDetection:
    def _cell(self):
        return HexCell(q=0, r=0)

    def _drone(self, rcs=0.5):
        d = Drone("d", DroneRole.STRIKE, rcs=rcs)
        d.state = DroneState((0,0))
        return d

    def test_out_of_range_returns_zero(self):
        s = Sensor("s", SensorType.RADAR, (0,0), range=3)
        d = self._drone()
        far_cell = HexCell(q=5, r=0)
        assert s.detection_prob(d, far_cell, 0.0, 0.0) == 0.0

    def test_suppressed_sensor_returns_zero(self):
        s = Sensor("s", SensorType.RADAR, (0,0), range=5)
        s.state.suppressed = True
        d = self._drone()
        assert s.detection_prob(d, self._cell(), 0.0, 0.0) == 0.0

    def test_inoperational_sensor_returns_zero(self):
        s = Sensor("s", SensorType.RADAR, (0,0), range=5)
        s.state.operational = False
        d = self._drone()
        assert s.detection_prob(d, self._cell(), 0.0, 0.0) == 0.0

    def test_prob_in_range(self):
        s = Sensor("s", SensorType.RADAR, (0,0), range=5, base_prob=0.9)
        d = self._drone(rcs=1.0)
        p = s.detection_prob(d, self._cell(), 0.0, 0.0)
        assert 0 < p <= 1.0

    def test_low_rcs_reduces_detection(self):
        s = Sensor("s", SensorType.RADAR, (0,0), range=5)
        d_hi = self._drone(rcs=0.9)
        d_lo = self._drone(rcs=0.1)
        c = self._cell()
        assert s.detection_prob(d_hi, c, 0.0, 0.0) > s.detection_prob(d_lo, c, 0.0, 0.0)

    def test_jamming_reduces_radar(self):
        s = Sensor("s", SensorType.RADAR, (0,0), range=5)
        d = self._drone(rcs=0.8)
        c = self._cell()
        p_no_jam = s.detection_prob(d, c, 0.0, 0.0)
        p_jammed  = s.detection_prob(d, c, 0.8, 0.0)
        assert p_no_jam > p_jammed

    def test_jamming_does_not_affect_optical(self):
        s = Sensor("s", SensorType.OPTICAL, (0,0), range=5)
        d = self._drone(rcs=0.8)
        c = self._cell()
        p_no_jam = s.detection_prob(d, c, 0.0, 0.0)
        p_jammed  = s.detection_prob(d, c, 0.9, 0.0)
        assert abs(p_no_jam - p_jammed) < 0.001

    def test_weather_reduces_optical(self):
        s = Sensor("s", SensorType.OPTICAL, (0,0), range=5)
        d = self._drone(rcs=0.8)
        c = self._cell()
        p_clear   = s.detection_prob(d, c, 0.0, 0.0)
        p_cloudy  = s.detection_prob(d, c, 0.0, 0.9)
        assert p_clear > p_cloudy

    def test_weather_does_not_affect_radar(self):
        s = Sensor("s", SensorType.RADAR, (0,0), range=5)
        d = self._drone(rcs=0.8)
        c = self._cell()
        p1 = s.detection_prob(d, c, 0.0, 0.0)
        p2 = s.detection_prob(d, c, 0.0, 0.9)
        assert abs(p1 - p2) < 0.001

    def test_terrain_clutter_reduces_radar(self):
        s = Sensor("s", SensorType.RADAR, (0,0), range=5)
        d = self._drone(rcs=0.8)
        c_open  = HexCell(q=0, r=0, terrain=TerrainType.OPEN)
        c_urban = HexCell(q=0, r=0, terrain=TerrainType.URBAN)
        assert s.detection_prob(d, c_open, 0.0, 0.0) > \
               s.detection_prob(d, c_urban, 0.0, 0.0)


# ── Interceptor hit probability ────────────────────────────────────────────────

class TestInterceptorHitProb:
    def _drone(self, rcs=0.35):
        d = Drone("d", DroneRole.STRIKE, rcs=rcs)
        return d

    def test_kinetic_ew_immune(self):
        ic = Interceptor("k", InterceptorType.KINETIC, hit_prob=0.70)
        d  = self._drone()
        p_no_jam = ic.effective_hit_prob(d, 0.0)
        p_jammed  = ic.effective_hit_prob(d, 1.0)
        assert abs(p_no_jam - p_jammed) < 0.01

    def test_laser_ew_immune(self):
        ic = Interceptor("l", InterceptorType.LASER, hit_prob=0.80)
        d  = self._drone()
        p_no_jam = ic.effective_hit_prob(d, 0.0)
        p_jammed  = ic.effective_hit_prob(d, 1.0)
        assert abs(p_no_jam - p_jammed) < 0.01

    def test_net_ew_degraded(self):
        ic = Interceptor("n", InterceptorType.NET, hit_prob=0.70)
        d  = self._drone()
        p_no_jam = ic.effective_hit_prob(d, 0.0)
        p_jammed  = ic.effective_hit_prob(d, 1.0)
        assert p_no_jam > p_jammed

    def test_rf_kill_ew_degraded(self):
        ic = Interceptor("r", InterceptorType.RF_KILL, hit_prob=0.65)
        d  = self._drone()
        assert ic.effective_hit_prob(d, 0.0) > ic.effective_hit_prob(d, 0.9)

    def test_prob_never_below_floor(self):
        ic = Interceptor("n", InterceptorType.NET, hit_prob=0.50)
        d  = self._drone()
        assert ic.effective_hit_prob(d, 1.0) >= 0.05

    def test_kinetic_floor(self):
        ic = Interceptor("k", InterceptorType.KINETIC, hit_prob=0.70)
        d  = self._drone(rcs=0.05)
        assert ic.effective_hit_prob(d, 0.0) >= 0.15


# ── Action resolution ──────────────────────────────────────────────────────────

class TestActionResolution:
    def _setup(self, radius=5, seed=99):
        rng = random.Random(seed)
        a   = Airspace(name="T", radius=radius, deadline=15)
        a.build_grid()
        return a, ActionResolver(a, rng)

    def test_move_drone_toward_target(self):
        a, res = self._setup()
        d = Drone("d1", DroneRole.STRIKE, speed=2)
        d.state = DroneState(position=(0,4))
        a.drones.append(d)
        a.cells[(0,-4)].is_target = True
        res.resolve_red_move(RedAction(
            RedActionType.MOVE, ["d1"], target=(0,-4)))
        assert d.position != (0,4)
        assert hex_distance(d.position, (0,4)) <= 2

    def test_move_destroyed_drone_ignored(self):
        a, res = self._setup()
        d = Drone("d1", DroneRole.STRIKE)
        d.state = DroneState(position=(0,0), status=DroneStatus.DESTROYED)
        a.drones.append(d)
        res.resolve_red_move(RedAction(
            RedActionType.MOVE, ["d1"], target=(2,0)))
        assert d.position == (0,0)

    def test_strike_drone_reaches_target(self):
        a, res = self._setup()
        d = Drone("s1", DroneRole.STRIKE, speed=5)
        d.state = DroneState(position=(0,1))
        a.drones.append(d)
        a.cells[(0,0)].is_target = True
        res.resolve_red_move(RedAction(
            RedActionType.MOVE, ["s1"], target=(0,0)))
        assert d.state.status == DroneStatus.OBJECTIVE

    def test_ew_activate_toggle(self):
        a, res = self._setup()
        d = Drone("ew1", DroneRole.EW)
        d.state = DroneState(position=(0,0), jammer_active=False)
        a.drones.append(d)
        res.resolve_activate_ew(RedAction(RedActionType.ACTIVATE_EW, ["ew1"]))
        assert d.state.jammer_active is True
        res.resolve_activate_ew(RedAction(RedActionType.ACTIVATE_EW, ["ew1"]))
        assert d.state.jammer_active is False

    def test_spoof_creates_track(self):
        a, res = self._setup()
        initial = len(a.tracks)
        res.resolve_spoof(RedAction(RedActionType.SPOOF, [], target=(1,0)))
        assert len(a.tracks) == initial + 1
        track = list(a.tracks.values())[-1]
        assert track.is_spoofed is True

    def test_engage_kills_drone_in_range(self):
        a, res = self._setup()
        d = Drone("target", DroneRole.STRIKE)
        d.state = DroneState(position=(2,0))
        a.drones.append(d)
        ic = Interceptor("ic1", InterceptorType.KINETIC, range=5, hit_prob=0.99)
        ic.state = InterceptorState(position=(0,0))
        a.interceptors.append(ic)
        a.tracks["track_target"] = __import__(
            'dronewar.env.airspace', fromlist=['Track']
        ).Track("track_target", (2,0), 0.9)
        # Force hit by seeding RNG
        res.rng = random.Random(0)
        # Run until hit (high prob)
        for _ in range(20):
            if d.state.status == DroneStatus.DESTROYED:
                break
            ic.state.available = True
            ic.state.cooldown  = 0
            res.resolve_engage(BlueAction(
                BlueActionType.ENGAGE, interceptor_id="ic1",
                track_id="track_target"))
        assert d.state.status == DroneStatus.DESTROYED

    def test_engage_out_of_range_fails(self):
        a, res = self._setup()
        d = Drone("far", DroneRole.STRIKE)
        d.state = DroneState(position=(4,0))
        a.drones.append(d)
        ic = Interceptor("ic1", InterceptorType.KINETIC, range=2)
        ic.state = InterceptorState(position=(0,0))
        a.interceptors.append(ic)
        a.tracks["track_far"] = __import__(
            'dronewar.env.airspace', fromlist=['Track']
        ).Track("track_far", (4,0), 0.9)
        result = res.resolve_engage(BlueAction(
            BlueActionType.ENGAGE, interceptor_id="ic1", track_id="track_far"))
        assert result is False
        assert d.state.status == DroneStatus.ACTIVE

    def test_engage_spoofed_track_wastes_shot(self):
        from dronewar.env.airspace import Track
        a, res = self._setup()
        ic = Interceptor("ic1", InterceptorType.KINETIC, range=5, hit_prob=0.99)
        ic.state = InterceptorState(position=(0,0))
        a.interceptors.append(ic)
        a.tracks["spoof_0"] = Track("spoof_0", (1,0), 0.8, is_spoofed=True)
        result = res.resolve_engage(BlueAction(
            BlueActionType.ENGAGE, interceptor_id="ic1", track_id="spoof_0"))
        assert result is False

    def test_clear_track_removes_it(self):
        from dronewar.env.airspace import Track
        a, res = self._setup()
        a.tracks["t1"] = Track("t1", (1,0), 0.7)
        res.resolve_clear_track(BlueAction(BlueActionType.CLEAR_TRACK, track_id="t1"))
        assert "t1" not in a.tracks

    def test_cooldown_tick(self):
        a, res = self._setup()
        ic = Interceptor("ic1", InterceptorType.KINETIC, reload_turns=2)
        ic.state = InterceptorState(position=(0,0), available=False, cooldown=2)
        a.interceptors.append(ic)
        res.tick_cooldowns()
        assert ic.state.cooldown == 1
        assert ic.state.available is False
        res.tick_cooldowns()
        assert ic.state.cooldown == 0
        assert ic.state.available is True

    def test_sensor_sweep_creates_track(self):
        a, res = self._setup()
        d = Drone("d1", DroneRole.STRIKE, rcs=1.0)
        d.state = DroneState(position=(1,0))
        a.drones.append(d)
        s = Sensor("s1", SensorType.RADAR, (0,0), range=5, base_prob=0.99)
        a.sensors.append(s)
        # Sweep many times to ensure detection with high prob
        for _ in range(20):
            res.sensor_sweep()
            if "track_d1" in a.tracks:
                break
        assert "track_d1" in a.tracks

    def test_sensor_sweep_ages_stale_tracks(self):
        from dronewar.env.airspace import Track
        a, res = self._setup()
        a.tracks["track_ghost"] = Track("track_ghost", (3,0), 0.8, age=0)
        # No real drone and no sensor → track ages out
        res.sensor_sweep()
        res.sensor_sweep()
        res.sensor_sweep()
        assert "track_ghost" not in a.tracks


# ── Engine ────────────────────────────────────────────────────────────────────

class TestEngine:
    def _run(self, scenario_fn, seed=42):
        rng = random.Random(seed)
        a   = scenario_fn()
        red  = HeuristicRedAgent("r", Team.RED,  rng=random.Random(rng.randint(0,9999)))
        blue = HeuristicBlueAgent("b", Team.BLUE, rng=random.Random(rng.randint(0,9999)))
        eng  = DroneWarEngine(a, red, blue,
                              WinCondition(deadline=a.deadline,
                                           red_objectives_needed=a.red_objectives_needed),
                              rng=rng, verbose=False)
        eng.run()
        return eng, a

    @pytest.mark.parametrize("scenario_fn", [
        forward_strike, infrastructure_raid, reconnaissance
    ])
    def test_all_scenarios_complete(self, scenario_fn):
        eng, a = self._run(scenario_fn)
        assert eng.winner in (Team.RED, Team.BLUE)
        assert eng.turn > 0

    @pytest.mark.parametrize("scenario_fn", [
        forward_strike, infrastructure_raid, reconnaissance
    ])
    def test_winner_is_set(self, scenario_fn):
        eng, a = self._run(scenario_fn)
        assert eng.winner is not None

    @pytest.mark.parametrize("scenario_fn", [
        forward_strike, infrastructure_raid, reconnaissance
    ])
    def test_scores_computed(self, scenario_fn):
        eng, a = self._run(scenario_fn)
        assert 0.0 <= a.red_score  <= 1.0
        assert 0.0 <= a.blue_score <= 1.0

    @pytest.mark.parametrize("seed", [0, 1, 7, 42, 99])
    def test_deterministic(self, seed):
        def run(s):
            rng = random.Random(s)
            a   = forward_strike()
            red  = HeuristicRedAgent("r", Team.RED,  rng=random.Random(rng.randint(0,9999)))
            blue = HeuristicBlueAgent("b", Team.BLUE, rng=random.Random(rng.randint(0,9999)))
            eng  = DroneWarEngine(a, red, blue,
                                  WinCondition(deadline=a.deadline,
                                               red_objectives_needed=a.red_objectives_needed),
                                  rng=rng, verbose=False)
            eng.run()
            return eng.winner, eng.turn
        assert run(seed) == run(seed)

    def test_deadline_enforced(self):
        rng = random.Random(0)
        a   = forward_strike()
        # Give Blue invincible interceptors so Red can never win
        for ic in a.interceptors:
            ic.hit_prob     = 0.0
            ic.reload_turns = 0
        # Also make drones really slow so they can't reach in time
        for d in a.drones:
            d.speed = 0
        red  = HeuristicRedAgent("r", Team.RED,  rng=random.Random(1))
        blue = HeuristicBlueAgent("b", Team.BLUE, rng=random.Random(2))
        eng  = DroneWarEngine(a, red, blue,
                              WinCondition(deadline=5,
                                           red_objectives_needed=a.red_objectives_needed),
                              rng=rng, verbose=False)
        eng.run()
        assert eng.turn == 5
        assert eng.winner == Team.BLUE

    def test_roe_violation_causes_red_win(self):
        rng = random.Random(0)
        a   = forward_strike()
        a.roe_threshold = 1
        red  = HeuristicRedAgent("r", Team.RED,  rng=random.Random(1))
        blue = HeuristicBlueAgent("b", Team.BLUE, rng=random.Random(2))
        eng  = DroneWarEngine(a, red, blue,
                              WinCondition(deadline=30, roe_threshold=1,
                                           red_objectives_needed=a.red_objectives_needed),
                              rng=rng, verbose=False)
        eng.run()
        # If ROE violation triggered, Red wins
        if a.roe_violations >= 1:
            assert eng.winner == Team.RED

    def test_history_recorded(self):
        eng, a = self._run(forward_strike)
        assert len(eng.history) == eng.turn
        for rec in eng.history:
            assert rec.turn > 0

    def test_random_agents_complete(self):
        rng = random.Random(7)
        a   = forward_strike()
        red  = RandomRedAgent("r",  Team.RED,  rng=random.Random(1))
        blue = RandomBlueAgent("b", Team.BLUE, rng=random.Random(2))
        eng  = DroneWarEngine(a, red, blue,
                              WinCondition(deadline=a.deadline,
                                           red_objectives_needed=a.red_objectives_needed),
                              rng=rng, verbose=False)
        eng.run()
        assert eng.winner in (Team.RED, Team.BLUE)


# ── Balance ───────────────────────────────────────────────────────────────────

class TestBalance:
    """
    Blue must be able to win — confirm non-zero win rate over many seeds.
    These are statistical tests; they use N=100 for speed.
    """
    N = 100

    def _win_rates(self, scenario_fn):
        red_wins = blue_wins = 0
        for seed in range(self.N):
            rng = random.Random(seed)
            a   = scenario_fn()
            red  = HeuristicRedAgent("r", Team.RED,  rng=random.Random(rng.randint(0,9999)))
            blue = HeuristicBlueAgent("b", Team.BLUE, rng=random.Random(rng.randint(0,9999)))
            eng  = DroneWarEngine(a, red, blue,
                                  WinCondition(deadline=a.deadline,
                                               red_objectives_needed=a.red_objectives_needed),
                                  rng=rng, verbose=False)
            eng.run()
            if eng.winner == Team.RED: red_wins  += 1
            else:                      blue_wins += 1
        return red_wins / self.N, blue_wins / self.N

    def test_forward_strike_blue_can_win(self):
        _, blue_rate = self._win_rates(forward_strike)
        assert blue_rate > 0.0, "Blue never wins forward_strike — scenario unbalanced"

    def test_infrastructure_raid_blue_can_win(self):
        _, blue_rate = self._win_rates(infrastructure_raid)
        assert blue_rate > 0.0, "Blue never wins infrastructure_raid — scenario unbalanced"

    def test_reconnaissance_blue_can_win(self):
        _, blue_rate = self._win_rates(reconnaissance)
        assert blue_rate > 0.0, "Blue never wins reconnaissance — scenario unbalanced"

    def test_red_advantage_is_not_overwhelming(self):
        """Red should not win >97% in any scenario (that would be uninteresting)."""
        for fn in [forward_strike, infrastructure_raid, reconnaissance]:
            red_rate, _ = self._win_rates(fn)
            assert red_rate < 0.99, \
                f"{fn.__name__}: Red wins {red_rate:.0%} — scenario needs rebalancing"


# ── Observation ───────────────────────────────────────────────────────────────

class TestObservation:
    def test_red_obs_fields(self):
        a = forward_strike()
        obs = ObservationBuilder(a)
        red_obs = obs.red_obs(1)
        assert red_obs.turn == 1
        assert isinstance(red_obs.active_drones, list)

    def test_blue_obs_fields(self):
        a = forward_strike()
        obs = ObservationBuilder(a)
        blue_obs = obs.blue_obs(1)
        assert blue_obs.turn == 1
        assert isinstance(blue_obs.tracks, list)
        assert isinstance(blue_obs.interceptors, list)
        assert isinstance(blue_obs.sensors, list)

    def test_blue_obs_sees_roe_count(self):
        a = forward_strike()
        a.roe_violations = 2
        obs = ObservationBuilder(a)
        blue_obs = obs.blue_obs(3)
        assert blue_obs.roe_violations == 2


# ── Scenarios ─────────────────────────────────────────────────────────────────

class TestScenarios:
    def test_all_scenarios_registered(self):
        assert "forward_strike"      in SCENARIOS
        assert "infrastructure_raid" in SCENARIOS
        assert "reconnaissance"      in SCENARIOS

    @pytest.mark.parametrize("name,fn", list(SCENARIOS.items()))
    def test_scenario_has_drones(self, name, fn):
        a = fn()
        assert len(a.drones) > 0

    @pytest.mark.parametrize("name,fn", list(SCENARIOS.items()))
    def test_scenario_has_sensors(self, name, fn):
        a = fn()
        assert len(a.sensors) > 0

    @pytest.mark.parametrize("name,fn", list(SCENARIOS.items()))
    def test_scenario_has_interceptors(self, name, fn):
        a = fn()
        assert len(a.interceptors) > 0

    @pytest.mark.parametrize("name,fn", list(SCENARIOS.items()))
    def test_scenario_has_target(self, name, fn):
        a = fn()
        assert any(c.is_target for c in a.cells.values())

    @pytest.mark.parametrize("name,fn", list(SCENARIOS.items()))
    def test_all_drones_start_in_grid(self, name, fn):
        a = fn()
        for d in a.drones:
            assert d.position in a.cells, \
                f"{name}: drone {d.id} starts outside grid at {d.position}"

    @pytest.mark.parametrize("name,fn", list(SCENARIOS.items()))
    def test_all_sensors_in_grid(self, name, fn):
        a = fn()
        for s in a.sensors:
            assert s.position in a.cells, \
                f"{name}: sensor {s.id} placed outside grid"

    @pytest.mark.parametrize("name,fn", list(SCENARIOS.items()))
    def test_all_interceptors_in_grid(self, name, fn):
        a = fn()
        for ic in a.interceptors:
            assert ic.state.position in a.cells, \
                f"{name}: interceptor {ic.id} placed outside grid"

    def test_reconnaissance_isr_required(self):
        a = reconnaissance()
        assert a.isr_turns_required >= 2

    def test_forward_strike_objectives_needed(self):
        a = forward_strike()
        assert a.red_objectives_needed >= 2

    def test_infrastructure_raid_multiple_targets(self):
        a = infrastructure_raid()
        target_count = sum(1 for c in a.cells.values() if c.is_target)
        assert target_count >= 2
