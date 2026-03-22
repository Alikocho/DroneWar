"""
main.py — DroneWar CLI
======================
Usage:
    python main.py --scenario forward_strike --seed 42
    python main.py --scenario infrastructure_raid --red heuristic --blue heuristic
    python main.py --scenario reconnaissance --verbose
"""

import argparse
import random
import sys

from dronewar.env.airspace import Team
from dronewar.engine.engine import DroneWarEngine, WinCondition
from dronewar.agents.agents import (
    HeuristicRedAgent, HeuristicBlueAgent,
    RandomRedAgent, RandomBlueAgent,
)
from dronewar.scenarios.scenarios import SCENARIOS

AGENTS = {
    "heuristic_red":  HeuristicRedAgent,
    "heuristic_blue": HeuristicBlueAgent,
    "random_red":     RandomRedAgent,
    "random_blue":    RandomBlueAgent,
}

def main():
    p = argparse.ArgumentParser(description="DroneWar simulation")
    p.add_argument("--scenario", default="forward_strike",
                   choices=list(SCENARIOS.keys()))
    p.add_argument("--red",  default="heuristic", choices=["heuristic","random"])
    p.add_argument("--blue", default="heuristic", choices=["heuristic","random"])
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--quiet",   action="store_true")
    args = p.parse_args()

    rng      = random.Random(args.seed)
    airspace = SCENARIOS[args.scenario]()

    red_cls  = HeuristicRedAgent  if args.red  == "heuristic" else RandomRedAgent
    blue_cls = HeuristicBlueAgent if args.blue == "heuristic" else RandomBlueAgent

    red  = red_cls( "red",  Team.RED,  rng=random.Random(rng.randint(0,999999)))
    blue = blue_cls("blue", Team.BLUE, rng=random.Random(rng.randint(0,999999)))

    engine = DroneWarEngine(
        airspace       = airspace,
        red_agent      = red,
        blue_agent     = blue,
        win_condition  = WinCondition(deadline=airspace.deadline),
        rng            = rng,
        verbose        = args.verbose and not args.quiet,
    )
    engine.run()

    if not args.quiet:
        winner = engine.winner.value.upper() if engine.winner else "DRAW"
        reason = f"  reason={engine.win_reason}" if engine.win_reason else ""
        print(f"{args.scenario}  seed={args.seed}  "
              f"winner={winner}  turns={engine.turn}  "
              f"red_score={airspace.red_score:.2f}  "
              f"blue_score={airspace.blue_score:.2f}{reason}")

if __name__ == "__main__":
    main()
