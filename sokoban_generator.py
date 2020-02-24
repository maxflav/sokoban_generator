#!/usr/bin/python

from heapq import heappop, heappush
import math
import random
import time

EMPTY = 0
WALL = 1
BLOCK = 2
HOLE = 3
SPACES = [EMPTY, WALL, BLOCK, HOLE]

GOAL = 4

ITEM_STRINGS = {
    EMPTY: ".",
    WALL: "#",
    BLOCK: "x",
    HOLE: "O",
}

SIZE = 6

MAX_TEMPERATURE = 50.0
TEMPERATURE_DELTA = 0.01
RESET_FREQUENCY = 7
IDEAL_SEARCH_STEPS = 250000
GIVEUP_SEARCH_STEPS = 750000

class Pos:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def get(self, level):
        if self.x < 0 or self.x >= SIZE or self.y < 0 or self.y >= SIZE:
            return WALL
        return level[self.x][self.y]

    def set(self, level, to):
        level[self.x][self.y] = to

    def __add__(self, other):
        return Pos(self.x + other.x, self.y + other.y)

    def __sub__(self, other):
        return Pos(self.x - other.x, self.y - other.y)

    def __eq__(self, other):
        return self.x == other.x and self.y == other.y

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return self.x * SIZE + self.y

    def __abs__(self):
        return abs(self.x) + abs(self.y)

    def __repr__(self):
        return "(" + str(self.x) + ", " + str(self.y) + ")"


PLAYER_START = Pos(0, 0)
GOAL_POS = Pos(SIZE - 1, SIZE - 1)


def copy_level(level):
    return [row[:] for row in level]

class GameState:
    def __init__(self, level, player=PLAYER_START):
        # level will never be modified, only copied
        self.level = level
        self.player = player

    def won(self):
        return self.player == GOAL_POS

    def neighbors(self):
        result = []
        for (dx, dy) in [(1,0), (-1,0), (0,1), (0,-1)]:
            n = self.one_neighbor(Pos(dx, dy))
            if n is not None:
                result.append(n)
        return result

    def one_neighbor(self, move):
        new_pos = self.player + move
        item = new_pos.get(self.level)
        if item in [WALL, HOLE]:
            return None

        if item == EMPTY:
            return GameState(self.level, new_pos)

        # It's a block
        assert item == BLOCK
        new_block_pos = new_pos + move
        if new_block_pos == GOAL_POS:
            return None
        block_into_item = new_block_pos.get(self.level)
        if block_into_item in [WALL, BLOCK]:
            return None

        new_level = copy_level(self.level)
        new_pos.set(new_level, EMPTY)
        if block_into_item == EMPTY:
            new_block_pos.set(new_level, BLOCK)
            new_level = normalize_level_around_pos(new_level, new_block_pos)
            return GameState(new_level, self.player + move)

        # Block falling into a hole
        assert block_into_item == HOLE
        new_block_pos.set(new_level, EMPTY)
        return GameState(new_level, self.player + move)

    def __hash__(self):
        total = hash(self.player)
        total *= SIZE * SIZE
        for row in self.level:
            for cell in row:
                total += cell
                total *= len(SPACES)
        assert total >= 0
        return total

    def __eq__(self, other):
        if self.player != other.player:
            return False
        for self_row, other_row in zip(self.level, other.level):
            for self_cell, other_cell in zip(self_row, other_row):
                if self_cell != other_cell:
                    return False
        return True

    def __str__(self):
        result = ""
        for row_idx, row in enumerate(self.level):
            for cell_idx, cell in enumerate(row):
                if self.player.x == row_idx and self.player.y == cell_idx:
                    result += "P"
                elif GOAL_POS.x == row_idx and GOAL_POS.y == cell_idx:
                    result += "*"
                else:
                    result += ITEM_STRINGS[cell]
            result += "\n"
        return result

cached_solutions = {}

def goal_reachable(level):
    # can the player reach the goal via EMPTY/BLOCK/HOLEs?
    new_level = copy_level(level)
    for row_idx in range(SIZE):
        for col_idx in range(SIZE):
            item = new_level[row_idx][col_idx]
            if item != WALL:
                new_level[row_idx][col_idx] = EMPTY

    steps, loop_count = solve_one(new_level)
    return steps != -1

def normalize_level_around_pos(level, pos):
    for move in [Pos(0, 0), Pos(-1, 0), Pos(0, -1), Pos(-1, -1)]:
        level = _normalize_level_at_pos(level, pos + move)

    if pos.get(level) == BLOCK:
        above_or_below = (pos + Pos(0, 1)).get(level) == WALL or (pos + Pos(0, -1)).get(level) == WALL
        right_or_left = (pos + Pos(1, 0)).get(level) == WALL or (pos + Pos(-1, 0)).get(level) == WALL
        if above_or_below and right_or_left:
            pos.set(level, WALL)


    return level

def _normalize_level_at_pos(level, pos):
    positions = [pos + p for p in [Pos(0, 0), Pos(1, 0), Pos(0, 1), Pos(1, 1)]]
    items = [GOAL if p == GOAL_POS else p.get(level) for p in positions]
    if not all([i in [BLOCK, WALL, GOAL] for i in items]):
        return level

    if not any([i == BLOCK for i in items]):
        return level

    for p in positions:
        if p.get(level) == BLOCK:
            changed_anything = True
            p.set(level, WALL)
    return level


def normalize_level(level):
    changed_anything = False
    for row in range(-1, SIZE):
        for col in range(-1, SIZE):
            level = _normalize_level_at_pos(level, Pos(row, col))

    return level

# first ret val is -1 if impossible, otherwise number of steps in shortest solution
# second ret val is number of states tried
def solve_one(level):
    pq = []

    # level = normalize_level(level)
    start_state = GameState(level)
    heappush(pq, (0, 0, start_state))
    seen = set([hash(start_state)])

    # Map from each state to its parent state
    state_map = {}

    loop_count = 0
    while len(pq) > 0:
        loop_count += 1
        # heappop will always return the LOWEST score
        (score, steps, state) = heappop(pq)

        hashed_state = hash(state)
        if state.won() or hashed_state in cached_solutions or loop_count > GIVEUP_SEARCH_STEPS:
            if loop_count > GIVEUP_SEARCH_STEPS:
                steps = -1

            if hashed_state in cached_solutions:
                steps, loop_count = cached_solutions[hashed_state]

            backstep_count = 0
            original_hashed_state = hashed_state
            while hashed_state in state_map:
                cached_solutions[hashed_state] = (steps - backstep_count, loop_count)
                if steps != -1:
                    backstep_count += 1
                state = state_map[hashed_state]
                hashed_state = hash(state)
                if backstep_count >= 100:
                    assert False

            return steps, loop_count

        for neighbor in state.neighbors():
            hashed_neighbor = hash(neighbor)
            if hashed_neighbor in seen:
                continue

            state_map[hashed_neighbor] = state
            seen.add(hashed_neighbor)

            new_steps = steps + 1
            goal_dist = abs(neighbor.player - GOAL_POS)
            num_blocks = sum([cell in [BLOCK, WALL] for row in neighbor.level for cell in row])
            new_score = (new_steps + goal_dist) * (SIZE * SIZE) + num_blocks

            heappush(pq, (new_score, new_steps, neighbor))

    for hashed_state in seen:
        loop_count = 0
        cached_solutions[hashed_state] = (-1, loop_count)
    return -1, loop_count

def similar_level(level):
    new_level = copy_level(level)
    while True:
        x = random.randint(0, SIZE-1)
        y = random.randint(0, SIZE-1)
        p = Pos(x, y)
        if p == PLAYER_START or p == GOAL_POS:
            continue

        new_level[x][y] = random.choice(SPACES)
        if new_level == level:
            continue

        new_level = normalize_level_around_pos(new_level, Pos(x, y))

        if goal_reachable(new_level):
            return new_level

def acceptance_probability(old_score, new_score, temperature):
    (old_solution_length, old_search_steps) = old_score
    (new_solution_length, new_search_steps) = new_score
    if new_solution_length > old_solution_length:
        return 1.0

    if new_solution_length < old_solution_length:
        return math.exp((new_solution_length - old_solution_length) / temperature) / 2.0

    new_search_steps = IDEAL_SEARCH_STEPS - abs(new_search_steps - IDEAL_SEARCH_STEPS)
    old_search_steps = IDEAL_SEARCH_STEPS - abs(old_search_steps - IDEAL_SEARCH_STEPS)

    if new_search_steps > old_search_steps:
        return 1.0

    # search_steps is in different units
    search_steps_temperature = temperature / MAX_TEMPERATURE * IDEAL_SEARCH_STEPS
    return math.exp((new_search_steps - old_search_steps) / temperature) / 2.0

def make_score(solution_length, search_steps):
    return (solution_length, IDEAL_SEARCH_STEPS - abs(search_steps - IDEAL_SEARCH_STEPS))

def generate_level():
    level = [[0 for _ in range(SIZE)] for _ in range(SIZE)]
    count = 0

    best_level = None
    best_score = 0

    temperature = MAX_TEMPERATURE
    old_score = make_score(0, 0)

    while temperature > 0:
        if temperature % RESET_FREQUENCY <= TEMPERATURE_DELTA:
            if best_level is not None:
                level = best_level
                old_score = best_score

        new_level = similar_level(level)

        new_solution_length, new_search_steps = solve_one(new_level)
        new_score = make_score(new_solution_length, new_search_steps)

        prob = acceptance_probability(old_score, new_score, temperature)
        if random.random() < prob:
            level = new_level
            old_score = new_score

            if new_score > best_score:
                if new_solution_length > 16:
                    print(new_solution_length, new_search_steps)
                    print(GameState(new_level))
                best_score = new_score
                best_level = new_level

        temperature -= TEMPERATURE_DELTA
    return best_level, best_score

generate_level()
