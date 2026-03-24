#!/usr/bin/env python3
"""Generate adjective-animal batch name candidates.

Usage:
    python3 scripts/gen_batch_names.py          # prints 50 names
    python3 scripts/gen_batch_names.py --n 20   # prints 20 names
    python3 scripts/gen_batch_names.py --seed 42
"""

import argparse
import random

ADJECTIVES = [
    "amber", "ancient", "arcane", "arctic", "azure", "blazing", "bold",
    "brave", "bright", "bronze", "calm", "cerulean", "charred", "chrome",
    "cobalt", "cool", "copper", "coral", "cosmic", "crimson", "crystal",
    "dark", "dawn", "dusk", "dusty", "eager", "ebony", "electric", "ember",
    "emerald", "feral", "fierce", "fiery", "flint", "fluffy", "frosty",
    "gentle", "gilded", "glowing", "golden", "granite", "gray", "green",
    "hollow", "honey", "icy", "indigo", "iron", "jade", "keen",
    "lavender", "lean", "lunar", "mauve", "midnight", "misty", "molten",
    "mossy", "muted", "mystic", "neon", "nimble", "noble", "obsidian",
    "ocean", "olive", "onyx", "opal", "pale", "phantom", "pine", "quiet",
    "rapid", "raven", "red", "rocky", "rose", "royal", "rusted", "rustic",
    "sandy", "sapphire", "scarlet", "shadow", "silver", "sleek", "slate",
    "smoky", "solar", "stark", "steel", "stone", "stormy", "swift",
    "teal", "thorned", "tidal", "timber", "twilight", "vast", "verdant",
    "violet", "vivid", "warm", "wild", "winter", "worn", "woven",
]

ANIMALS = [
    "badger", "bat", "bear", "beetle", "bison", "bobcat", "boar",
    "buck", "bull", "cat", "cobra", "condor", "coyote", "crane",
    "crow", "deer", "dingo", "dolphin", "dove", "dragon", "duck",
    "eagle", "eel", "elk", "falcon", "ferret", "finch", "fish",
    "fox", "frog", "gator", "gecko", "goat", "goose", "gorilla",
    "grouse", "hare", "hawk", "heron", "hornet", "horse", "hyena",
    "ibis", "jackal", "jaguar", "jay", "kite", "kiwi", "koala",
    "lemur", "leopard", "lion", "lizard", "llama", "lynx", "magpie",
    "mink", "mole", "mongoose", "moose", "moth", "mouse", "mule",
    "newt", "osprey", "otter", "owl", "ox", "panther", "parrot",
    "pelican", "penguin", "pike", "porcupine", "python", "rabbit",
    "raccoon", "ram", "raptor", "rat", "raven", "rhino", "robin",
    "rooster", "salamander", "salmon", "scorpion", "seal", "shark",
    "sheep", "shrike", "skunk", "sloth", "slug", "snail", "snake",
    "sparrow", "spider", "stag", "stallion", "stoat", "stork",
    "swan", "swift", "tiger", "toad", "tortoise", "toucan", "trout",
    "viper", "vole", "vulture", "walrus", "weasel", "wolf", "wolverine",
    "wombat", "wren", "yak", "zebra",
]


def generate(n: int = 50, seed: int | None = None) -> list[str]:
    rng = random.Random(seed)
    seen: set[str] = set()
    names: list[str] = []
    adj_pool = ADJECTIVES[:]
    ani_pool = ANIMALS[:]
    rng.shuffle(adj_pool)
    rng.shuffle(ani_pool)
    i = 0
    attempts = 0
    while len(names) < n and attempts < n * 10:
        adj = rng.choice(ADJECTIVES)
        ani = rng.choice(ANIMALS)
        name = f"{adj}-{ani}"
        if name not in seen:
            seen.add(name)
            names.append(name)
        attempts += 1
        i += 1
    return names


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate batch name candidates")
    parser.add_argument("--n", type=int, default=50, help="Number of names to generate")
    parser.add_argument("--seed", type=int, default=None, help="Random seed")
    args = parser.parse_args()
    for name in generate(args.n, args.seed):
        print(name)
