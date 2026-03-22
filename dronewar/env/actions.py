"""
env/actions.py
==============
Action definitions and resolution for DroneWar.

Red actions
-----------
  MOVE          — move one or more drones toward target
  ACTIVATE_EW   — switch EW drone jammer on/off
  FORM_SWARM    — group drones into formation (shared speed boost)
  SPLIT_SWARM   — break formation
  SPOOF         — inject false track into Blue's picture
  KAMIKAZE      — sacrifice drone for guaranteed damage if reaches target

Blue actions
------------
  ENGAGE        — fire interceptor at a tracked drone
  REPOSITION    — move interceptor to new cell
  ACTIVATE_SENSOR — toggle sensor (power management)
  SUPPRESS_EW   — attempt to suppress Red EW drone
  CLEAR_TRACK   — remove a spoofed/stale track from picture
  ROE_OVERRIDE  — authorise autonomous engagement (costs no action tokens)
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple

from dronewar.env.airspace import (
    Airspace, Drone, DroneStatus, DroneRole,
    Interceptor, InterceptorType, Sensor, Track,
    AutonomyLevel, Team, hex_distance, shortest_path,
)


# ── Action types ───────────────────────────────────────────────────────────

class RedActionType(Enum):
    MOVE         = "move"
    ACTIVATE_EW  = "activate_ew"
    FORM_SWARM   = "form_swarm"
    SPLIT_SWARM  = "split_swarm"
    SPOOF        = "spoof"
    KAMIKAZE     = "kamikaze"

class BlueActionType(Enum):
    ENGAGE          = "engage"
    REPOSITION      = "reposition"
    ACTIVATE_SENSOR = "activate_sensor"
    SUPPRESS_EW     = "suppress_ew"
    CLEAR_TRACK     = "clear_track"
    ROE_OVERRIDE    = "roe_override"


@dataclass
class RedAction:
    action_type: RedActionType
    drone_ids:   List[str]               # target drone(s)
    target:      Optional[Tuple[int,int]] = None   # target cell for MOVE/SPOOF
    cost:        int = 1

@dataclass
class BlueAction:
    action_type:    BlueActionType
    interceptor_id: Optional[str]         = None
    sensor_id:      Optional[str]         = None
    track_id:       Optional[str]         = None
    target:         Optional[Tuple[int,int]] = None
    cost:           int = 1


# ── Action costs ───────────────────────────────────────────────────────────

RED_ACTION_COSTS = {
    RedActionType.MOVE:        1,
    RedActionType.ACTIVATE_EW: 1,
    RedActionType.FORM_SWARM:  2,
    RedActionType.SPLIT_SWARM: 1,
    RedActionType.SPOOF:       2,
    RedActionType.KAMIKAZE:    0,   # sunk cost — drone already launched
}

BLUE_ACTION_COSTS = {
    BlueActionType.ENGAGE:          1,
    BlueActionType.REPOSITION:      1,
    BlueActionType.ACTIVATE_SENSOR: 1,
    BlueActionType.SUPPRESS_EW:     2,
    BlueActionType.CLEAR_TRACK:     1,
    BlueActionType.ROE_OVERRIDE:    0,   # administrative; costs doctrine not budget
}


# ── Resolution ─────────────────────────────────────────────────────────────

class ActionResolver:
    """
    Resolves actions against the Airspace world.
    Red and Blue actions are collected each turn, then resolved simultaneously:
      1. Red moves (simultaneous)
      2. Blue engages (against post-move positions)
      3. Sensor sweep (update tracks)
      4. Cooldowns / reloads tick down
      5. Win condition check
    """

    def __init__(self, airspace: Airspace, rng: random.Random):
        self.airspace = rng_world = airspace
        self.rng      = rng
        self._log: List[str] = []

    @property
    def log(self) -> List[str]:
        return list(self._log)

    def clear_log(self):
        self._log.clear()

    def _note(self, msg: str):
        self._log.append(msg)

    # ── Red actions ────────────────────────────────────────────────────────

    def resolve_red_move(self, action: RedAction):
        """Move drones one step toward target cell."""
        a = self.airspace
        target = action.target
        if target is None:
            return
        for did in action.drone_ids:
            drone = next((d for d in a.drones if d.id == did), None)
            if drone is None or not drone.is_active:
                continue
            if drone.state.suppressed:
                self._note(f"  {did} suppressed — cannot move")
                drone.state.suppressed = False
                continue
            path = shortest_path(drone.position, target,
                                  a.cells, drone.speed)
            if path:
                drone.state.position = path[-1]
                self._note(f"  {did} → {drone.position}")
            # Check objective
            cell = a.cells.get(drone.position)
            if cell:
                if cell.is_target:
                    if drone.role == DroneRole.STRIKE:
                        drone.state.status = DroneStatus.OBJECTIVE
                        self._note(f"  {did} STRUCK TARGET at {drone.position}")
                    elif drone.role == DroneRole.ISR:
                        drone.state.turns_in_zone += 1
                        if drone.state.turns_in_zone >= a.isr_turns_required:
                            drone.state.status = DroneStatus.OBJECTIVE
                            self._note(f"  {did} ISR COMPLETE")
                    elif drone.role == DroneRole.DECOY:
                        drone.state.status = DroneStatus.OBJECTIVE
                        self._note(f"  {did} decoy reached objective")

    def resolve_activate_ew(self, action: RedAction):
        a = self.airspace
        for did in action.drone_ids:
            drone = next((d for d in a.drones if d.id == did), None)
            if drone and drone.is_active and drone.role == DroneRole.EW:
                drone.state.jammer_active = not drone.state.jammer_active
                state = "ON" if drone.state.jammer_active else "OFF"
                self._note(f"  {did} EW jammer {state}")

    def resolve_spoof(self, action: RedAction):
        """Inject a false track into Blue's air picture."""
        if action.target is None:
            return
        a = self.airspace
        tid = f"spoof_{len(a.tracks)}"
        a.tracks[tid] = Track(
            track_id   = tid,
            position   = action.target,
            confidence = 0.6 + self.rng.random() * 0.3,
            is_spoofed = True,
        )
        self._note(f"  Spoof track injected at {action.target}")

    def resolve_red_actions(self, actions: List[RedAction]):
        for act in actions:
            if act.action_type == RedActionType.MOVE:
                self.resolve_red_move(act)
            elif act.action_type == RedActionType.ACTIVATE_EW:
                self.resolve_activate_ew(act)
            elif act.action_type == RedActionType.SPOOF:
                self.resolve_spoof(act)

    # ── Blue actions ───────────────────────────────────────────────────────

    def resolve_engage(self, action: BlueAction) -> bool:
        """
        Fire an interceptor at a tracked target.
        Returns True if drone destroyed.
        """
        a = self.airspace
        if action.interceptor_id is None or action.track_id is None:
            return False
        interceptor = next((i for i in a.interceptors
                            if i.id == action.interceptor_id), None)
        track = a.tracks.get(action.track_id)
        if interceptor is None or track is None:
            return False
        if not interceptor.is_available:
            self._note(f"  {action.interceptor_id} not available (cooldown)")
            return False
        # Check range
        dist = hex_distance(interceptor.state.position, track.position)
        if dist > interceptor.range:
            self._note(f"  {action.interceptor_id} out of range ({dist}>{interceptor.range})")
            return False
        # Check LOS
        if not a.los_clear(interceptor.state.position, track.position):
            self._note(f"  {action.interceptor_id} no LOS to {track.position}")
            return False

        # ROE check for autonomous assets
        roe_ok = self._roe_check(interceptor, track)
        if not roe_ok:
            a.roe_violations += 1
            self._note(f"  ROE violation #{a.roe_violations}!")

        # Find real drone at track position
        real_drone = next(
            (d for d in a.active_drones() if d.position == track.position),
            None
        )

        jam_level = a.jam_level_at(track.position)
        hit_prob  = interceptor.effective_hit_prob(
            real_drone if real_drone else _dummy_drone(), jam_level)

        # Spoofed track: automatically miss
        if track.is_spoofed:
            hit_prob = 0.0
            self._note(f"  {action.interceptor_id} engaged spoofed track — wasted shot")

        hit = self.rng.random() < hit_prob
        interceptor.state.available = False
        interceptor.state.cooldown  = interceptor.reload_turns

        if hit and real_drone:
            if interceptor.intercept_type in (InterceptorType.NET,
                                               InterceptorType.RF_KILL):
                real_drone.state.suppressed = True
                self._note(f"  {action.interceptor_id} SOFT-KILLED {real_drone.id}")
            else:
                real_drone.state.status = DroneStatus.DESTROYED
                self._note(f"  {action.interceptor_id} KILLED {real_drone.id}")
            del a.tracks[action.track_id]
            return True
        else:
            self._note(f"  {action.interceptor_id} missed")
            return False

    def resolve_suppress_ew(self, action: BlueAction) -> bool:
        """Blue attempts to suppress a Red EW drone via directional RF."""
        a = self.airspace
        if action.track_id is None:
            return False
        track = a.tracks.get(action.track_id)
        if track is None:
            return False
        drone = next((d for d in a.active_drones()
                      if d.position == track.position
                      and d.role == DroneRole.EW), None)
        if drone is None:
            return False
        # Base 50% chance, improved by proximity
        prob = 0.50
        if self.rng.random() < prob:
            drone.state.jammer_active = False
            drone.state.suppressed    = True
            self._note(f"  EW drone {drone.id} suppressed by Blue RF")
            return True
        self._note(f"  Blue RF suppress failed")
        return False

    def resolve_reposition(self, action: BlueAction):
        a = self.airspace
        if action.interceptor_id is None or action.target is None:
            return
        interceptor = next((i for i in a.interceptors
                            if i.id == action.interceptor_id), None)
        if interceptor and a.in_bounds(*action.target):
            interceptor.state.position = action.target
            self._note(f"  {action.interceptor_id} repositioned to {action.target}")

    def resolve_clear_track(self, action: BlueAction):
        a = self.airspace
        if action.track_id and action.track_id in a.tracks:
            del a.tracks[action.track_id]
            self._note(f"  Track {action.track_id} cleared")

    def resolve_blue_actions(self, actions: List[BlueAction]):
        for act in actions:
            if act.action_type == BlueActionType.ENGAGE:
                self.resolve_engage(act)
            elif act.action_type == BlueActionType.REPOSITION:
                self.resolve_reposition(act)
            elif act.action_type == BlueActionType.SUPPRESS_EW:
                self.resolve_suppress_ew(act)
            elif act.action_type == BlueActionType.CLEAR_TRACK:
                self.resolve_clear_track(act)

    # ── Sensor sweep ───────────────────────────────────────────────────────

    def sensor_sweep(self):
        """
        Update Blue's track picture from all operational sensors.
        - Real drones: detected probabilistically → update/create track
        - Existing tracks age out if undetected
        - Spoofed tracks persist until Blue clears them
        """
        a = self.airspace
        detected_drones: set[str] = set()

        for sensor in a.sensors:
            if not sensor.state.operational or sensor.state.suppressed:
                continue
            for drone in a.active_drones():
                cell = a.cells.get(drone.position)
                if cell is None:
                    continue
                if not a.los_clear(sensor.position, drone.position):
                    continue
                jam = a.jam_level_at(drone.position)
                p   = sensor.detection_prob(drone, cell, jam, a.weather)
                if self.rng.random() < p:
                    tid = f"track_{drone.id}"
                    a.tracks[tid] = Track(
                        track_id   = tid,
                        position   = drone.position,
                        confidence = p,
                        age        = 0,
                    )
                    detected_drones.add(drone.id)

        # Age existing real tracks; remove stale ones
        stale = []
        for tid, track in a.tracks.items():
            if track.is_spoofed:
                continue
            drone_id = tid.replace("track_", "")
            if drone_id not in detected_drones:
                track.age += 1
                if track.age > 2:
                    stale.append(tid)
        for tid in stale:
            del a.tracks[tid]

    # ── Cooldown tick ──────────────────────────────────────────────────────

    def tick_cooldowns(self):
        for interceptor in self.airspace.interceptors:
            if interceptor.state.cooldown > 0:
                interceptor.state.cooldown -= 1
                if interceptor.state.cooldown == 0:
                    interceptor.state.available = True

    # ── ROE ────────────────────────────────────────────────────────────────

    def _roe_check(self, interceptor: Interceptor, track: Track) -> bool:
        """
        Return True if engagement is ROE-compliant.
        SUPERVISED: always compliant (human authorised).
        SEMI: 85% compliant.
        AUTONOMOUS: 70% compliant.
        """
        level = interceptor.state.autonomy
        if level == AutonomyLevel.SUPERVISED:
            return True
        elif level == AutonomyLevel.SEMI:
            return self.rng.random() < 0.95
        else:
            return self.rng.random() < 0.70


def _dummy_drone() -> Drone:
    """Placeholder used when track has no real drone underneath."""
    from dronewar.env.airspace import Drone, DroneRole, DroneState, AutonomyLevel
    return Drone(id="_dummy", role=DroneRole.DECOY, rcs=0.35)
