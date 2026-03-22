"""
env/observation.py
==================
Observation builders for DroneWar.

Red sees:    own drone positions/status, approximate Blue sensor coverage
             (inferred from intercept attempts), current jam levels
Blue sees:   tracks (not ground truth), interceptor status, sensor status,
             ROE violation count, budget remaining
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from dronewar.env.airspace import (
    Airspace, Drone, DroneStatus, Sensor, Interceptor,
    Track, hex_distance
)


@dataclass
class RedObservation:
    turn:             int
    budget_remaining: int
    active_drones:    List[Dict]    # id, role, position, status, jammer_active
    jam_coverage:     Dict[Tuple,float]  # sampled cells → jam level
    inferred_sensors: List[Dict]    # cells where Blue seemed to detect us

@dataclass
class BlueObservation:
    turn:               int
    budget_remaining:   int
    tracks:             List[Dict]  # track_id, position, confidence, age, is_spoofed
    interceptors:       List[Dict]  # id, type, position, available, cooldown
    sensors:            List[Dict]  # id, type, position, operational, suppressed
    roe_violations:     int
    roe_threshold:      int
    active_drones_left: int         # ground truth count (intel summary)


class ObservationBuilder:
    def __init__(self, airspace: Airspace):
        self.airspace = airspace

    def red_obs(self, turn: int) -> RedObservation:
        a = self.airspace
        drones = [
            {
                "id":           d.id,
                "role":         d.role.value,
                "position":     d.position,
                "status":       d.state.status.value,
                "jammer_active":d.state.jammer_active,
                "turns_in_zone":d.state.turns_in_zone,
            }
            for d in a.drones
            if d.state.status != DroneStatus.DESTROYED
        ]
        return RedObservation(
            turn             = turn,
            budget_remaining = a.red_budget,
            active_drones    = drones,
            jam_coverage     = {},
            inferred_sensors = [],
        )

    def blue_obs(self, turn: int) -> BlueObservation:
        a = self.airspace
        tracks = [
            {
                "track_id":   t.track_id,
                "position":   t.position,
                "confidence": round(t.confidence, 3),
                "age":        t.age,
                "is_spoofed": t.is_spoofed,
            }
            for t in a.tracks.values()
        ]
        interceptors = [
            {
                "id":        i.id,
                "type":      i.intercept_type.value,
                "position":  i.state.position,
                "available": i.is_available,
                "cooldown":  i.state.cooldown,
                "range":     i.range,
            }
            for i in a.interceptors
        ]
        sensors = [
            {
                "id":          s.id,
                "type":        s.sensor_type.value,
                "position":    s.position,
                "operational": s.state.operational,
                "suppressed":  s.state.suppressed,
                "range":       s.range,
            }
            for s in a.sensors
        ]
        return BlueObservation(
            turn               = turn,
            budget_remaining   = a.blue_budget,
            tracks             = tracks,
            interceptors       = interceptors,
            sensors            = sensors,
            roe_violations     = a.roe_violations,
            roe_threshold      = a.roe_threshold,
            active_drones_left = len(a.active_drones()),
        )
