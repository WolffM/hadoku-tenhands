"""Is a manifest change a *dependency* change, or just bookkeeping?

`protected_paths` is a path deny-list, and for most of what it guards that is
the right question: nobody edits `.github/workflows/**` by accident, so the
fact that it was touched IS the risk. Manifests are the exception. In this
ecosystem `package.json` and `pnpm-lock.yaml` change on nearly every task —
the pre-commit hook bumps the version, the auto-update bot moves `@wolffm/*`
ranges — so a path rule fires on the mechanical part of almost every diff and
essentially never on the thing it was written to catch. Measured on
WolffM/hadoku-watchparty#139: a version bump, one range bump on an existing
dependency, a lockfile touching only packages it already had, and a new
non-lifecycle script — refused, and the fix then had to be written by hand.

So this module asks the narrower question the deny-list was standing in for:

- **A new dependency is new supply chain.** Adding a key to a dependency
  section, or retargeting one at `git:`/`file:`/`http:`/`link:`/`portal:`,
  is refused. Bumping a range on a key that is already there is not.
- **A lifecycle script is arbitrary code at install time.** `postinstall` and
  friends run on every `pnpm install`, on a laptop and in CI, so they are
  refused. An ordinary script (`lint:icons`, `build`) is not: the agent can
  already edit any source file, and a script it can only add is no more reach
  than it already had.
- **Resolution overrides retarget packages silently.** `overrides`,
  `resolutions`, `pnpm.patchedDependencies` and `pnpm.onlyBuiltDependencies`
  can change or execute what a dependency resolves to without touching the
  dependency itself, so they are refused too. Same for `packageManager`,
  which decides which pnpm gets fetched and run.
- **A lockfile may not gain a package.** Version movement inside packages it
  already had is fine; a name that was not there before is a new dependency
  arriving by the back door.

**Two entry points, because the two callers can see different things.**
`classify_files` is exact: the lander has the checkout, so it reads whole
manifests on both sides and knows precisely which section every key sits in.
`classify_diff` is conservative: a gate has only `05-fixed/diff.patch`, whose
hunks routinely omit the enclosing `"scripts": {`, so section is often
unknowable. Rather than guess, it judges by the shape of the VALUE — a
dependency's value is a version specifier, a script's is a command line — and
refuses anything it cannot read at all.

Both directions fail closed. Unparseable JSON, an unreadable file, a diff
line in a form we do not recognise: all refusals. For a rule whose job is to
bound an unreviewed merge, "I cannot tell" is never a pass — the same stance
`protected_paths_untouched` takes on unreadable evidence.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional

# ── what the rules key off ────────────────────────────────────────────────

#: Script keys npm/pnpm execute on their own during an install or publish.
#: These are the ones that turn "edited a manifest" into "ran code on your
#: machine", which is why they are refused while `build` or `lint:icons`
#: are not.
LIFECYCLE_SCRIPTS = frozenset({
    "preinstall", "install", "postinstall",
    "preprepare", "prepare", "postprepare",
    "prepack", "postpack", "prepublish", "prepublishOnly", "postpublish",
    "dependencies", "preuninstall", "uninstall", "postuninstall",
})

#: Manifest sections whose keys ARE dependencies.
DEPENDENCY_SECTIONS = (
    "dependencies", "devDependencies", "peerDependencies",
    "optionalDependencies", "bundleDependencies", "bundledDependencies",
)

#: Dotted key paths that change what resolves or what runs, without ever
#: appearing as a dependency edit. Refused wholesale.
SENSITIVE_PATHS = (
    "overrides", "resolutions", "packageManager",
    "pnpm.overrides", "pnpm.resolutions", "pnpm.patchedDependencies",
    "pnpm.onlyBuiltDependencies", "pnpm.allowedDeprecatedVersions",
)

#: A specifier pointing somewhere other than the registry. `workspace:` is
#: deliberately absent — it resolves inside the repo we are already editing,
#: so it adds no third party.
NON_REGISTRY_PREFIXES = (
    "git:", "git+", "file:", "link:", "portal:", "http:", "https:",
    "github:", "gitlab:", "bitbucket:", "ssh:", "npm:",
)

#: First-party scope. A lockfile may gain these without it being a new
#: third-party dependency — they are our own packages, published by us, and
#: the auto-update bot moves them constantly.
FIRST_PARTY_SCOPE = "@wolffm/"

#: A registry version specifier: `^1.2.3`, `~1.0`, `1.x`, `>=2 <3`, `*`,
#: `workspace:*`, `catalog:`. Deliberately loose — anything that parses as a
#: version range counts, because the consequence of a false positive here is
#: a refusal (safe) and of a false negative is a missed dependency (not).
_VERSION_SPEC = re.compile(
    r"""^\s*(?:
        workspace:.* | catalog:.* | \* |
        [\^~>=<]*\s*v?\d+(?:\.\d+)*(?:[-+.][0-9A-Za-z-.]+)? (?:\s*[-|]{1,2}\s*.*)? |
        \d+\.[x*] | [x*]
    )\s*$""",
    re.VERBOSE,
)

#: One `"key": value` line out of a JSON object, as it appears in a diff.
_JSON_PAIR = re.compile(r'^\s*"((?:[^"\\]|\\.)*)"\s*:\s*(.*?),?\s*$')

#: Structural JSON noise a diff line may legitimately be.
_JSON_STRUCTURAL = re.compile(r"^\s*[\{\}\[\],]*\s*$")


def is_lifecycle_key(key: str) -> bool:
    """True for a script npm runs by itself."""
    return key.split(".")[-1] in LIFECYCLE_SCRIPTS


def is_sensitive_path(path: str) -> bool:
    """True for a dotted path that retargets or executes."""
    return any(path == s or path.startswith(s + ".") for s in SENSITIVE_PATHS)


def in_dependency_section(path: str) -> bool:
    """True for a dotted path naming one package inside a deps section."""
    head = path.split(".")[0]
    return head in DEPENDENCY_SECTIONS or (
        path.startswith("pnpm.") and path.split(".")[1:2] and
        path.split(".")[1] in DEPENDENCY_SECTIONS
    )


def looks_like_dependency_spec(value: str) -> bool:
    """True when a value has the shape of a version specifier.

    This is how `classify_diff` tells `"lodash": "^4.17.21"` (a dependency
    arriving) from `"lint:icons": "hadoku-check-icons ."` (a script) without
    knowing which section the line came from. A script whose body happened to
    read exactly like a semver range would be misread as a dependency and
    refused — the harmless direction.
    """
    v = (value or "").strip().strip('"')
    if not v:
        return False
    if v.startswith(NON_REGISTRY_PREFIXES):
        return True
    return bool(_VERSION_SPEC.match(v))


def targets_non_registry(value: str) -> bool:
    """True when a specifier points outside the registry."""
    return (value or "").strip().strip('"').startswith(NON_REGISTRY_PREFIXES)


# ── the verdict ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ManifestVerdict:
    """Why a manifest change may or may not land unreviewed."""

    ok: bool
    #: One short line naming the first thing that refused, or what passed.
    reason: str
    #: Every refusal, so a caller can report more than the headline.
    refusals: tuple[str, ...] = ()
    #: What the classifier was able to read, for the evidence record.
    details: dict = field(default_factory=dict)


def _ok(reason: str, **details) -> ManifestVerdict:
    return ManifestVerdict(ok=True, reason=reason, details=details)


def _no(refusals: list[str], **details) -> ManifestVerdict:
    return ManifestVerdict(
        ok=False,
        reason="; ".join(refusals[:3]),
        refusals=tuple(refusals),
        details=details,
    )


# ── exact: whole files, both sides (the lander) ───────────────────────────


def _flatten(obj, prefix: str = "") -> dict[str, str]:
    """A JSON object as dotted path -> scalar text.

    Only the shapes a manifest actually uses. A nested object recurses; a
    list or scalar is rendered compactly so a change to it is still visible
    as a value change.
    """
    out: dict[str, str] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}{k}"
            if isinstance(v, dict):
                out.update(_flatten(v, path + "."))
            else:
                out[path] = v if isinstance(v, str) else json.dumps(
                    v, sort_keys=True, separators=(",", ":"))
    return out


def classify_package_json(old_text: str, new_text: str) -> ManifestVerdict:
    """Exact rule over two whole `package.json` files."""
    try:
        old = _flatten(json.loads(old_text or "{}"))
    except ValueError as e:
        return _no([f"could not parse the old package.json: {e}"])
    try:
        new = _flatten(json.loads(new_text or "{}"))
    except ValueError as e:
        return _no([f"could not parse the new package.json: {e}"])

    refusals: list[str] = []
    allowed: list[str] = []

    for path in sorted(set(old) | set(new)):
        before, after = old.get(path), new.get(path)
        if before == after:
            continue

        if is_sensitive_path(path):
            refusals.append(f"{path} changed — it retargets or executes")
            continue

        if path.startswith("scripts.") and is_lifecycle_key(path):
            refusals.append(
                f"{path} is a lifecycle script — it runs on every install")
            continue

        if in_dependency_section(path):
            if before is None:
                refusals.append(f"{path} is a new dependency")
            elif after is None:
                refusals.append(f"{path} was removed")
            elif targets_non_registry(after):
                refusals.append(
                    f"{path} now points outside the registry: {after}")
            else:
                allowed.append(f"{path} {before} -> {after}")
            continue

        # Ordinary metadata and non-lifecycle scripts: `version`, `lint:icons`,
        # `description`. The agent can already edit any source file, so these
        # are not a widening of what it can reach.
        allowed.append(f"{path} changed")

    if refusals:
        return _no(refusals, allowed=allowed)
    return _ok(f"{len(allowed)} manifest change(s), none a dependency",
               allowed=allowed)


def _lock_package_names(text: str) -> set[str]:
    """Every package name a pnpm lockfile mentions.

    Reads the entry KEYS (`'@scope/pkg@1.2.3':`, `lodash@4.17.21:`) under
    `packages:`/`snapshots:` rather than the whole YAML: this has to survive
    lockfile format churn, and the key line is the part that has been stable
    across v6-v9. Anything it cannot split into name+version is returned as
    the raw token, which can only ever cause a refusal.
    """
    names: set[str] = set()
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or not line.endswith(":"):
            continue
        token = line[:-1].strip().strip("'\"")
        if "@" not in token or token.endswith("/"):
            continue
        if token.startswith("@"):
            at = token.rfind("@")
            if at <= 0:
                continue
            name = token[:at]
        else:
            name = token.split("@", 1)[0]
        if name and "/" not in name.rstrip("/") or name.startswith("@"):
            names.add(name)
    return names


def classify_lockfile(old_text: str, new_text: str) -> ManifestVerdict:
    """Exact rule over two whole `pnpm-lock.yaml` files."""
    old = _lock_package_names(old_text)
    new = _lock_package_names(new_text)
    gained = sorted(
        n for n in (new - old) if not n.startswith(FIRST_PARTY_SCOPE))
    if gained:
        return _no(
            [f"the lockfile gained {len(gained)} package(s) it did not have: "
             f"{', '.join(gained[:5])}"],
            gained=gained)
    return _ok(f"lockfile: no new packages ({len(new)} present)")


_REQ_LINE = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*(?:[=<>!~]=?.*)?$")


def classify_requirements(old_text: str, new_text: str) -> ManifestVerdict:
    """Exact rule over two whole `requirements.txt` files."""

    def names(text: str) -> tuple[set[str], list[str]]:
        found, odd = set(), []
        for raw in (text or "").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            if line.startswith("-") or "://" in line or line.startswith("git+"):
                odd.append(line)
                continue
            m = _REQ_LINE.match(line)
            if not m:
                odd.append(line)
                continue
            found.add(m.group(1).lower())
        return found, odd

    old, _ = names(old_text)
    new, new_odd = names(new_text)
    refusals = []
    gained = sorted(new - old)
    if gained:
        refusals.append(
            f"requirements.txt gained {len(gained)} package(s): "
            f"{', '.join(gained[:5])}")
    if new_odd:
        refusals.append(
            f"requirements.txt has {len(new_odd)} line(s) that are not a "
            f"plain pinned package: {new_odd[0][:60]}")
    if refusals:
        return _no(refusals, gained=gained)
    return _ok(f"requirements.txt: no new packages ({len(new)} present)")


def classify_files(
    sides: Mapping[str, tuple[Optional[str], Optional[str]]],
) -> ManifestVerdict:
    """Judge every manifest at once, given `(old_text, new_text)` per path.

    `None` on either side means the file was added or deleted outright, which
    is never bookkeeping — a manifest appearing or vanishing changes what the
    install resolves, and no version-bump story explains it.
    """
    refusals: list[str] = []
    passed: list[str] = []

    for path in sorted(sides):
        old_text, new_text = sides[path]
        if old_text is None or new_text is None:
            verb = "added" if old_text is None else "deleted"
            refusals.append(f"{path} was {verb}")
            continue

        base = path.rsplit("/", 1)[-1]
        if base == "package.json":
            v = classify_package_json(old_text, new_text)
        elif base.endswith("lock.yaml") or base.endswith("lock.json"):
            v = classify_lockfile(old_text, new_text)
        elif base.startswith("requirements") and base.endswith(".txt"):
            v = classify_requirements(old_text, new_text)
        else:
            refusals.append(f"{path}: no rule for this manifest")
            continue

        if v.ok:
            passed.append(f"{path}: {v.reason}")
        else:
            refusals.extend(f"{path}: {r}" for r in v.refusals)

    if refusals:
        return _no(refusals, passed=passed)
    return _ok("; ".join(passed) or "no manifests changed", passed=passed)


# ── conservative: a unified diff only (a gate) ────────────────────────────


def split_diff_by_file(diff_text: str) -> dict[str, list[str]]:
    """Unified diff -> the body lines belonging to each file path."""
    files: dict[str, list[str]] = {}
    current: Optional[str] = None
    for line in (diff_text or "").splitlines():
        if line.startswith("diff --git "):
            current = None
            # `diff --git a/x b/x` — take the b-side, which is the path as it
            # exists after the change.
            parts = line.split(" b/", 1)
            if len(parts) == 2 and parts[1].strip():
                current = parts[1].strip()
                files.setdefault(current, [])
            continue
        if line.startswith("+++ b/"):
            current = line[len("+++ b/"):].strip()
            files.setdefault(current, [])
            continue
        if current is None or line.startswith(("--- ", "+++ ", "index ",
                                               "new file", "deleted file",
                                               "similarity ", "rename ",
                                               "old mode", "new mode")):
            continue
        files[current].append(line)
    return files


def _changed_pairs(lines: Iterable[str]) -> tuple[dict, dict, list[str]]:
    """`(removed, added, unreadable)` for one file's diff body."""
    removed: dict[str, str] = {}
    added: dict[str, str] = {}
    unreadable: list[str] = []
    for line in lines:
        if not line or line[0] not in "+-":
            continue
        body = line[1:]
        if _JSON_STRUCTURAL.match(body):
            continue
        m = _JSON_PAIR.match(body)
        if not m:
            unreadable.append(body.strip()[:80])
            continue
        (added if line[0] == "+" else removed)[m.group(1)] = m.group(2)
    return removed, added, unreadable


def _classify_package_json_diff(lines: list[str]) -> list[str]:
    removed, added, unreadable = _changed_pairs(lines)
    refusals: list[str] = []
    if unreadable:
        refusals.append(
            f"{len(unreadable)} line(s) not readable as a JSON field, so the "
            f"change cannot be judged: {unreadable[0]}")

    for key in sorted(set(added) | set(removed)):
        if is_lifecycle_key(key):
            refusals.append(
                f'"{key}" is a lifecycle script — it runs on every install')
            continue
        if is_sensitive_path(key):
            refusals.append(f'"{key}" retargets or executes')
            continue
        before, after = removed.get(key), added.get(key)
        if before is not None and after is not None:
            if targets_non_registry(after):
                refusals.append(
                    f'"{key}" now points outside the registry: {after}')
            continue
        # Present on one side only. Without the enclosing section we judge by
        # the value: a dependency's is a specifier, a script's is a command.
        value = after if after is not None else before
        if looks_like_dependency_spec(value):
            verb = "added" if after is not None else "removed"
            refusals.append(f'"{key}": {value} — a dependency was {verb}')
    return refusals


def _classify_lock_diff(lines: list[str]) -> list[str]:
    added_names: set[str] = set()
    known: set[str] = set()
    for line in lines:
        if not line:
            continue
        target = added_names if line[0] == "+" else known
        target |= _lock_package_names(line[1:] if line[0] in "+- " else line)
    gained = sorted(
        n for n in (added_names - known) if not n.startswith(FIRST_PARTY_SCOPE))
    if gained:
        return [f"the lockfile gains {len(gained)} package(s) not already in "
                f"it: {', '.join(gained[:5])}"]
    return []


def classify_diff(diff_text: str, manifest_paths: Iterable[str]) -> ManifestVerdict:
    """Judge the manifest parts of a unified diff.

    Sees less than `classify_files` and says so: where a section cannot be
    established it falls back to the value's shape, and any line it cannot
    read at all is a refusal.
    """
    wanted = {p.lstrip("./") for p in manifest_paths}
    if not wanted:
        return _ok("no manifests touched")

    by_file = split_diff_by_file(diff_text)
    refusals: list[str] = []
    seen: list[str] = []

    for path in sorted(wanted):
        lines = by_file.get(path)
        if lines is None:
            # The path was reported as touched but the diff does not contain
            # it. That is exactly the "cannot tell" case.
            refusals.append(f"{path} is not present in the diff, so its "
                            f"change cannot be judged")
            continue
        seen.append(path)
        base = path.rsplit("/", 1)[-1]
        if base == "package.json":
            refusals += [f"{path}: {r}" for r in _classify_package_json_diff(lines)]
        elif base.endswith("lock.yaml") or base.endswith("lock.json"):
            refusals += [f"{path}: {r}" for r in _classify_lock_diff(lines)]
        elif base.startswith("requirements") and base.endswith(".txt"):
            for line in lines:
                if line[:1] == "+" and line[1:].strip():
                    body = line[1:].split("#", 1)[0].strip()
                    if body and (body.startswith("-") or "://" in body
                                 or body.startswith("git+")):
                        refusals.append(
                            f"{path}: {body[:60]} is not a plain pinned package")
        else:
            refusals.append(f"{path}: no rule for this manifest")

    if refusals:
        return _no(refusals, judged=seen)
    return _ok(f"{len(seen)} manifest(s) changed, none a dependency",
               judged=seen)
