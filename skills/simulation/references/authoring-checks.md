# Authoring checks from the check hints

A testpoint's `covers[]` names check hints; each hint lives in `<check_hints>/check-hints.json` and
names the `<requirements>/requirements.json` rows it establishes. Read the hint by `check_id` and
the rows by `id`; the row's `verbatim` is what the check exists to establish, the hint's
`observable` and `reference_rule` say how.

A row that points at a file beside the intent document — a reference model, a register map, a
standard — is read there, under `<intent>/`; a bit-exact reference algorithm the engineer
delivered is what your refmodel ports. Derive the golden model from those files, never from the RTL. A model reverse-engineered from
the DUT mirrors the implementation, bugs included, and can never disagree. A hint whose rule does
not let you author the check without the RTL is a specification defect: end with
`STATUS: BLOCKED check-hints incomplete: <check_id list>` rather than reading the RTL.

Every covered hint gets a cycle-accurate check: an assignment formula becomes `assign exp_<sig>`
compared with `===` on every clock edge, a behavioural or algorithmic rule becomes a model whose
output is compared, an error-trigger rule becomes time-domain monitoring of the trigger. A
mismatch is `` `uvm_error `` and increments a counter that the report reads; never `$fatal`, which
bypasses the UVM report server, and never a mismatch downgraded to `uvm_info`.

A testpoint with an empty `covers[]` is a scenario the plan author added; a functional model is
fine there, but the check must still be able to disagree.
