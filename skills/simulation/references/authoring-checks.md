# Authoring independent checks

A testpoint's `covers[]` names check hints and their requirement rows. Read those alongside the
original intent and referenced algorithms, register maps or standards. Use the intended behavior
to establish expected results; do not derive a reference model by copying the DUT implementation.
RTL may be inspected to diagnose a discrepancy or determine what stimulus reaches a condition.

Match checks to the behavior: compare values and tolerances for numerical results, transactions
for protocols, and cycle relations where timing is part of the requirement. An empty `covers[]`
does not excuse an ineffective check; the testpoint's stated purpose still needs an independent
expectation. A check that mirrors the output being judged cannot detect an error in that output.

A mismatch must fail the test and appear in its recorded status. For UVM, report errors through
the report server and ensure counters/status reflect them. If a hint or plan conflicts with the
original requirement, investigate and return that defect; do not reproduce it just to match a plan.
