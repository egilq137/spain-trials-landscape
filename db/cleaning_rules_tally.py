"""What one load actually changed, counted by field and rule.

db/cleaning_rules.py says what we *would* change. This says what we *did*, on
this run, against this cache. The two are not the same thing, and the
difference is the point: the rules carry counts measured in September 2026, and a REEC refresh
can move every one of them.

Why it exists at all, given that tests/test_cleaning_rules.py already
re-measures the counts:

  * **Provenance.** db/cleaning_rules.py claims "the rules plus the tally are
    enough to get back to any raw value". `data/raw/` is never rewritten, so
    the raw value always exists -- but without a record of which rules fired,
    getting back to it means re-running the loader and diffing. The tally is
    the other half of that claim.
  * **Refresh safety without a test run.** The corpus tests only catch drift
    when somebody runs them. A load reports its own numbers every time, so a
    refresh that doubles the placeholder count is visible immediately.

Deliberately not a log. It counts; it does not record which record each change
happened to. Per-row provenance would be a table the size of the database, and
`data/raw/` already holds every original value.
"""

import collections


class CleaningRulesTally:
    """Counts rule applications. One per load."""

    def __init__(self):
        self._counts = collections.Counter()
        self.records = 0

    def saw_record(self):
        """One more source record examined, changed or not.

        Tracked so the report has a denominator. '4,763 placeholders' means
        something different against 11,847 records than against 20,000.
        """
        self.records += 1

    def applied(self, field, rule):
        """One value in `field` was changed by `rule`."""
        self._counts[(field, rule)] += 1

    def counts(self):
        """{(field, rule): n} — for tests and for the dry run in db/validate."""
        return dict(self._counts)

    def total(self):
        return sum(self._counts.values())

    def report(self):
        """The tally as text, grouped by field, most-changed field first."""
        if not self._counts:
            return ("Cleaning rules tally — {:,} records, nothing changed"
                    .format(self.records))

        by_field = collections.defaultdict(list)
        for (field, rule), count in self._counts.items():
            by_field[field].append((count, rule))

        lines = ["Cleaning rules tally — {:,} records".format(self.records),
                 ""]
        for field in sorted(by_field,
                            key=lambda f: (-sum(c for c, _ in by_field[f]), f)):
            lines.append(field)
            for count, rule in sorted(by_field[field], reverse=True):
                lines.append("    {:<44}{:>9,}".format(rule, count))
        lines += ["", "{:<48}{:>9,}".format("total changes", self.total())]
        return "\n".join(lines)
