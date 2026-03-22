"""
scenarios/scenarios.py
======================
Three DroneWar scenarios.

Forward Strike    — FPV swarm vs point defence  (attrition focus)
Infrastructure Raid — loitering munition vs layered C-UAS  (layered defence)
Reconnaissance    — ISR penetration vs EW/intercept  (HMT + EW focus)
"""

from __future__ import annotations

from dronewar.env.airspace import (
    Airspace, HexCell, Drone, DroneRole, DroneState, DroneStatus,
    Sensor, SensorType, SensorState,
    Interceptor, InterceptorType, InterceptorState,
    TerrainType, AutonomyLevel,
)


# ── Shared helpers ─────────────────────────────────────────────────────────

def _drone(drone_id, role, pos, speed=2, rcs=0.35,
           autonomy=AutonomyLevel.SEMI, cost=1) -> Drone:
    d = Drone(id=drone_id, role=role, speed=speed, rcs=rcs,
              autonomy=autonomy, cost=cost)
    d.state = DroneState(position=pos)
    return d

def _sensor(sensor_id, stype, pos, rng=4, prob=0.75) -> Sensor:
    s = Sensor(id=sensor_id, sensor_type=stype, position=pos,
               range=rng, base_prob=prob)
    return s

def _interceptor(iid, itype, pos, rng=3, hit=0.70,
                 reload=2, autonomy=AutonomyLevel.SEMI) -> Interceptor:
    i = Interceptor(id=iid, intercept_type=itype, range=rng,
                    hit_prob=hit, reload_turns=reload)
    i.state = InterceptorState(position=pos, autonomy=autonomy)
    return i


# ── Scenario 1: Forward Strike ─────────────────────────────────────────────

def forward_strike() -> Airspace:
    """
    Ukraine-style FPV swarm (6 drones) assaults a point defence position.
    Red: 4× strike FPVs + 1× EW drone + 1× decoy
    Blue: 3× kinetic interceptors + 1× net + 3× sensors
    Grid radius: 9 (gives Blue 3+ turns to detect and engage)
    Deadline: 20 turns
    Focus: attrition vs swarm saturation
    """
    a = Airspace(name="Forward Strike", radius=11, deadline=24,
                 red_budget=10, blue_budget=8)
    a.build_grid()

    # Terrain: open with some urban clutter mid-field
    for coord in [(-1,0),(0,-1),(1,-1),(0,0),(-1,1),(1,0)]:
        if coord in a.cells:
            a.cells[coord].terrain = TerrainType.URBAN

    # Red base (south), three target cells spread across north (Blue HQ cluster)
    a.cells[( 0, 11)].is_red_base = True
    for coord in [(-1,-10),(0,-10),(1,-10)]:
        a.cells[coord].is_target = True
    a.cells[( 0,-10)].is_blue_hq = True

    # Red drones — each strike drone has its own target offset
    a.drones = [
        _drone("fpv_1",  DroneRole.STRIKE, ( 0, 10), speed=1, rcs=0.25),
        _drone("fpv_2",  DroneRole.STRIKE, ( 1, 10), speed=1, rcs=0.25),
        _drone("fpv_3",  DroneRole.STRIKE, (-1, 10), speed=1, rcs=0.25),
        _drone("fpv_4",  DroneRole.STRIKE, ( 0,  9), speed=1, rcs=0.25),
        _drone("ew_1",   DroneRole.EW,     ( 0, 10), speed=1, rcs=0.40),
        _drone("decoy_1",DroneRole.DECOY,  ( 1,  9), speed=1, rcs=0.50),
    ]

    # Blue sensors — forward-deployed to detect early
    a.sensors = [
        _sensor("radar_1", SensorType.RADAR,   ( 0,  3), rng=6, prob=0.85),
        _sensor("radar_2", SensorType.RADAR,   ( 3,  0), rng=5, prob=0.80),
        _sensor("opt_1",   SensorType.OPTICAL, (-3,  0), rng=4, prob=0.70),
    ]

    # Blue interceptors — spread across depth for layered defence
    a.interceptors = [
        _interceptor("kinetic_1", InterceptorType.KINETIC, ( 0,  1), rng=5, hit=0.72, reload=1),
        _interceptor("kinetic_2", InterceptorType.KINETIC, ( 2, -1), rng=5, hit=0.68, reload=1),
        _interceptor("kinetic_3", InterceptorType.KINETIC, (-2, -1), rng=5, hit=0.68, reload=1),
        _interceptor("kinetic_4", InterceptorType.KINETIC, ( 1, -5), rng=5, hit=0.70, reload=1),
        _interceptor("net_1",     InterceptorType.NET,     ( 0, -4), rng=3, hit=0.62),
    ]

    # Red needs 2 drones to reach objectives (saturate the defence)
    a.red_objectives_needed = 2
    a.roe_threshold = 8
    return a


# ── Scenario 2: Infrastructure Raid ───────────────────────────────────────

def infrastructure_raid() -> Airspace:
    """
    Loitering munition (Shahed-style) penetrates layered C-UAS to reach
    three infrastructure targets. Red needs to hit ANY ONE.
    Red: 3× loitering strike + 1× EW + 2× decoys
    Blue: 3× kinetic + 1× laser + 4× sensors (radar + passive)
    Grid radius: 10
    Deadline: 25 turns
    Focus: layered C-UAS, prioritisation under saturation
    """
    a = Airspace(name="Infrastructure Raid", radius=10, deadline=25,
                 red_budget=12, blue_budget=10)
    a.build_grid()

    # Mixed terrain — urban corridor, forest flanks, mountains blocking LOS
    for q in range(-4, 5):
        if (q, 0) in a.cells:
            a.cells[(q, 0)].terrain = TerrainType.URBAN
    for q in range(-6, -2):
        if (q, 4) in a.cells:
            a.cells[(q, 4)].terrain = TerrainType.FOREST
    for coord in [(4,-3),(-4,-3),(3,-4),(-3,-4)]:
        if coord in a.cells:
            a.cells[coord].terrain = TerrainType.MOUNTAIN

    # Three infrastructure targets
    for coord in [(-3,-7),(0,-8),(3,-7)]:
        if coord in a.cells:
            a.cells[coord].is_target = True

    a.cells[(0, 10)].is_red_base = True

    # Red drones — slow loitering munitions
    a.drones = [
        _drone("loit_1", DroneRole.STRIKE, (-1, 9), speed=1, rcs=0.30,
               autonomy=AutonomyLevel.SEMI),
        _drone("loit_2", DroneRole.STRIKE, ( 0, 9), speed=1, rcs=0.30,
               autonomy=AutonomyLevel.SEMI),
        _drone("loit_3", DroneRole.STRIKE, ( 1, 9), speed=1, rcs=0.30,
               autonomy=AutonomyLevel.SEMI),
        _drone("ew_1",   DroneRole.EW,     ( 0, 9), speed=1, rcs=0.45),
        _drone("dec_1",  DroneRole.DECOY,  (-2, 9), speed=1, rcs=0.55),
        _drone("dec_2",  DroneRole.DECOY,  ( 2, 8), speed=1, rcs=0.55),
    ]

    # Blue layered defence — outer ring, mid ring, inner
    a.sensors = [
        _sensor("radar_out_1", SensorType.RADAR,   ( 0,  5), rng=7, prob=0.85),
        _sensor("radar_out_2", SensorType.RADAR,   ( 4,  2), rng=6, prob=0.80),
        _sensor("passive_1",   SensorType.PASSIVE,  (-4,  2), rng=6, prob=0.65),
        _sensor("opt_inner",   SensorType.OPTICAL,  ( 0, -2), rng=4, prob=0.75),
    ]

    a.interceptors = [
        _interceptor("kin_out_1", InterceptorType.KINETIC, ( 3,  4), rng=6, hit=0.65, reload=1),
        _interceptor("kin_out_2", InterceptorType.KINETIC, (-3,  4), rng=6, hit=0.65, reload=1),
        _interceptor("laser_mid", InterceptorType.LASER,   ( 0,  1), rng=5, hit=0.82,
                     reload=3),
        _interceptor("kin_inner", InterceptorType.KINETIC, ( 0, -4), rng=4, hit=0.75, reload=1),
        _interceptor("kin_flank", InterceptorType.KINETIC, ( 4, -2), rng=5, hit=0.68, reload=1),
    ]

    # Red needs 1 objective — but 3 targets spread Blue's defence
    a.red_objectives_needed = 1
    a.roe_threshold = 8
    return a


# ── Scenario 3: Reconnaissance ─────────────────────────────────────────────

def reconnaissance() -> Airspace:
    """
    Small ISR package (2 drones) must reach and survive in target zone
    for 3 turns against EW-heavy Blue defence.
    Red: 2× ISR (low RCS, high autonomy) + 1× EW support
    Blue: 2× kinetic + 1× RF-kill + 3× sensors (radar + passive)
    Grid radius: 9
    Deadline: 22 turns
    Focus: HMT autonomy dial + EW interplay
    """
    a = Airspace(name="Reconnaissance", radius=9, deadline=22,
                 red_budget=8, blue_budget=8,
                 weather=0.25)
    a.isr_turns_required = 3
    a.build_grid()

    # Forest corridors give cover but optical also degraded
    for coord in [(-1,3),(0,3),(1,3),(-2,2),(2,2),
                  (-1,-2),(0,-2),(1,-2),(-2,-1),(2,-1)]:
        if coord in a.cells:
            a.cells[coord].terrain = TerrainType.FOREST

    a.cells[( 0,  9)].is_red_base = True
    a.cells[( 0, -5)].is_target   = True

    # Red ISR package — very low RCS
    a.drones = [
        _drone("isr_1", DroneRole.ISR, ( 0,  8), speed=2, rcs=0.12,
               autonomy=AutonomyLevel.AUTONOMOUS, cost=2),
        _drone("isr_2", DroneRole.ISR, ( 1,  8), speed=2, rcs=0.12,
               autonomy=AutonomyLevel.AUTONOMOUS, cost=2),
        _drone("ew_1",  DroneRole.EW,  ( 0,  8), speed=1, rcs=0.40,
               autonomy=AutonomyLevel.SUPERVISED),
    ]

    # Blue: forward radar + passive flanks + RF-kill inner
    a.sensors = [
        _sensor("radar_1",   SensorType.RADAR,   ( 0,  2), rng=6, prob=0.80),
        _sensor("passive_1", SensorType.PASSIVE,  (-3,  1), rng=5, prob=0.70),
        _sensor("passive_2", SensorType.PASSIVE,  ( 3,  1), rng=5, prob=0.70),
    ]

    a.interceptors = [
        _interceptor("kin_1",    InterceptorType.KINETIC,  (-2,  0), rng=5, hit=0.65),
        _interceptor("kin_2",    InterceptorType.KINETIC,  ( 2,  0), rng=5, hit=0.65),
        _interceptor("rf_kill_1",InterceptorType.RF_KILL,  ( 0, -2), rng=4, hit=0.60,
                     autonomy=AutonomyLevel.SUPERVISED),
        _interceptor("kin_3",    InterceptorType.KINETIC,  ( 0,  3), rng=5, hit=0.68),
    ]

    # Red needs both ISR drones to complete zone dwell (harder to achieve)
    a.red_objectives_needed = 2
    a.roe_threshold = 4
    return a


# ── Scenario registry ──────────────────────────────────────────────────────

SCENARIOS = {
    "forward_strike":      forward_strike,
    "infrastructure_raid": infrastructure_raid,
    "reconnaissance":      reconnaissance,
}
