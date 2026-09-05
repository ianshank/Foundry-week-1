<!--
Runbook step 2, prompt 1 -- planner.

TEMPLATE. Paste a real proposal from $PLANLINT_TARGET/openspec/changes/<change>/proposal.md
into the block below before running, and commit the filled copy so the four
cells are comparing the same input. A synthetic proposal would measure prose
quality; a real one measures whether the model can hold your acceptance
criteria in view.

Pick a change that already has at least one known gap -- an unpaired
requirement, a criterion that is untestable as written -- so a cell that finds
nothing is a miss rather than a coin flip. Note the known gaps here before you
run, so the scoring is not retrofitted:

  Known gaps in this proposal (fill in before running):
    1.
    2.

Expected: NOT_APPLICABLE (no tool run to judge). This prompt scores reasoning
quality, not exit-code fidelity.
-->

Review this OpenSpec change proposal against its own acceptance criteria.

For each requirement, say whether the stated criteria would actually verify it,
and name any requirement whose criteria are missing, untestable, or verify
something narrower than the requirement claims. Be specific about which line
you are objecting to. Do not rewrite the proposal.

```markdown
<<< PASTE proposal.md HERE >>>
```
