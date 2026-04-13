"""Temporal workflow definitions.

Workflows are deterministic Python functions that the Temporal worker
runs. They MUST NOT do I/O directly — every side effect goes through an
activity (see ../activities/).

Workflows in this package:
    issue_workflow.py — IssueWorkflow: per-issue state machine
    batch_workflow.py — BatchWorkflow: fans out to many IssueWorkflows
"""
