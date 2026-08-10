"""`TaskRef` — the subject a hadoku-task-automation gate is handed.

crimson-kitty's gates receive an `IssueRef` (fork slug, upstream slug,
upstream number). This pipeline's receive a `TaskRef`. `run_gates` takes the
subject as an opaque value and the registry is namespaced by pipeline, so
each pipeline hands its gates whatever it actually has.

**A note on a design idea we dropped.** The plan was to unify both into one
`WorkRef` to avoid duplication. Having written out the two field sets, that
would have been worse: they overlap on almost nothing, so the union type
would be one where half the fields are always `None` and every gate has to
know which half applies to it. Two small honest types beat one dishonest
one. The anti-duplication rule is about not forking *shared behaviour* —
`fix.py`, `repro.py`, the judge — and those genuinely stay single-copy.

`notes_at_claim` is load-bearing and not a convenience: it is the snapshot
taken when the claim was acquired, and the only notes text a gate may treat
as authorisation. See `task_text.extract_allow_protected`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RepoPolicy:
    """Per-repo gate configuration.

    Defaults are strict on purpose. A stalled task is annoying, visible, and
    fixed on a laptop; a bad unreviewed merge into a repo nobody was watching
    is the failure we are actually trying to avoid. Loosen from evidence
    once a repo has landed a few dozen tasks.
    """

    #: Globs that never auto-merge without an explicit per-task authorisation.
    protected_paths: tuple[str, ...] = (
        # Self-modifying CI. A broken deploy workflow can break the very
        # mechanism that would ship the revert, so this one is not merely
        # sensitive — it can take away our ability to undo.
        ".github/workflows/**",
        # Infra and deploy surface.
        "Dockerfile", "docker-compose*", "deploy/**", "infra/**",
        # Secrets. A leaked credential is the one failure a revert does not
        # undo: the value is burned the moment it is pushed.
        ".devvault.json", ".devvault.local.json", ".env*",
        "**/*secret*", "**/*.pem",
        # Destructive and irreversible.
        "**/migrations/**",
        # New dependencies are new supply chain.
        "package.json", "pnpm-lock.yaml", "requirements.txt",
        # The pipeline's own code. An agent that can edit its own gates is
        # not gated.
        "backend/temporal/**",
    )

    #: Hard cap on how far one task may reach, enforced in `Lander.preflight`.
    #: Scope creep is the most common way a correct fix becomes an
    #: unreviewable one, and nobody reads these diffs before they merge.
    #:
    #: There was a `max_lines_changed: int = 600` here too, declared under the
    #: same comment and read by nothing — `preflight` only ever receives
    #: `changed_files`, so a 3-file 5,000-line diff passed it. Removed rather
    #: than wired up: a cap that exists only as a field reads as protection
    #: that is being applied, which is worse than an honestly absent one.
    max_files_changed: int = 20

    #: The suite that must go green on the merge result before anything is
    #: pushed. Empty means nothing verifies this repo's changes — allowed,
    #: but the lander records it as a loud check rather than passing quietly.
    test_command: tuple[str, ...] = ()

    #: Where `test_command` runs, relative to the checkout root.
    test_cwd: str = "."

    base_branch: str = "main"


@dataclass(frozen=True)
class TaskRef:
    """One board task, as the gates see it."""

    repo_slug: str          # e.g. "WolffM/tenhands"
    board: str              # board handle
    task_id: str
    title: str = ""
    #: `notes` as it stood when we took the claim — the human's version by
    #: construction, since we cannot write before holding the claim.
    notes_at_claim: str = ""
    policy: RepoPolicy = field(default_factory=RepoPolicy)

    @property
    def repo_name(self) -> str:
        return self.repo_slug.split("/")[-1]
