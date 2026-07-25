"""hadoku-task-automation — the board-driven pipeline.

crimson-kitty's engine with the two ends swapped: work arrives from a
hadoku-task board instead of the aggregator, and lands by merging to our own
`main` instead of opening an upstream PR. The middle — environment, repro,
fix, verify — is the same code, reached through the same gate registry
(namespaced by pipeline, see `temporal.gates`).

See docs/hadoku-task-automation/README.md.
"""
