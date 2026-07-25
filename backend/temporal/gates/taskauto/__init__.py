"""Gates for the hadoku-task-automation pipeline.

Registered under `TASK_AUTOMATION` so they never fire for crimson-kitty —
the two pipelines share this process and their state names collide. See
`temporal.gates` for the namespace, and docs/hadoku-task-automation/gates.md
for what each gate is defending against.
"""
