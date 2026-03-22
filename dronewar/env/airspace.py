"""
env/airspace.py
===============
Airspace environment for DroneWar.

Coordinate system: axial hex (q, r).
  Neighbours of (q,r): (q+1,r),(q-1,r),(q,r+1),(q,r-1),(q+1,r-1),(q-1,r+1)
  Distance: max(|dq|,|dr|,|dq+dr|)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


# ── Enums ──────────────────────────────────────────────────────────────────

class Team(Enum):
    RED  = "red"
    BLUE = "blue"

class DroneRole(Enum):
    STRIKE = "strike"   # reach target cell
    ISR    = "isr"      # survive N turns in target zone
    DECOY  = "decoy"    # absorb Blue intercepts
    EW     = "ew"       # jammer payload, degrade Blue sensors

class DroneStatus(Enum):
    ACTIVE    = "active"
    DESTROYED = "destroyed"
    RTB       = "rtb"
    OBJECTIVE = "objective"

class SensorType(Enum):
    RADAR   = "radar"
    OPTICAL = "optical"
    PASSIVE = "passive"

class InterceptorType(Enum):
    KINETIC = "kinetic"
    NET     = "net"
    LASER   = "laser"
    RF_KILL = "rf_kill"

class TerrainType(Enum):
    OPEN     = "open"
    URBAN    = "urban"
    FOREST   = "forest"
    WATER    = "water"
    MOUNTAIN = "mountain"

class AutonomyLevel(Enum):
    SUPERVISED = 0   # costs 1 Blue action token each turn
    SEMI       = 1   # free; ROE compliance 85% probabilistic
    AUTONOMOUS = 2   # free; ROE violations can end game


# ── Hex geometry ───────────────────────────────────────────────────────────

def hex_distance(a: Tuple[int,int], b: Tuple[int,int]) -> int:
    dq, dr = b[0]-a[0], b[1]-a[1]
    return max(abs(dq), abs(dr), abs(dq+dr))

def hex_neighbours(q: int, r: int) -> List[Tuple[int,int]]:
    return [(q+1,r),(q-1,r),(q,r+1),(q,r-1),(q+1,r-1),(q-1,r+1)]

def hex_disk(center: Tuple[int,int], radius: int) -> List[Tuple[int,int]]:
    """All cells within radius steps (inclusive)."""
    cq, cr = center
    out = []
    for dq in range(-radius, radius+1):
        r_lo = max(-radius, -dq-radius)
        r_hi = min( radius, -dq+radius)
        for dr in range(r_lo, r_hi+1):
            out.append((cq+dq, cr+dr))
    return out

def hex_line(a: Tuple[int,int], b: Tuple[int,int]) -> List[Tuple[int,int]]:
    """Hex cells on line from a to b (for LOS checks)."""
    n = hex_distance(a, b)
    if n == 0:
        return [a]
    results = []
    for i in range(n+1):
        t = i/n
        fq = a[0] + (b[0]-a[0])*t
        fr = a[1] + (b[1]-a[1])*t
        fc = -fq - fr
        rq, rr, rc = round(fq), round(fr), round(fc)
        dq2, dr2, dc2 = abs(rq-fq), abs(rr-fr), abs(rc-fc)
        if dq2 > dr2 and dq2 > dc2:
            rq = -rr - rc
        elif dr2 > dc2:
            rr = -rq - rc
        results.append((rq, rr))
    return results

def shortest_path(start: Tuple[int,int], goal: Tuple[int,int],
                  cells: Dict[Tuple[int,int], "HexCell"],
                  speed: int) -> List[Tuple[int,int]]:
    """
    BFS shortest path on the hex grid, respecting bounds.
    Returns list of coords from start (exclusive) to goal (inclusive),
    capped at `speed` steps.
    """
    if start == goal:
        return []
    from collections import deque
    queue = deque([(start, [start])])
    visited = {start}
    while queue:
        pos, path = queue.popleft()
        for nb in hex_neighbours(*pos):
            if nb not in cells:
                continue
            if nb in visited:
                continue
            new_path = path + [nb]
            if nb == goal:
                return new_path[1:1+speed]   # skip start, take up to speed steps
            visited.add(nb)
            queue.append((nb, new_path))
    # goal unreachable — move toward it greedily
    q, r = start
    gq, gr = goal
    dq, dr = gq-q, gr-r
    step = (max(-1,min(1,dq)), max(-1,min(1,dr)))
    candidate = (q+step[0], r+step[1])
    if candidate in cells:
        return [candidate]
    return []


# ── HexCell ────────────────────────────────────────────────────────────────

@dataclass
class HexCell:
    q:           int
    r:           int
    terrain:     TerrainType = TerrainType.OPEN
    rf_noise:    float       = 0.0
    is_target:   bool        = False
    is_red_base: bool        = False
    is_blue_hq:  bool        = False

    @property
    def coord(self) -> Tuple[int,int]:
        return (self.q, self.r)

    @property
    def radar_clutter(self) -> float:
        return {TerrainType.OPEN:0.00, TerrainType.URBAN:0.30,
                TerrainType.FOREST:0.15, TerrainType.WATER:0.20,
                TerrainType.MOUNTAIN:0.10}[self.terrain]

    @property
    def blocks_los(self) -> bool:
        return self.terrain == TerrainType.MOUNTAIN


# ── Drone ──────────────────────────────────────────────────────────────────

@dataclass
class DroneState:
    position:      Tuple[int,int]
    status:        DroneStatus  = DroneStatus.ACTIVE
    health:        float        = 1.0
    turns_in_zone: int          = 0
    jammer_active: bool         = False
    jammer_range:  int          = 2
    suppressed:    bool         = False

@dataclass
class Drone:
    id:       str
    role:     DroneRole
    speed:    int           = 2
    rcs:      float         = 0.35
    autonomy: AutonomyLevel = AutonomyLevel.SEMI
    cost:     int           = 1
    state:    DroneState    = field(default_factory=lambda: DroneState((0,0)))

    @property
    def is_active(self) -> bool:
        return self.state.status == DroneStatus.ACTIVE

    @property
    def position(self) -> Tuple[int,int]:
        return self.state.position


# ── Sensor ─────────────────────────────────────────────────────────────────

@dataclass
class SensorState:
    operational: bool = True
    suppressed:  bool = False
    cooldown:    int  = 0

@dataclass
class Sensor:
    id:          str
    sensor_type: SensorType
    position:    Tuple[int,int]
    range:       int   = 4
    base_prob:   float = 0.75
    state:       SensorState = field(default_factory=SensorState)

    def detection_prob(self, drone: Drone, cell: HexCell,
                       jam_level: float, weather: float) -> float:
        if not self.state.operational or self.state.suppressed:
            return 0.0
        d = hex_distance(self.position, cell.coord)
        if d > self.range:
            return 0.0
        p = self.base_prob
        p *= 1.0 - (d / self.range) * 0.4
        p *= drone.rcs
        p *= (1.0 - cell.radar_clutter)
        if self.sensor_type in (SensorType.RADAR, SensorType.PASSIVE):
            p *= (1.0 - jam_level * 0.65)
        if self.sensor_type == SensorType.OPTICAL:
            p *= (1.0 - weather * 0.55)
        return max(0.0, min(1.0, p))


# ── Interceptor ────────────────────────────────────────────────────────────

@dataclass
class InterceptorState:
    position:  Tuple[int,int]
    available: bool          = True
    cooldown:  int           = 0
    autonomy:  AutonomyLevel = AutonomyLevel.SEMI

@dataclass
class Interceptor:
    id:             str
    intercept_type: InterceptorType
    range:          int   = 3
    hit_prob:       float = 0.70
    reload_turns:   int   = 2
    cost_per_shot:  int   = 1
    state:          InterceptorState = field(
        default_factory=lambda: InterceptorState((0,0)))

    @property
    def is_available(self) -> bool:
        return self.state.available and self.state.cooldown == 0

    def effective_hit_prob(self, drone: Drone, jam_level: float) -> float:
        base = self.hit_prob
        if self.intercept_type == InterceptorType.KINETIC:
            # Missiles are EW-immune; very low RCS slightly harder to guide
            return max(0.15, base - (1.0 - drone.rcs) * 0.08)
        if self.intercept_type == InterceptorType.LASER:
            # Directed energy: fully EW-immune
            return max(0.20, base)
        # Net / RF-kill: strongly affected by jamming
        return max(0.05, base - jam_level * 0.50)


# ── Track ──────────────────────────────────────────────────────────────────

@dataclass
class Track:
    track_id:   str
    position:   Tuple[int,int]
    confidence: float
    age:        int  = 0
    is_spoofed: bool = False


# ── Airspace ───────────────────────────────────────────────────────────────

@dataclass
class Airspace:
    name:     str
    radius:   int
    deadline: int
    weather:  float = 0.0

    cells:        Dict[Tuple[int,int], HexCell]  = field(default_factory=dict)
    drones:       List[Drone]                     = field(default_factory=list)
    sensors:      List[Sensor]                    = field(default_factory=list)
    interceptors: List[Interceptor]               = field(default_factory=list)
    tracks:       Dict[str, Track]                = field(default_factory=dict)

    red_budget:  int = 10
    blue_budget: int = 6

    roe_violations: int = 0
    roe_threshold:  int = 3

    red_score:  float = 0.0
    blue_score: float = 0.0

    # ISR scenario: drones need this many turns in zone
    isr_turns_required:    int = 3
    # Red needs this many objective completions to win
    red_objectives_needed: int = 1

    def get_cell(self, q: int, r: int) -> Optional[HexCell]:
        return self.cells.get((q, r))

    def all_cells(self) -> List[HexCell]:
        return list(self.cells.values())

    def active_drones(self) -> List[Drone]:
        return [d for d in self.drones if d.is_active]

    def available_interceptors(self) -> List[Interceptor]:
        return [i for i in self.interceptors if i.is_available]

    def in_bounds(self, q: int, r: int) -> bool:
        return (q, r) in self.cells

    def jam_level_at(self, coord: Tuple[int,int]) -> float:
        total = 0.0
        for d in self.active_drones():
            if d.role == DroneRole.EW and d.state.jammer_active:
                dist = hex_distance(d.position, coord)
                if dist <= d.state.jammer_range:
                    total += 1.0 / max(1, dist) ** 0.8
        return min(1.0, total)

    def los_clear(self, a: Tuple[int,int], b: Tuple[int,int]) -> bool:
        for coord in hex_line(a, b)[1:-1]:
            cell = self.cells.get(coord)
            if cell and cell.blocks_los:
                return False
        return True

    def compute_scores(self):
        n = len(self.drones)
        if n == 0:
            return
        self.red_score  = sum(1 for d in self.drones
                              if d.state.status == DroneStatus.OBJECTIVE) / n
        self.blue_score = sum(1 for d in self.drones
                              if d.state.status == DroneStatus.DESTROYED) / n

    def build_grid(self):
        for dq in range(-self.radius, self.radius+1):
            r_lo = max(-self.radius, -dq-self.radius)
            r_hi = min( self.radius, -dq+self.radius)
            for dr in range(r_lo, r_hi+1):
                self.cells[(dq, dr)] = HexCell(q=dq, r=dr)
