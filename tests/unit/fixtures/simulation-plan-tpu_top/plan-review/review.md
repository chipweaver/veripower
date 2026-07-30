# tpu_top plan-adequacy review

## TP-MAC-FUNC under-stimulates the column carry chain

**Compared against** `design.md` §1.5 SC-002 and `CHK-MAC-05`.
**Blocks:** no.
`TP-MAC-FUNC` covers CHK-MAC-05 (the `mac00_out → mac_10.i_pre_result` column chain) and its bins
name `data_forward`, but the sequences linked to it drive a single weight set. The chained
accumulation is exercised, so this is not an uncovered behaviour — it is thin stimulus, and the
coverage bins will show it if it matters.

## Every skipped_checks[] entry: none to review

**Compared against** the aggregated `check-hints/*.json`.
**Blocks:** no.
`skipped_checks[]` is empty and all 30 authored check_ids are covered, so there is no skip
justification to weigh.
