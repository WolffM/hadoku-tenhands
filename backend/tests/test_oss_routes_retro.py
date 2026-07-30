"""Which upstream PR a retro card shows, and what the funnel counts.

An issue accumulates several submitted-PR records over its life — a closed
attempt and a retry, or a real PR plus a later fork-only bookkeeping row —
and the retro view has to pick one. Both rules below were wrong in
production against real `state/` data, and both were invisible: the card
showed *a* PR, just the wrong one.

The fixtures mirror the real records that exposed each bug (see the
docstrings on `_pick_upstream_pr`), including the detail that makes it
subtle: file order is not chronological order.
"""

from routes.oss_routes_retro import _pick_upstream_pr, _went_upstream


def _pr(slug, issue, number, state, submitted_at, url=None):
    return {
        "origin_slug": slug,
        "issue_number": issue,
        "pr_number": number,
        "pr_url": url if url is not None else (
            f"https://github.com/{slug}/pull/{number}" if number else ""),
        "state": state,
        "submitted_at": submitted_at,
    }


def _fork_only(slug, issue, merged_at):
    """A `merged-in-fork-only` row: submission-shaped, but no PR anywhere."""
    return {
        "origin_slug": slug,
        "issue_number": issue,
        "pr_number": None,
        "pr_url": "",
        "state": "merged-in-fork-only",
        "submitted_at": merged_at,
        "merged_at": merged_at,
    }


class TestWentUpstream:
    def test_a_record_with_a_number_and_url_went_upstream(self):
        assert _went_upstream(_pr("microsoft/markitdown", 183, 1619, "open",
                                  "2026-03-14T13:06:52Z"))

    def test_a_fork_only_record_did_not(self):
        assert not _went_upstream(
            _fork_only("microsoft/markitdown", 183, "2026-03-17T18:42:54Z"))

    def test_a_number_without_a_url_is_not_a_link_we_can_show(self):
        assert not _went_upstream(
            _pr("acme/widget", 1, 7, "open", "2026-03-14T00:00:00Z", url=""))


class TestPickUpstreamPR:
    def test_a_real_pr_beats_a_later_fork_only_record(self):
        """markitdown#183: PR #1619 is open; a fork-only row landed 3 days
        later. Preferring the newer row reported "no upstream PR" for an
        issue with a live one."""
        prs = [
            _pr("microsoft/markitdown", 183, 1619, "open", "2026-03-14T13:06:52Z"),
            _fork_only("microsoft/markitdown", 183, "2026-03-17T18:42:54Z"),
        ]
        picked = _pick_upstream_pr(prs, "microsoft/markitdown", 183)
        assert picked["pr_number"] == 1619
        assert picked["state"] == "open"

    def test_newest_submission_wins_regardless_of_file_order(self):
        """PowerToys#22315: the newer open #46315 sits at index 0 and the
        older closed #46124 at the end, so "last match in the list" showed a
        closed PR as the outcome of an issue with an open one."""
        prs = [
            _pr("microsoft/PowerToys", 22315, 46315, "open", "2026-03-20T05:09:56Z"),
            _pr("other/repo", 1, 5, "open", "2026-03-01T00:00:00Z"),
            _pr("microsoft/PowerToys", 22315, 46124, "closed", "2026-03-14T13:07:05Z"),
        ]
        picked = _pick_upstream_pr(prs, "microsoft/PowerToys", 22315)
        assert picked["pr_number"] == 46315

    def test_fork_only_is_still_returned_when_it_is_all_there_is(self):
        """The work happened; the card says "merged in fork only" rather than
        pretending the issue was never touched."""
        prs = [_fork_only("microsoft/fluentui", 28967, "2026-03-20T05:17:45Z")]
        picked = _pick_upstream_pr(prs, "microsoft/fluentui", 28967)
        assert picked["state"] == "merged-in-fork-only"

    def test_no_records_means_no_pr(self):
        assert _pick_upstream_pr([], "acme/widget", 1) is None

    def test_other_issues_records_are_never_borrowed(self):
        prs = [_pr("acme/widget", 2, 9, "open", "2026-03-20T00:00:00Z")]
        assert _pick_upstream_pr(prs, "acme/widget", 1) is None

    def test_a_missing_submitted_at_does_not_crash_or_win(self):
        prs = [
            _pr("acme/widget", 1, 10, "closed", "2026-03-01T00:00:00Z"),
            {"origin_slug": "acme/widget", "issue_number": 1, "pr_number": 11,
             "pr_url": "https://github.com/acme/widget/pull/11", "state": "open"},
        ]
        picked = _pick_upstream_pr(prs, "acme/widget", 1)
        assert picked["pr_number"] == 10
