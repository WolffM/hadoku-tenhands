"""Temporal activities — side-effect implementations.

Activities are the layer where workflows touch the outside world. Each
activity is a single-purpose function decorated with @activity.defn. They
WRAP existing utilities from backend/helpers/ and backend/services/ rather
than reimplementing them.

Reuse map (see docs/crimson-kitty/components.md):

    eligibility.py   → _call_aggregator (oss_service), validation helpers
    quarantine.py    → run_gh_command (github_api), new quarantine_fork svc
    environment.py   → run_gh_command, oss_runner_setup
    agent.py         → CopilotAgent (new) wrapping existing dispatchers logic
    repro.py         → agent.py + evidence I/O
    fix.py           → agent.py + git diff parsing
    verify.py        → screenshot diff, pytest output parsing
    review.py        → existing CopilotReviewDispatcher logic, lifted
    remediation.py   → existing CopilotRemediationDispatcher logic, lifted
    submission.py    → sanitizer.py + format_upstream_pr_body
    watchers.py      → notify_human_comments (helpers/notifications.py)
    inbox.py         → new — enqueues for the operator inbox
"""
