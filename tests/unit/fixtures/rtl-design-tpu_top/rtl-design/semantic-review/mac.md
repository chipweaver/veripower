# mac — intent review

Compared `mac.v` against `mac.md` §2 Interface and §3 Internal Behavior.

The multiply-accumulate behaviour matches §2: single-cycle multiply, registered
accumulate, synchronous clear on `acc_clr`. Nothing blocks.

One thing worth recording, not blocking: `mac.v:18` declares `parameter DATA_W = 32`,
and `mac.md` §1 says the width is fixed at 32 bits. Behaviour at the default is
correct, so this is unrequested configurability rather than a defect. The fix, if
anyone wants it, is in this child's RTL.
