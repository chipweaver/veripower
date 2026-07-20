"""TDD tests for the flash-attention golden reference (§1.4 golden, piece (i)).

The reference is an ORACLE: if it is subtly wrong, every adjudication verdict is
wrong. So its correctness rests on KNOWN-ANSWER cases (uniform / single-term /
causal softmax, hand-computable exactly) plus structural INVARIANTS (row-sum,
convexity, mask-zeros, determinism), not on trust.

Run:  python3 -m pytest eval/golden/flash_attn/test_reference.py -q
"""

import reference as ref

# fp16-exact building blocks (all integers 1..16 are exact in fp16, so
# hand-computed means below are exact and precision-robust).
V_RAMP = [
    [1.0, 2.0, 3.0, 4.0],
    [5.0, 6.0, 7.0, 8.0],
    [9.0, 10.0, 11.0, 12.0],
    [13.0, 14.0, 15.0, 16.0],
]
ZEROS = [[0.0] * 4 for _ in range(4)]

EXACT = 1e-6  # exact-arithmetic cases (only fp32 output rounding intrudes)


# --------------------------------------------------------------------------- #
# fp16 quantization — must be IEEE-754 half exact                             #
# --------------------------------------------------------------------------- #
def test_quantize_fp16_representable_values_unchanged():
    for x in (0.0, 1.0, 2.0, -4.0, 16.0, 0.5):
        assert ref.quantize_fp16(x) == x


def test_quantize_fp16_rounds_to_nearest_half():
    # 0.1 is not representable in fp16; nearest half is 0x2E66.
    assert ref.quantize_fp16(0.1) == 0.0999755859375


def test_quantize_fp16_is_idempotent():
    for x in (0.1, 0.333333, -1.2345, 3.14159):
        q = ref.quantize_fp16(x)
        assert ref.quantize_fp16(q) == q


# --------------------------------------------------------------------------- #
# QK scores — raw Q·Kᵀ with the pinned 1/√d = 0.5 scale                        #
# --------------------------------------------------------------------------- #
def test_qk_scores_apply_inverse_sqrt_d_scale():
    Q = [[1.0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
    K = [[2.0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
    S = ref.qk_scores(Q, K)
    assert S[0][0] == 1.0  # raw dot 2.0 * (1/√4 = 0.5)
    assert S[1][0] == 0.0
    assert S[0][1] == 0.0


# --------------------------------------------------------------------------- #
# softmax row — safe, exact, mask-aware                                        #
# --------------------------------------------------------------------------- #
def test_softmax_row_sums_to_one():
    P = ref.softmax_row([1.3, -2.0, 0.7, 4.1])
    assert abs(sum(P) - 1.0) < 1e-12


def test_softmax_row_uniform_for_equal_inputs():
    P = ref.softmax_row([0.0, 0.0, 0.0, 0.0])
    assert P == [0.25, 0.25, 0.25, 0.25]


def test_softmax_row_masked_positions_are_exactly_zero():
    P = ref.softmax_row([0.0, 5.0, 5.0, 5.0], mask=[False, True, True, True])
    assert P[1] == 0.0 and P[2] == 0.0 and P[3] == 0.0
    assert P[0] == 1.0  # only the single unmasked term survives


# --------------------------------------------------------------------------- #
# full attention — hand-computable known answers                              #
# --------------------------------------------------------------------------- #
def test_attention_equal_scores_gives_column_mean_of_v():
    # Q=K=0 -> all scores equal -> uniform softmax -> every O row = mean of V.
    out = ref.attention_reference(ZEROS, ZEROS, V_RAMP, causal=False)
    col_mean = [7.0, 8.0, 9.0, 10.0]
    for i in range(4):
        for c in range(4):
            assert abs(out[i][c] - col_mean[c]) < EXACT


def test_attention_causal_row0_selects_v0():
    out = ref.attention_reference(ZEROS, ZEROS, V_RAMP, causal=True)
    for c in range(4):
        assert abs(out[0][c] - V_RAMP[0][c]) < EXACT


def test_attention_causal_lower_triangular_uniform_means():
    # Q=K=0, causal -> row i attends j<=i uniformly -> O[i] = mean of V[0..i].
    out = ref.attention_reference(ZEROS, ZEROS, V_RAMP, causal=True)
    expect = [
        [1.0, 2.0, 3.0, 4.0],  # row 0: V0
        [3.0, 4.0, 5.0, 6.0],  # row 1: (V0+V1)/2
        [5.0, 6.0, 7.0, 8.0],  # row 2: (V0+V1+V2)/3
        [7.0, 8.0, 9.0, 10.0],  # row 3: mean of all
    ]
    for i in range(4):
        for c in range(4):
            assert abs(out[i][c] - expect[i][c]) < EXACT


def test_attention_output_is_convex_combination_of_v():
    st = ref.gen_stimulus(7, causal_en=0)
    out = ref.attention_reference(st["Q"], st["K"], st["V"], causal=False)
    for c in range(4):
        col = [st["V"][j][c] for j in range(4)]
        lo, hi = min(col), max(col)
        for i in range(4):
            assert lo - 1e-4 <= out[i][c] <= hi + 1e-4


# --------------------------------------------------------------------------- #
# stimulus generation — deterministic, fp16, clamped                          #
# --------------------------------------------------------------------------- #
def test_gen_stimulus_is_deterministic_per_seed():
    assert ref.gen_stimulus(42, 0) == ref.gen_stimulus(42, 0)


def test_gen_stimulus_differs_across_seeds():
    assert ref.gen_stimulus(42, 0)["Q"] != ref.gen_stimulus(43, 0)["Q"]


def test_gen_stimulus_values_are_fp16_and_clamped():
    st = ref.gen_stimulus(99, 1)
    for name in ("Q", "K", "V"):
        for row in st[name]:
            for x in row:
                assert ref.quantize_fp16(x) == x  # already fp16
                assert abs(x) <= 4.0  # clamped to ±4σ


# --------------------------------------------------------------------------- #
# vector bundle — the held-out artifact the adjudication TB consumes           #
# --------------------------------------------------------------------------- #
def test_gen_vectors_carries_expected_output_and_keys():
    vecs = ref.gen_vectors(seeds=[1, 2], causal_modes=(0, 1))
    assert len(vecs) == 4  # 2 seeds × 2 modes
    for v in vecs:
        assert set(v) >= {"seed", "causal_en", "Q", "K", "V", "expected_O"}
        assert len(v["expected_O"]) == 4 and len(v["expected_O"][0]) == 4


def test_gen_vectors_expected_output_matches_direct_reference():
    v = ref.gen_vectors(seeds=[5], causal_modes=(1,))[0]
    direct = ref.attention_reference(v["Q"], v["K"], v["V"], causal=True)
    assert v["expected_O"] == direct


# --------------------------------------------------------------------------- #
# TB serialization — the beat bit-packing pinned in the spec (little-endian)   #
# --------------------------------------------------------------------------- #
def test_fp16_bits_known_patterns():
    assert ref.fp16_bits(0.0) == 0x0000
    assert ref.fp16_bits(1.0) == 0x3C00
    assert ref.fp16_bits(2.0) == 0x4000
    assert ref.fp16_bits(0.5) == 0x3800
    assert ref.fp16_bits(-1.0) == 0xBC00


def test_fp16_bits_reinterpret_equals_quantize():
    import struct

    for x in (0.1, -1.2345, 3.14159, 0.0):
        bits = ref.fp16_bits(x)
        back = struct.unpack("<e", struct.pack("<H", bits))[0]
        assert back == ref.quantize_fp16(x)


def test_pack_row_is_little_endian_element_j_at_16j():
    # element 0 -> bits [15:0]; element 3 -> bits [63:48].
    assert ref.pack_row([1.0, 0.0, 0.0, 0.0]) == 0x3C00
    assert ref.pack_row([0.0, 0.0, 0.0, 1.0]) == 0x3C00 << 48
    assert ref.pack_row([1.0, 2.0, 0.0, 0.0]) == 0x40003C00


def test_pack_row_round_trips_to_original_fp16_values():
    st = ref.gen_stimulus(3, causal_en=0)
    row = st["Q"][2]
    beat = ref.pack_row(row)
    import struct

    for j in range(4):
        lane = (beat >> (16 * j)) & 0xFFFF
        assert struct.unpack("<e", struct.pack("<H", lane))[0] == row[j]


def test_emit_tb_token_stream_shape():
    # header N, then per test: 1 (causal) + 12 (beats) + 16 (expected) = 29 tokens.
    vecs = ref.gen_vectors(seeds=[1], causal_modes=(0, 1))  # 2 tests
    toks = ref.emit_tb(vecs).split()
    assert int(toks[0]) == 2
    assert len(toks) == 1 + 2 * 29


def test_emit_tb_beats_decode_back_to_stimulus():
    vecs = ref.gen_vectors(seeds=[8], causal_modes=(0,))
    toks = ref.emit_tb(vecs).split()
    beats_hex = toks[2:14]  # skip N(0), causal(1); 12 beats
    st = vecs[0]
    expect_rows = st["Q"] + st["K"] + st["V"]  # beat order Q,K,V rows 0-3
    import struct

    for b, row in zip(beats_hex, expect_rows):
        beat = int(b, 16)
        decoded = [
            struct.unpack("<e", struct.pack("<H", (beat >> (16 * j)) & 0xFFFF))[0]
            for j in range(4)
        ]
        assert decoded == row
