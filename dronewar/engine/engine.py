"""
engine/engine.py
================
DroneWar simulation engine.

Turn structure (simultaneous resolution):
  1. Both agents observe the world
  2. Red submits actions   (move, EW, spoof, …)
  3. Blue submits actions  (engage, reposition, …)
  4. Resolve Red moves
  5. Resolve Blue engages (against post-move positions)
  6. Sensor sweep → update Blue's track picture
  7. Tick cooldowns
  8. Check win conditions

Win conditions
--------------
  Red wins:
    - Any STRIKE or ISR drone reaches OBJECTIVE status
    - Blue ROE violations >= threshold (mission abort)
  Blue wins:
    - All Red drones destroyed/RTB before deadline
    - Deadline reached with no Red objective achieved
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import List, Optional

from dronewar.env.airspace import Airspace, Drone, DroneStatus, Team
from dronewar.env.actions  import ActionResolver, RedAction, BlueAction
from dronewar.env.observation import ObservationBuilder


@dataclass
class WinCondition:
    deadline:              int   = 20
    roe_threshold:         int   = 3    # Blue loses if violations reach this
    isr_turns_required:    int   = 3    # ISR drones need this many turns in zone
    red_objectives_needed: int   = 1    # Red needs this many objectives to win


@dataclass
class TurnRecord:
    turn:          int
    red_actions:   List[RedAction]
    blue_actions:  List[BlueAction]
    log:           List[str]
    active_drones: int
    track_count:   int


class DroneWarEngine:
    def __init__(self, airspace: Airspace,
                 red_agent, blue_agent,
                 win_condition: WinCondition,
                 rng: Optional[random.Random] = None,
                 verbose: bool = False):
        self.airspace      = airspace
        self.red_agent     = red_agent
        self.blue_agent    = blue_agent
        self.win_condition = win_condition
        self.rng           = rng or random.Random()
        self.verbose       = verbose

        self.airspace.roe_threshold        = win_condition.roe_threshold
        self.airspace.isr_turns_required   = win_condition.isr_turns_required
        self.airspace.red_objectives_needed = win_condition.red_objectives_needed

        self.resolver = ActionResolver(self.airspace, self.rng)
        self.obs      = ObservationBuilder(self.airspace)

        self.turn:       int            = 0
        self.winner:     Optional[Team] = None
        self.win_reason: str            = ""
        self.history:    List[TurnRecord] = []

    def run(self):
        while self.turn < self.win_condition.deadline:
            self.turn += 1
            self._step()
            if self.winner:
                break
        if self.winner is None:
            # Deadline reached — Blue wins by survival
            self.winner     = Team.BLUE
            self.win_reason = "deadline" 

        self.airspace.compute_scores()
        if self.verbose:
            w = self.winner.value.upper()
            print(f"\n{'═'*50}")
            print(f"  RESULT: {w} wins  │  {self.turn} turns")
            print(f"  Red score : {self.airspace.red_score:.2f}")
            print(f"  Blue score: {self.airspace.blue_score:.2f}")
            print(f"{'═'*50}")

    def _step(self):
        a   = self.airspace
        res = self.resolver

        red_obs  = self.obs.red_obs(self.turn)
        blue_obs = self.obs.blue_obs(self.turn)

        # Both agents decide
        red_actions  = self.red_agent.act(red_obs,  a)
        blue_actions = self.blue_agent.act(blue_obs, a)

        res.clear_log()

        if self.verbose:
            print(f"\n── Turn {self.turn} ─────────────────────────────────")
            print(f"  Active drones: {len(a.active_drones())}  "
                  f"Tracks: {len(a.tracks)}  "
                  f"ROE violations: {a.roe_violations}")

        # Phase 1: Red moves
        res.resolve_red_actions(red_actions)

        # Phase 2: Sensor sweep — update tracks BEFORE Blue engages
        # This ensures Blue fires at current positions, not stale ones.
        res.sensor_sweep()

        # Phase 3: Blue engages (post-move, post-sweep positions)
        res.resolve_blue_actions(blue_actions)

        # Phase 4: Cooldowns
        res.tick_cooldowns()

        if self.verbose:
            for line in res.log:
                print(line)

        self.history.append(TurnRecord(
            turn          = self.turn,
            red_actions   = red_actions,
            blue_actions  = blue_actions,
            log           = res.log,
            active_drones = len(a.active_drones()),
            track_count   = len(a.tracks),
        ))

        # Check win conditions
        self._check_win()

    def step(self):
        """Run one turn. Returns TurnRecord or None if game already over."""
        if self.winner is not None:
            return None
        if self.turn >= self.win_condition.deadline:
            self.winner     = Team.BLUE
            self.win_reason = "deadline"
            self.airspace.compute_scores()
            return None
        self.turn += 1
        self._step()
        return self.history[-1] if self.history else None

    def _check_win(self):
        a = self.airspace

        # Red: enough drones completed objective
        n_obj = sum(1 for d in a.drones
                    if d.state.status == DroneStatus.OBJECTIVE)
        needed = getattr(a, 'red_objectives_needed', 1)
        if n_obj >= needed:
            self.winner     = Team.RED
            self.win_reason = f"objective ({n_obj}/{needed})"
            if self.verbose:
                print(f"  *** RED WINS — {n_obj}/{needed} objectives ***")
            return

        # Blue loses: ROE violation threshold
        if a.roe_violations >= a.roe_threshold:
            self.winner     = Team.RED
            self.win_reason = f"roe_violation ({a.roe_violations})"
            if self.verbose:
                print(f"  *** RED WINS — Blue ROE violations ({a.roe_violations}) ***")
            return

        # Blue wins: all drones neutralised
        if len(a.active_drones()) == 0:
            self.winner     = Team.BLUE
            self.win_reason = "all_drones_neutralised"
            if self.verbose:
                print(f"  *** BLUE WINS — all drones neutralised ***")
            return
