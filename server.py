"""
server.py
=========
Flask game server for DroneWar.

Serves the browser-based game UI and a REST API the UI polls each turn.
One game instance per server process. Supports AI vs AI watch mode,
human vs AI, and human vs human.

Usage:
    python server.py                          # start screen, pick in browser
    python server.py --scenario forward_strike --human red
    python server.py --scenario reconnaissance --human blue --opponent heuristic
    python server.py --port 5001
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import threading
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, jsonify, request, send_from_directory

from dronewar.env.airspace import (
    Team, Drone, DroneStatus, DroneRole,
    Sensor, Interceptor, Track, Airspace,
    hex_distance,
)
from dronewar.env.actions import (
    RedAction, BlueAction, RedActionType, BlueActionType,
    RED_ACTION_COSTS, BLUE_ACTION_COSTS,
)
from dronewar.env.observation import ObservationBuilder
from dronewar.engine.engine import DroneWarEngine, WinCondition
from dronewar.agents.agents import (
    HeuristicRedAgent, HeuristicBlueAgent,
    RandomRedAgent, RandomBlueAgent, BaseAgent,
)
from dronewar.scenarios.scenarios import SCENARIOS

_HERE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=os.path.join(_HERE, "static"))


# ─────────────────────────────────────────────────────────────────────────────
# Global game state
# ─────────────────────────────────────────────────────────────────────────────

class GameState:
    def __init__(self):
        self.engine:     Optional[DroneWarEngine] = None
        self.airspace:   Optional[Airspace]       = None
        self.config:     dict                     = {}
        self.status:     str                      = "waiting"
        self.last_record: Optional[dict]          = None
        self.lock        = threading.Lock()
        # Human action queues
        self.pending_red:  list  = []
        self.pending_blue: list  = []
        self.red_ready:    bool  = False
        self.blue_ready:   bool  = False

G = GameState()


# ─────────────────────────────────────────────────────────────────────────────
# Human agent — blocks until the browser submits actions
# ─────────────────────────────────────────────────────────────────────────────

class HumanRedAgent(BaseAgent):
    def __init__(self, game_state: GameState):
        super().__init__("human-red", Team.RED, rng=random.Random())
        self.G = game_state

    def act(self, obs, airspace):
        # Return whatever the browser queued; browser calls /api/end_turn
        with self.G.lock:
            actions = list(self.G.pending_red)
            self.G.pending_red.clear()
        return actions


class HumanBlueAgent(BaseAgent):
    def __init__(self, game_state: GameState):
        super().__init__("human-blue", Team.BLUE, rng=random.Random())
        self.G = game_state

    def act(self, obs, airspace):
        with self.G.lock:
            actions = list(self.G.pending_blue)
            self.G.pending_blue.clear()
        return actions


# ─────────────────────────────────────────────────────────────────────────────
# Game init
# ─────────────────────────────────────────────────────────────────────────────

def _make_agent(team: Team, agent_type: str, rng: random.Random):
    if agent_type == "human":
        return HumanRedAgent(G) if team == Team.RED else HumanBlueAgent(G)
    if agent_type == "random":
        cls = RandomRedAgent if team == Team.RED else RandomBlueAgent
    else:
        cls = HeuristicRedAgent if team == Team.RED else HeuristicBlueAgent
    return cls(f"{team.value}-ai", team, rng=rng)


def init_game(scenario: str, red_type: str, blue_type: str, seed: int):
    rng = random.Random(seed)
    airspace = SCENARIOS[scenario]()
    red  = _make_agent(Team.RED,  red_type,  random.Random(rng.randint(0, 999999)))
    blue = _make_agent(Team.BLUE, blue_type, random.Random(rng.randint(0, 999999)))

    engine = DroneWarEngine(
        airspace      = airspace,
        red_agent     = red,
        blue_agent    = blue,
        win_condition = WinCondition(
            deadline              = airspace.deadline,
            red_objectives_needed = airspace.red_objectives_needed,
        ),
        rng     = random.Random(rng.randint(0, 999999)),
        verbose = False,
    )

    with G.lock:
        G.engine    = engine
        G.airspace  = airspace
        G.config    = {
            "scenario":   scenario,
            "seed":       seed,
            "red_type":   red_type,
            "blue_type":  blue_type,
            "human_team": _human_team(red_type, blue_type),
            "deadline":   airspace.deadline,
            "red_objectives_needed": airspace.red_objectives_needed,
        }
        G.status      = "playing"
        G.last_record = None
        G.pending_red.clear()
        G.pending_blue.clear()
        G.red_ready  = False
        G.blue_ready = False

    # AI vs AI — kick off auto-stepping
    if G.config["human_team"] == "none":
        threading.Timer(0.5, _run_step).start()


def _human_team(red_type: str, blue_type: str) -> str:
    if red_type == "human" and blue_type == "human":
        return "both"
    if red_type == "human":
        return "red"
    if blue_type == "human":
        return "blue"
    return "none"


# ─────────────────────────────────────────────────────────────────────────────
# Serialisation
# ─────────────────────────────────────────────────────────────────────────────

def serialise_airspace(airspace: Airspace, engine: DroneWarEngine) -> dict:
    drones = [
        {
            "id":            d.id,
            "role":          d.role.value,
            "position":      list(d.position),
            "status":        d.state.status.value,
            "health":        round(d.state.health, 2),
            "jammer_active": d.state.jammer_active,
            "turns_in_zone": d.state.turns_in_zone,
            "autonomy":      d.autonomy.value,
            "rcs":           round(d.rcs, 2),
            "speed":         d.speed,
        }
        for d in airspace.drones
    ]
    sensors = [
        {
            "id":          s.id,
            "type":        s.sensor_type.value,
            "position":    list(s.position),
            "range":       s.range,
            "operational": s.state.operational,
            "suppressed":  s.state.suppressed,
        }
        for s in airspace.sensors
    ]
    interceptors = [
        {
            "id":        i.id,
            "type":      i.intercept_type.value,
            "position":  list(i.state.position),
            "range":     i.range,
            "available": i.is_available,
            "cooldown":  i.state.cooldown,
            "hit_prob":  round(i.hit_prob, 2),
        }
        for i in airspace.interceptors
    ]
    tracks = [
        {
            "track_id":   t.track_id,
            "position":   list(t.position),
            "confidence": round(t.confidence, 2),
            "age":        t.age,
            "is_spoofed": t.is_spoofed,
        }
        for t in airspace.tracks.values()
    ]
    targets = [
        list(c.coord)
        for c in airspace.all_cells() if c.is_target
    ]
    return {
        "turn":          engine.turn,
        "deadline":      airspace.deadline,
        "winner":        engine.winner.value if engine.winner else None,
        "win_reason":    engine.win_reason,
        "red_score":     round(airspace.red_score, 3),
        "blue_score":    round(airspace.blue_score, 3),
        "roe_violations":airspace.roe_violations,
        "roe_threshold": airspace.roe_threshold,
        "red_budget":    airspace.red_budget,
        "blue_budget":   airspace.blue_budget,
        "radius":        airspace.radius,
        "drones":        drones,
        "sensors":       sensors,
        "interceptors":  interceptors,
        "tracks":        tracks,
        "targets":       targets,
    }


def serialise_record(rec) -> dict:
    def sa(action):
        if isinstance(action, RedAction):
            return {
                "type":      action.action_type.value,
                "drone_ids": action.drone_ids,
                "target":    list(action.target) if action.target else None,
            }
        return {
            "type":           action.action_type.value,
            "interceptor_id": action.interceptor_id,
            "track_id":       action.track_id,
            "target":         list(action.target) if action.target else None,
        }
    return {
        "turn":                rec.turn,
        "log":                 rec.log,
        "red_actions":         [sa(a) for a in rec.red_actions],
        "blue_actions":        [sa(a) for a in rec.blue_actions],
        "active_drones":       rec.active_drones,
        "track_count":         rec.track_count,
        "drone_snapshot":      rec.drone_snapshot      or [],
        "interceptor_snapshot":rec.interceptor_snapshot or [],
        "track_snapshot":      rec.track_snapshot      or [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Engine step
# ─────────────────────────────────────────────────────────────────────────────

def _should_step() -> bool:
    with G.lock:
        if G.engine is None or G.engine.winner is not None:
            return False
        ht = G.config.get("human_team", "none")
        if ht == "none":   return True
        if ht == "both":   return G.red_ready and G.blue_ready
        if ht == "red":    return G.red_ready
        if ht == "blue":   return G.blue_ready
    return False


def _run_step():
    with G.lock:
        if G.engine is None or G.engine.winner is not None:
            return
        G.status = "animating"

    rec = G.engine.step()

    with G.lock:
        G.last_record = serialise_record(rec) if rec else None
        G.red_ready   = False
        G.blue_ready  = False
        if G.engine.winner:
            G.airspace.compute_scores()
            G.status = "finished"
        else:
            G.status = "playing"
        # AI vs AI: schedule next step
        if G.config.get("human_team") == "none" and not G.engine.winner:
            threading.Timer(0.7, _run_step).start()


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "game.html")


@app.route("/api/scenarios")
def api_scenarios():
    return jsonify({
        "forward_strike": {
            "label":       "Forward Strike",
            "description": "FPV swarm assault on a defended position. Red needs 2 drones to reach the objective cluster.",
            "difficulty":  "Medium",
            "deadline":    24,
            "red_needs":   2,
        },
        "infrastructure_raid": {
            "label":       "Infrastructure Raid",
            "description": "Loitering munitions penetrate layered C-UAS to reach one of three infrastructure targets.",
            "difficulty":  "Hard",
            "deadline":    25,
            "red_needs":   1,
        },
        "reconnaissance": {
            "label":       "Reconnaissance",
            "description": "ISR package must survive in the target zone for 3 turns. Autonomous drones risk ROE violations.",
            "difficulty":  "Hard",
            "deadline":    22,
            "red_needs":   2,
        },
    })


@app.route("/api/new_game", methods=["POST"])
def api_new_game():
    data       = request.get_json() or {}
    scenario   = data.get("scenario",   "forward_strike")
    red_type   = data.get("red_agent",  "heuristic")
    blue_type  = data.get("blue_agent", "heuristic")
    seed       = data.get("seed",       random.randint(0, 9999))
    init_game(scenario, red_type, blue_type, seed)
    return jsonify({"ok": True, "seed": seed})


@app.route("/api/state")
def api_state():
    with G.lock:
        if G.engine is None:
            return jsonify({"status": "waiting"})
        state = serialise_airspace(G.airspace, G.engine)
        state["status"]      = G.status
        state["config"]      = G.config
        state["last_record"] = G.last_record
        state["history_len"] = len(G.engine.history)
        return jsonify(state)


@app.route("/api/action", methods=["POST"])
def api_action():
    """
    Submit actions for a team.
    Body: { "team": "red"|"blue", "actions": [...], "end_turn": true }

    Red action:   { "type": "move", "drone_ids": ["fpv_1"], "target": [0, -5] }
    Blue action:  { "type": "engage", "interceptor_id": "kinetic_1", "track_id": "track_fpv_1" }
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON body"}), 400

    team_str = data.get("team", "red")
    actions_raw = data.get("actions", [])
    end_turn = data.get("end_turn", True)

    with G.lock:
        if G.engine is None or G.engine.winner is not None:
            return jsonify({"error": "Game not active"}), 400

        parsed = []
        for ar in actions_raw:
            try:
                if team_str == "red":
                    # Accept both "type" and "action_type" as the key
                    type_val = ar.get("type") or ar.get("action_type")
                    at = RedActionType(type_val)
                    cost = RED_ACTION_COSTS.get(at, 1)
                    tgt = ar.get("target")
                    parsed.append(RedAction(
                        action_type = at,
                        drone_ids   = ar.get("drone_ids", []),
                        target      = tuple(tgt) if tgt else None,
                        cost        = cost,
                    ))
                else:
                    type_val = ar.get("type") or ar.get("action_type")
                    at = BlueActionType(type_val)
                    cost = BLUE_ACTION_COSTS.get(at, 1)
                    tgt = ar.get("target")
                    parsed.append(BlueAction(
                        action_type    = at,
                        interceptor_id = ar.get("interceptor_id"),
                        track_id       = ar.get("track_id"),
                        target         = tuple(tgt) if tgt else None,
                        cost           = cost,
                    ))
            except (ValueError, KeyError):
                continue

        if team_str == "red":
            G.pending_red.extend(parsed)
            if end_turn:
                G.red_ready = True
        else:
            G.pending_blue.extend(parsed)
            if end_turn:
                G.blue_ready = True

    if _should_step():
        threading.Thread(target=_run_step).start()

    return jsonify({"ok": True, "actions_queued": len(parsed)})


@app.route("/api/end_turn", methods=["POST"])
def api_end_turn():
    data = request.get_json() or {}
    team_str = data.get("team", "red")
    with G.lock:
        if team_str == "red":
            G.red_ready = True
        else:
            G.blue_ready = True
    if _should_step():
        threading.Thread(target=_run_step).start()
    return jsonify({"ok": True})


@app.route("/api/history")
def api_history():
    with G.lock:
        if G.engine is None:
            return jsonify([])
        return jsonify([serialise_record(r) for r in G.engine.history])


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory("static", filename)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="DroneWar Game Server")
    p.add_argument("--port",     type=int, default=5000)
    p.add_argument("--host",     default="127.0.0.1")
    p.add_argument("--scenario", default=None, choices=list(SCENARIOS.keys()))
    p.add_argument("--human",    default=None, choices=["red", "blue", "both"])
    p.add_argument("--opponent", default="heuristic", choices=["heuristic", "random"])
    p.add_argument("--seed",     type=int, default=None)
    args = p.parse_args()

    os.makedirs("static", exist_ok=True)

    url = f"http://localhost:{args.port}"

    print(f"\n{'═'*56}")
    print(f"  DRONEWAR")
    print(f"{'─'*56}")
    print(f"  URL:  {url}")
    print(f"  Open the URL above if the browser doesn't launch.")
    print(f"{'═'*56}\n")

    if args.scenario and args.human:
        seed = args.seed or random.randint(0, 9999)
        red_t  = "human"     if args.human in ("red", "both")  else args.opponent
        blue_t = "human"     if args.human in ("blue", "both") else args.opponent
        init_game(args.scenario, red_t, blue_t, seed)
        print(f"  Auto-started: {args.scenario}  red={red_t}  blue={blue_t}  seed={seed}\n")

    import threading, time

    def _open_browser():
        time.sleep(1.5)
        print(f"\n  Opening: {url}")
        try:
            import sys, subprocess
            if sys.platform == "darwin":
                subprocess.Popen(["open", url])
            elif sys.platform == "win32":
                import os; os.startfile(url)
            else:
                subprocess.Popen(["xdg-open", url])
        except Exception:
            try:
                import webbrowser; webbrowser.open(url)
            except Exception:
                pass

    threading.Thread(target=_open_browser, daemon=True).start()

    
