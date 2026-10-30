"""Pure virtual-time pet motion; no GUI, timers, file access or sprite ownership.

The caller supplies monotonic seconds. Only ``tick(now)`` consumes delta_x;
events return a snapshot with zero displacement. Stop events freeze the last
rendered position, discarding unrendered sub-frame travel.

Renderer states:
  rest/loop              fixed sleeping mode
  attentive/loop         panel open, stationary
  walk/start, loop, end  .36s acceleration, 4-7s cruise, .28s deceleration
  idle/pause             1-3s awake pause; short/long pauses weighted 3:1
  idle/turn              .25s boundary pause after decelerating and reversing
  typing/loop            1.2s after the last input, with continuous phase time
  highlight/start, loop, end .12s + .65s + .15s, higher priority than typing
  delete/eat, chew, burp .82s + .90s + .85s; lower events never interrupt it

The renderer clamps position to screen bounds before calling turn(). Its short
end phase can still request outward travel, which remains clamped at the edge.
The timing structure is informed by VPet Start/Loop/End and Shimeji's separate
pose timing/velocity and weighted behavior choices; their code is not copied.
"""

from dataclasses import dataclass
import math
import random


@dataclass(frozen=True)
class BehaviorFrame:
    action: str
    phase: str
    local_elapsed: float
    action_elapsed: float
    delta_x: float
    direction: int
    speed: float


class PetBehavior:
    WALK_START = 0.36
    WALK_END = 0.28
    TURN_PAUSE = 0.25
    TYPING_HOLD = 1.2
    HIGHLIGHT_START = 0.12
    HIGHLIGHT_HOLD = 0.65
    HIGHLIGHT_END = 0.15
    DELETE_PHASES = {"eat": 0.82, "chew": 0.90, "burp": 0.85}
    PRIORITY = {"typing": 1, "highlight": 2, "delete": 3}

    def __init__(self, *, now=0.0, rng=None, speed=35.0, direction=1):
        now, speed = float(now), float(speed)
        if not math.isfinite(now) or not math.isfinite(speed) or speed <= 0 or direction not in (-1, 1):
            raise ValueError("Use a finite time, positive speed, and direction -1 or 1")
        self._random = rng if rng is not None else random.Random()
        self._cruise_speed = speed
        self._direction = direction
        self.panel_open = False
        self.wandering = False
        self._now = now
        self._action = "rest"
        self._phase = "loop"
        self._phase_started = now
        self._action_started = now
        self._deadline = math.inf
        self._pending_dx = 0.0
        self._end_speed = 0.0
        self._turning = False
        self._highlight_until = now

    @property
    def action(self):
        return self._action

    @property
    def phase(self):
        return self._phase

    @property
    def direction(self):
        return self._direction

    @property
    def local_elapsed(self):
        return self._now - self._phase_started

    @property
    def action_elapsed(self):
        return self._now - self._action_started

    @property
    def speed(self):
        return self._velocity(self._now)

    def _frame(self, delta_x=0.0):
        return BehaviorFrame(self.action, self.phase, self.local_elapsed,
                             self.action_elapsed, delta_x, self.direction, self.speed)

    def _state(self, action, phase, now, duration=math.inf):
        if action != self._action:
            self._action_started = now
        self._action, self._phase = action, phase
        self._phase_started = now
        self._deadline = now + duration

    def _base(self, now):
        self._turning = False
        if self.panel_open:
            action, phase, duration = "attentive", "loop", math.inf
        elif self.wandering:
            action, phase, duration = "walk", "start", self.WALK_START
        else:
            action, phase, duration = "rest", "loop", math.inf
        if action in ("rest", "attentive") and action == self.action:
            return
        self._state(action, phase, now, duration)

    def _velocity(self, now):
        if self.action != "walk":
            return 0.0
        elapsed = now - self._phase_started
        if self.phase == "start":
            return self._cruise_speed * min(1.0, elapsed / self.WALK_START)
        if self.phase == "end":
            return self._end_speed * max(0.0, 1.0 - elapsed / self.WALK_END)
        return self._cruise_speed

    def _integrate(self, end):
        # The start/end speed curves are linear, so the trapezoid is exact.
        duration = end - self._now
        self._pending_dx += self.direction * duration * (self._velocity(self._now) + self._velocity(end)) / 2
        self._now = end

    def _next_phase(self, now):
        if self.action == "walk":
            if self.phase == "start":
                self._state("walk", "loop", now, self._random.uniform(4.0, 7.0))
            elif self.phase == "loop":
                self._end_speed = self._cruise_speed
                self._state("walk", "end", now, self.WALK_END)
            elif self._turning:
                self._direction *= -1
                self._turning = False
                self._state("idle", "turn", now, self.TURN_PAUSE)
            else:
                bounds = (1.0, 2.0) if self._random.random() < 0.75 else (2.0, 3.0)
                self._state("idle", "pause", now, self._random.uniform(*bounds))
        elif self.action == "highlight" and self.phase == "start":
            self._state("highlight", "loop", now, self._highlight_until - now)
        elif self.action == "highlight" and self.phase == "loop":
            self._state("highlight", "end", now, self.HIGHLIGHT_END)
        elif self.action == "delete" and self.phase == "eat":
            self._state("delete", "chew", now, self.DELETE_PHASES["chew"])
        elif self.action == "delete" and self.phase == "chew":
            self._state("delete", "burp", now, self.DELETE_PHASES["burp"])
        else:
            self._base(now)

    def _advance(self, now):
        now = float(now)
        if not math.isfinite(now) or now < self._now:
            raise ValueError("PetBehavior requires finite, nondecreasing monotonic time")
        # Account for every elapsed phase, including a timer tick that arrives
        # late. Frame rate changes cannot stretch movement or reaction timing.
        while self._deadline <= now:
            self._integrate(self._deadline)
            self._next_phase(self._now)
        self._integrate(now)

    def tick(self, now) -> BehaviorFrame:
        self._advance(now)
        delta_x, self._pending_dx = self._pending_dx, 0.0
        return self._frame(delta_x)

    def set_panel_open(self, enabled, now) -> BehaviorFrame:
        self._advance(now)
        enabled = bool(enabled)
        cancel_attention = not enabled and self.action in ("typing", "highlight")
        if enabled != self.panel_open or cancel_attention:
            self.panel_open = enabled
            if enabled or cancel_attention:
                self._pending_dx = 0.0
            if cancel_attention or self.action not in self.PRIORITY:
                self._base(self._now)
        return self._frame()

    def set_wandering(self, enabled, now) -> BehaviorFrame:
        self._advance(now)
        enabled = bool(enabled)
        if enabled != self.wandering:
            self.wandering = enabled
            if not enabled:
                self._pending_dx = 0.0
            if self.action not in self.PRIORITY:
                self._base(self._now)
        return self._frame()

    def react(self, event, now) -> BehaviorFrame:
        if event not in self.PRIORITY:
            raise ValueError(f"Unknown pet reaction: {event}")
        self._advance(now)
        if self.PRIORITY[event] < self.PRIORITY.get(self.action, 0):
            return self._frame()
        if event == self.action:
            if event == "typing":
                self._deadline = max(self._deadline, self._now + self.TYPING_HOLD)
            elif event == "highlight" and self.phase != "end":
                self._highlight_until = max(self._highlight_until, self._now + self.HIGHLIGHT_HOLD)
                if self.phase == "loop":
                    self._deadline = self._highlight_until
            return self._frame()
        self._pending_dx = 0.0
        self._turning = False
        if event == "delete":
            self._state("delete", "eat", self._now, self.DELETE_PHASES["eat"])
        elif event == "highlight":
            self._highlight_until = self._now + self.HIGHLIGHT_START + self.HIGHLIGHT_HOLD
            self._state("highlight", "start", self._now, self.HIGHLIGHT_START)
        else:
            self._state(event, "loop", self._now, self.TYPING_HOLD)
        return self._frame()

    def set_direction(self, direction, now) -> BehaviorFrame:
        """Change facing without restarting a pose; use turn() at boundaries."""
        if direction not in (-1, 1):
            raise ValueError("Direction must be -1 or 1")
        self._advance(now)
        self._direction = direction
        return self._frame()

    def turn(self, now) -> BehaviorFrame:
        self._advance(now)
        if self._turning or (self.action == "idle" and self.phase == "turn"):
            return self._frame()
        if self.action == "walk":
            self._turning = True
            if self.phase != "end":
                self._end_speed = self.speed
                self._state("walk", "end", self._now, self.WALK_END)
        elif self.action == "idle":
            self._direction *= -1
            self._state("idle", "turn", self._now, self.TURN_PAUSE)
        return self._frame()
