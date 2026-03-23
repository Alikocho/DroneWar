# DroneWar

> *Swarm. Jam. Intercept. Decide.*

[![CI](https://github.com/Alikocho/DroneWar/actions/workflows/ci.yml/badge.svg)](https://github.com/Alikocho/DroneWar/actions/workflows/ci.yml)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**DroneWar** is an asymmetric multi-agent wargame modelling UAV/drone warfare at the tactical level. Red operates a heterogeneous swarm — strike drones, ISR packages, EW carriers, decoys. Blue commands a layered counter-UAS defence — radar networks, kinetic interceptors, lasers, RF-kill systems.

Both teams operate under partial information. Blue sees *tracks*, not ground truth. Red's EW drone degrades Blue's picture. Autonomous interceptors are faster but risk ROE violations that lose the game. Every decision involves a tradeoff.

---

## Research pillars

| Pillar | Mechanic |
|---|---|
| **Swarm vs attrition** | Red fields 4–6 drones; needs multiple to saturate Blue's intercept capacity |
| **Layered C-UAS** | Blue has outer/mid/inner intercept rings; kinetic, laser, net, RF-kill |
| **Human-machine teaming** | Autonomy dial: supervised (costs action tokens) → semi → autonomous (risks ROE) |
| **Electronic warfare** | Jammer degrades radar/passive sensors; kinetic and laser immune; net/RF-kill heavily affected |

---

## Quickstart

### Download Packaged Release (easiest and runs from desktop)

Mac - https://github.com/Alikocho/DroneWar/releases/download/v.0.1.0/dronewar-mac.zip
Windows - https://github.com/Alikocho/DroneWar/releases/download/v.0.1.0/dronewar.exe

### Browser UI (recommended)
```bash
git clone https://github.com/Alikocho/DroneWar
cd dronewar
pip install -e ".[web]"

python server.py          # opens http://localhost:5000 automatically
```

Pick scenario and agent types on the start screen. AI vs AI watch mode auto-steps at 0.7s/turn.

### CLI (headless / scripting)
```bash
pip install -e .

python main.py --scenario forward_strike
python main.py --scenario infrastructure_raid --seed 7
python main.py --scenario reconnaissance --verbose
python main.py --scenario forward_strike --red heuristic --blue random --seed 42
```

---

## Scenarios

### Forward Strike
FPV swarm assault on a point-defence position. Red needs 2 drones to reach the objective cluster. Blue fields 5 kinetic interceptors across depth. Ukraine-style attrition.

- Grid: radius 11 hex   |   Deadline: 24 turns
- Red: 4× strike FPV + 1× EW + 1× decoy   |   needs 2 objectives
- Blue: 4× kinetic + 1× net

### Infrastructure Raid
Loitering munitions (Shahed-style) penetrate a layered C-UAS system to reach one of three infrastructure targets. Blue must cover all three. Red needs only one.

- Grid: radius 10 hex   |   Deadline: 25 turns
- Red: 3× loitering strike + 1× EW + 2× decoys   |   needs 1 objective
- Blue: 2× outer kinetic + 1× laser (mid) + 1× inner kinetic + 1× flank

### Reconnaissance
A small ISR package must penetrate to a target zone and dwell for 3 turns — long enough to collect intelligence. Blue uses RF-kill and kinetic interceptors. Weather degrades optical sensors.

- Grid: radius 9 hex   |   Deadline: 22 turns
- Red: 2× ISR (very low RCS, autonomous) + 1× EW   |   needs both ISR drones to dwell 3 turns
- Blue: 2× kinetic + 1× RF-kill

---

## Simulation results (300 seeds, heuristic vs heuristic)

| Scenario | Red wins | Blue wins | Avg turns | Primary Red path |
|---|---|---|---|---|
| Forward Strike | 62% | **38%** | 18.7 | objective 46%, ROE 16% |
| Infrastructure Raid | 70% | **30%** | 12.9 | objective 55%, ROE 15% |
| Reconnaissance | 81% | **19%** | 9.8 | objective 81% |

Blue wins in roughly 1 in 3–5 games. ROE violations account for 15–16% of Red wins in the first two scenarios — autonomous systems that engage too freely forfeit the mission.

---

## Key mechanics

### Hex airspace
Axial hex coordinates with terrain (open, urban, forest, water, mountain). Terrain adds radar clutter (urban), blocks line-of-sight (mountain), and degrades optical sensors (forest/weather). Jamming falls off with distance.

### Simultaneous resolution
Each turn: Red moves → sensor sweep → Blue engages → cooldowns tick. The sweep-before-engage ordering ensures Blue fires at current positions, not stale tracks.

### Partial observability
Blue sees tracks — position + confidence estimate. Tracks age out after 2 turns without re-detection. Red can inject spoofed tracks (costs 2 budget) to waste intercept shots.

### EW model
- Kinetic and laser interceptors: **fully EW-immune** (missiles don't care about jamming)
- Net and RF-kill: **strongly degraded** by jamming (up to −50% hit probability)
- Jammer range falls off as distance^0.8

### ROE dial
Each interceptor has an autonomy level:

| Level | Action cost | ROE compliance |
|---|---|---|
| Supervised | 1 Blue budget/turn | 100% |
| Semi | Free | 95% |
| Autonomous | Free | 70% |

Three violations ends the game as a Red win. The recon scenario uses a lower threshold (4) because the HMT tension is the central research question.

---

## Architecture

```
dronewar/
├── env/
│   ├── airspace.py      Hex grid, Drone, Sensor, Interceptor, Track, Airspace
│   ├── actions.py       Red + Blue action types, resolution logic
│   └── observation.py   Partial observability builders
├── agents/
│   └── agents.py        HeuristicRed/Blue, RandomRed/Blue
├── engine/
│   └── engine.py        DroneWarEngine, WinCondition, turn loop, step()
└── scenarios/
    └── scenarios.py     forward_strike, infrastructure_raid, reconnaissance
server.py                Flask web server — REST API, browser auto-open
static/game.html         Single-page UI — hex grid, start screen, turn log
main.py                  CLI runner
dronewar.spec            PyInstaller spec (bundles server + static/)
```

---

## Server

```bash
pip install -e ".[web]"   # installs Flask
python server.py          # opens http://localhost:5000 automatically
```

```
python server.py [options]

  --port    INT    (default: 5000)
  --host    STR    (default: 127.0.0.1)

  # Skip the start screen and jump straight into a game:
  --scenario {forward_strike,infrastructure_raid,reconnaissance}
  --human    {red,blue,both}
  --opponent {heuristic,random}   (default: heuristic)
  --seed     INT
```

The start screen lets you choose scenario and agent type for each side independently. AI vs AI watch mode auto-steps at 0.7s/turn. The hex grid renders sensor range rings, drone positions by role (✕ strike, ◎ ISR, ◇ decoy, ⚡ EW), interceptors as diamonds, and Blue's track picture as crosses. The turn log colour-codes kills, objectives, ROE violations, and spoofed tracks.

---

## CLI reference

```
python main.py [options]

  --scenario {forward_strike,infrastructure_raid,reconnaissance}
  --red      {heuristic,random}   (default: heuristic)
  --blue     {heuristic,random}   (default: heuristic)
  --seed     INT                  (default: 42)
  --verbose                       per-turn output
  --quiet                         suppress all output
```

---

## Python API

```python
from dronewar.scenarios.scenarios import SCENARIOS
from dronewar.engine.engine import DroneWarEngine, WinCondition
from dronewar.agents.agents import HeuristicRedAgent, HeuristicBlueAgent
from dronewar.env.airspace import Team
import random

rng      = random.Random(42)
airspace = SCENARIOS["forward_strike"]()

red  = HeuristicRedAgent("red",  Team.RED,  rng=random.Random(1))
blue = HeuristicBlueAgent("blue", Team.BLUE, rng=random.Random(2))

engine = DroneWarEngine(
    airspace      = airspace,
    red_agent     = red,
    blue_agent    = blue,
    win_condition = WinCondition(
        deadline              = airspace.deadline,
        red_objectives_needed = airspace.red_objectives_needed,
    ),
    rng     = rng,
    verbose = True,
)
engine.run()

print(engine.winner)       # Team.RED or Team.BLUE
print(engine.win_reason)   # "objective (2/2)", "roe_violation (3)", "deadline", ...
print(airspace.red_score)  # fraction of drones that reached objectives
print(airspace.blue_score) # fraction of drones destroyed
```

---

## Running tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

The test suite does not require Flask — 106 tests cover the simulation engine only. To verify the server:

```bash
pip install flask
python -c "from server import app; print('OK')"
```

106 tests covering hex geometry, sensor physics, EW/jamming model, action resolution, turn loop, win conditions, all three scenarios, balance (Blue non-zero win rate), and determinism across 5 seeds.

---

## Citation

```bibtex
@software{kocho_williams_2025_dronewar,
  author    = {Kocho-Williams, Alastair},
  title     = {DroneWar: A Multi-Agent UAV Warfare Simulation},
  year      = {2025},
  publisher = {Cold Alchemy Games},
  url       = {https://github.com/Alikocho/DroneWar}
}
```

---

## License

MIT — see [LICENSE](LICENSE).
