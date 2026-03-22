"""
agents/agents.py
================
Heuristic and random agents for DroneWar.

RedAgent strategy
-----------------
  HeuristicRed:
    - EW drones: activate jammer on turn 1, hold position near entry
    - Decoys: advance directly toward target (absorb intercepts)
    - Strike/ISR: advance behind decoy screen; use EW coverage
    - Spoof if budget allows and Blue has many tracks

BlueAgent strategy
------------------
  HeuristicBlue:
    - Each turn: engage highest-confidence track within range
    - Prioritise STRIKE drones over DECOY (if role inferrable from track count)
    - Reposition interceptors if no targets in range
    - Suppress EW drones when detected
"""

from __future__ import annotations

import random
from typing import List

from dronewar.env.airspace import (
    Airspace, Drone, DroneRole, DroneStatus, DroneState,
    Interceptor, Team, AutonomyLevel,
    hex_distance, shortest_path,
)
from dronewar.env.actions import (
    RedAction, BlueAction, RedActionType, BlueActionType,
    RED_ACTION_COSTS, BLUE_ACTION_COSTS,
)
from dronewar.env.observation import RedObservation, BlueObservation


class BaseAgent:
    def __init__(self, agent_id: str, team: Team, rng: random.Random):
        self.agent_id = agent_id
        self.team     = team
        self.rng      = rng

    def act(self, obs, airspace: Airspace) -> list:
        raise NotImplementedError


# ── Random agents ──────────────────────────────────────────────────────────

class RandomRedAgent(BaseAgent):
    def __init__(self, agent_id: str, team: Team, rng: random.Random):
        super().__init__(agent_id, team, rng)

    def act(self, obs: RedObservation, airspace: Airspace) -> List[RedAction]:
        actions = []
        budget  = airspace.red_budget
        target_cells = [c for c in airspace.all_cells() if c.is_target]
        if not target_cells:
            return []

        for d in airspace.active_drones():
            if budget <= 0:
                break
            cost = RED_ACTION_COSTS[RedActionType.MOVE]
            if budget >= cost:
                actions.append(RedAction(
                    action_type = RedActionType.MOVE,
                    drone_ids   = [d.id],
                    target      = min(target_cells,
                                      key=lambda c: hex_distance(d.position, c.coord)).coord,
                    cost        = cost,
                ))
                budget -= cost
        return actions


class RandomBlueAgent(BaseAgent):
    def __init__(self, agent_id: str, team: Team, rng: random.Random):
        super().__init__(agent_id, team, rng)

    def act(self, obs: BlueObservation, airspace: Airspace) -> List[BlueAction]:
        actions = []
        budget  = airspace.blue_budget
        tracks  = list(airspace.tracks.values())

        for interceptor in airspace.available_interceptors():
            if not tracks or budget <= 0:
                break
            track = self.rng.choice(tracks)
            cost  = BLUE_ACTION_COSTS[BlueActionType.ENGAGE]
            if budget >= cost:
                actions.append(BlueAction(
                    action_type    = BlueActionType.ENGAGE,
                    interceptor_id = interceptor.id,
                    track_id       = track.track_id,
                    cost           = cost,
                ))
                budget -= cost
        return actions


# ── Heuristic Red ──────────────────────────────────────────────────────────

class HeuristicRedAgent(BaseAgent):
    def __init__(self, agent_id: str, team: Team, rng: random.Random):
        super().__init__(agent_id, team, rng)

    def act(self, obs: RedObservation, airspace: Airspace) -> List[RedAction]:
        actions = []
        budget  = airspace.red_budget

        target_cells = [c for c in airspace.all_cells() if c.is_target]
        if not target_cells:
            return []

        active = airspace.active_drones()

        # Step 1: Activate EW jammers (once per game)
        for d in active:
            if d.role == DroneRole.EW and not d.state.jammer_active:
                cost = RED_ACTION_COSTS[RedActionType.ACTIVATE_EW]
                if budget >= cost:
                    actions.append(RedAction(
                        action_type = RedActionType.ACTIVATE_EW,
                        drone_ids   = [d.id],
                        cost        = cost,
                    ))
                    budget -= cost

        # Step 2: Spoof once — only if no spoofed track already exists
        has_spoof = any(t.is_spoofed for t in airspace.tracks.values())
        if not has_spoof and budget >= 2 and len(airspace.tracks) < 4:
            spoof_target = self.rng.choice(target_cells).coord
            actions.append(RedAction(
                action_type = RedActionType.SPOOF,
                drone_ids   = [],
                target      = spoof_target,
                cost        = 2,
            ))
            budget -= 2

        def nearest_target(drone):
            return min(target_cells,
                       key=lambda c: hex_distance(drone.position, c.coord)).coord

        # Step 3: Move decoys first (they absorb intercepts)
        decoys = [d for d in active if d.role == DroneRole.DECOY]
        for d in decoys:
            cost = RED_ACTION_COSTS[RedActionType.MOVE]
            if budget >= cost:
                actions.append(RedAction(
                    action_type = RedActionType.MOVE,
                    drone_ids   = [d.id],
                    target      = nearest_target(d),
                    cost        = cost,
                ))
                budget -= cost

        # Step 4: Move strike/ISR drones toward their nearest target
        priority = [d for d in active
                    if d.role in (DroneRole.STRIKE, DroneRole.ISR)]
        for d in priority:
            cost = RED_ACTION_COSTS[RedActionType.MOVE]
            if budget >= cost:
                actions.append(RedAction(
                    action_type = RedActionType.MOVE,
                    drone_ids   = [d.id],
                    target      = nearest_target(d),
                    cost        = cost,
                ))
                budget -= cost

        # Step 5: Move EW drones (slowly — maintain jamming coverage)
        ew_drones = [d for d in active if d.role == DroneRole.EW]
        for d in ew_drones:
            cost = RED_ACTION_COSTS[RedActionType.MOVE]
            if budget >= cost and self.rng.random() < 0.5:
                actions.append(RedAction(
                    action_type = RedActionType.MOVE,
                    drone_ids   = [d.id],
                    target      = nearest_target(d),
                    cost        = cost,
                ))
                budget -= cost

        return actions


# ── Heuristic Blue ─────────────────────────────────────────────────────────

class HeuristicBlueAgent(BaseAgent):
    def __init__(self, agent_id: str, team: Team, rng: random.Random):
        super().__init__(agent_id, team, rng)

    def act(self, obs: BlueObservation, airspace: Airspace) -> List[BlueAction]:
        actions = []
        budget  = airspace.blue_budget
        tracks  = list(airspace.tracks.values())

        target_cell = next((c for c in airspace.all_cells() if c.is_target), None)

        # ── Step 0: Clear only confirmed spoofed or very stale tracks ────────
        # Only flush tracks explicitly flagged spoofed or aged ≥ 3 turns.
        # Do NOT flush low-confidence tracks — those are real drones in clutter.
        for track in list(tracks):
            if budget <= 0:
                break
            if track.is_spoofed or track.age >= 3:
                cost = BLUE_ACTION_COSTS[BlueActionType.CLEAR_TRACK]
                if budget >= cost:
                    actions.append(BlueAction(
                        action_type = BlueActionType.CLEAR_TRACK,
                        track_id    = track.track_id,
                        cost        = cost,
                    ))
                    budget -= cost
                    tracks.remove(track)

        # ── Priority sort: closest to target, highest confidence, not spoofed ─
        def track_priority(t):
            dist = hex_distance(t.position, target_cell.coord) if target_cell else 99
            return (t.is_spoofed, dist, -t.confidence)
        tracks.sort(key=track_priority)

        # ── Step 1: Engage best available target ─────────────────────────────
        for interceptor in airspace.available_interceptors():
            if budget <= 0:
                break
            engaged = False
            for track in tracks:
                dist = hex_distance(interceptor.state.position, track.position)
                if dist > interceptor.range:
                    continue
                if not airspace.los_clear(interceptor.state.position,
                                          track.position):
                    continue
                cost = BLUE_ACTION_COSTS[BlueActionType.ENGAGE]
                if budget >= cost:
                    actions.append(BlueAction(
                        action_type    = BlueActionType.ENGAGE,
                        interceptor_id = interceptor.id,
                        track_id       = track.track_id,
                        cost           = cost,
                    ))
                    budget -= cost
                    engaged = True
                    break

            # ── Step 2: Reposition toward threat if no shot available ─────────
            if not engaged and tracks and budget >= 1:
                # Move toward track closest to target (highest priority threat)
                nearest = tracks[0]
                path = shortest_path(interceptor.state.position,
                                     nearest.position,
                                     airspace.cells, speed=2)
                if path:
                    actions.append(BlueAction(
                        action_type    = BlueActionType.REPOSITION,
                        interceptor_id = interceptor.id,
                        target         = path[-1],
                        cost           = 1,
                    ))
                    budget -= 1

        # ── Step 3: Suppress EW drones ────────────────────────────────────────
        ew_tracks = [t for t in tracks
                     if any(d.role == DroneRole.EW and d.position == t.position
                            for d in airspace.active_drones())]
        for t in ew_tracks:
            cost = BLUE_ACTION_COSTS[BlueActionType.SUPPRESS_EW]
            if budget < cost:
                break
            actions.append(BlueAction(
                action_type = BlueActionType.SUPPRESS_EW,
                track_id    = t.track_id,
                cost        = cost,
            ))
            budget -= cost

        return actions
