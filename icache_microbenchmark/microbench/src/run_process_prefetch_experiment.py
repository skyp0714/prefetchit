#!/usr/bin/env python3
import argparse
import csv
import random
import re
import subprocess
from pathlib import Path


FAIR_CASES = [
    ("baseline (no prefetch)", "baseline", ["none"]),
    ("advance execution", "fair_advance_execution", None),
    ("data T0", "fair_data_prefetcht0", None),
    ("data T0 multiline", "fair_data_prefetcht0_lines", None),
    ("data T1", "fair_data_prefetcht1", None),
    ("data T1 multiline", "fair_data_prefetcht1_lines", None),
    ("code IT0", "fair_code_prefetchit0", None),
    ("code IT0 multiline", "fair_code_prefetchit0_lines", None),
    ("code IT1", "fair_code_prefetchit1", None),
    ("code IT1 multiline", "fair_code_prefetchit1_lines", None),
]

CORE_ROUND_CASES = [
    ("baseline (no prefetch)", "baseline", None),
    ("data T0 multiline", "fair_data_prefetcht0_lines", None),
    ("code IT0 fixed p2 strong far", "fair_code_prefetchit0_fixed_p2_strong_far_tlb4", None),
    ("advance execution", "fair_advance_execution", None),
]

CPUID_FAR_CASES = [
    ("baseline (no prefetch)", "baseline", None),
    ("data T0 multiline", "fair_data_prefetcht0_lines", None),
    ("code IT0 p2 far cpuid", "fair_code_prefetchit0_p2_far_tlb2_cpuid_after", None),
    ("code IT0 p2 strong far", "fair_code_prefetchit0_p2_strong_far_tlb2", None),
    ("code IT0 fixed p2 strong far", "fair_code_prefetchit0_fixed_p2_strong_far_tlb4", None),
    ("code IT0 cpuid p2 cpuid far", "fair_code_prefetchit0_cpuid_p2_cpuid_far", None),
    ("code IT0 cpuid p2 far cpuid", "fair_code_prefetchit0_cpuid_p2_far_cpuid", None),
    ("code IT0 far cpuid p2 far", "fair_code_prefetchit0_far_cpuid_p2_far", None),
    ("code IT0 cpuid far p2 far cpuid", "fair_code_prefetchit0_cpuid_far_p2_far_cpuid", None),
    ("code IT1 p2 strong far", "fair_code_prefetchit1_p2_strong_far_tlb4", None),
    ("code IT1 strong farfunc burst", "fair_code_prefetchit1_strong_farfunc_burst4_far_tlb2", None),
    ("code IT1 cpuid p2 cpuid far", "fair_code_prefetchit1_cpuid_p2_cpuid_far", None),
    ("code IT1 cpuid p2 far cpuid", "fair_code_prefetchit1_cpuid_p2_far_cpuid", None),
    ("code IT1 far cpuid p2 far", "fair_code_prefetchit1_far_cpuid_p2_far", None),
    ("code IT1 cpuid far p2 far cpuid", "fair_code_prefetchit1_cpuid_far_p2_far_cpuid", None),
    ("advance execution", "fair_advance_execution", None),
]

NOHELPER_SEARCH_CASES = [
    ("baseline (no prefetch)", "baseline", None),
    ("data T0 multiline", "fair_data_prefetcht0_lines", None),
    ("code IT0 far lines", "fair_code_prefetchit0_lines", None),
    ("code IT0 repeat lines", "fair_code_prefetchit0_forced_repeat_lines", None),
    ("code IT0 branch miss", "fair_code_prefetchit0_branch_misp_lines", None),
    ("code IT0 branch call", "fair_code_prefetchit0_branch_call_lines", None),
    ("code IT0 indirect call", "fair_code_prefetchit0_indirect_call_lines", None),
    ("code IT0 complex flow", "fair_code_prefetchit0_complex_lines", None),
    ("code IT0 path complex", "fair_code_prefetchit0_path_complex_lines", None),
    ("code IT0 nested scatter", "fair_code_prefetchit0_nested_scatter", None),
    ("code IT0 nested far", "fair_code_prefetchit0_nested_far_scatter", None),
    ("code IT0 nested far deep", "fair_code_prefetchit0_nested_far_deep_scatter", None),
    ("code IT0 nested per target", "fair_code_prefetchit0_nested_per_target_far", None),
    ("code IT0 nested window", "fair_code_prefetchit0_nested_window_p2_far", None),
    ("code IT0 nested window per target", "fair_code_prefetchit0_nested_window_per_target", None),
    ("code IT0 nested far window", "fair_code_prefetchit0_nested_window_far_p2_far", None),
    ("code IT0 branch actual", "fair_code_prefetchit0_branch_actual_p2_far", None),
    ("code IT0 branch far actual", "fair_code_prefetchit0_branch_actual_far_p2_far", None),
    ("code IT0 branch nested actual", "fair_code_prefetchit0_branch_actual_nested_p2_far", None),
    ("code IT0 branch repeat", "fair_code_prefetchit0_branch_actual_repeat", None),
    ("code IT0 far branch", "fair_code_prefetchit0_far_branch_actual_p2_far", None),
    ("code IT0 branch farpath", "fair_code_prefetchit0_branch_farpath_p2_far", None),
    ("code IT0 branch farpath far", "fair_code_prefetchit0_branch_farpath_far_p2_far", None),
    ("code IT0 branch farpath repeat", "fair_code_prefetchit0_branch_farpath_repeat", None),
    ("code IT0 cpuid after", "fair_code_prefetchit0_cpuid_after_lines", None),
    ("code IT0 before far big", "fair_code_prefetchit0_before_far_big", None),
    ("code IT0 before far huge", "fair_code_prefetchit0_before_far_huge", None),
    ("code IT0 before far cpuid", "fair_code_prefetchit0_before_far_cpuid_after", None),
    ("code IT0 after far coldline", "fair_code_prefetchit0_after_far_coldline_spaced32", None),
    ("code IT0 before far coldline", "fair_code_prefetchit0_before_far_coldline_spaced32", None),
    ("code IT0 between cold calls", "fair_code_prefetchit0_between_cold_calls", None),
    ("code IT0 before branch far", "fair_code_prefetchit0_before_branch_misp_far", None),
    ("code IT0 before indirect far", "fair_code_prefetchit0_before_indirect_misp_far", None),
    ("code IT0 repeat16 cpuid", "fair_code_prefetchit0_repeat16_cpuid_after", None),
    ("code IT0 repeat64 cpuid", "fair_code_prefetchit0_repeat64_cpuid_after", None),
    ("code IT0 repeat16 far", "fair_code_prefetchit0_repeat16_before_far_big", None),
    ("code IT0 repeat64 far", "fair_code_prefetchit0_repeat64_before_far_big", None),
    ("code IT0 wrongpath branch", "fair_code_prefetchit0_wrongpath_slow_branch", None),
    ("code IT0 wrongpath cpuid", "fair_code_prefetchit0_wrongpath_cpuid_after", None),
    ("code IT0 wrongpath far", "fair_code_prefetchit0_wrongpath_far_after", None),
    ("code IT0 wrongpath data branch", "fair_code_prefetchit0_wrongpath_data_slow_branch", None),
    ("code IT0 wrongpath data cpuid", "fair_code_prefetchit0_wrongpath_data_cpuid_after", None),
    ("code IT0 wrongpath data far", "fair_code_prefetchit0_wrongpath_data_far_after", None),
    ("code IT0 wrongpath deep", "fair_code_prefetchit0_wrongpath_deep_repeat4_cpuid_after", None),
    ("code IT0 wrongpath chase", "fair_code_prefetchit0_wrongpath_chase256_cpuid_after", None),
    ("code IT0 inline chase", "fair_code_prefetchit0_inline_chase4096_burst4", None),
    ("code IT0 inline chase fixed", "fair_code_prefetchit0_inline_chase4096_fixed_burst4", None),
    ("code IT0 trained inline chase", "fair_code_prefetchit0_trained_inline_chase4096_burst4", None),
    ("code IT0 trained inline fixed", "fair_code_prefetchit0_trained_inline_chase4096_fixed_burst4", None),
    ("code IT0 slow taken branch", "fair_code_prefetchit0_slow_taken_branch", None),
    ("code IT0 slow taken cpuid", "fair_code_prefetchit0_slow_taken_cpuid_after", None),
    ("code IT0 trained wrongpath", "fair_code_prefetchit0_trained_wrongpath_flush", None),
    ("code IT0 deep trained wrongpath", "fair_code_prefetchit0_deep_trained_wrongpath_flush", None),
    ("code IT0 deep spaced wrongpath", "fair_code_prefetchit0_deep_spaced32_trained_wrongpath_flush", None),
    ("code IT0 burst4", "fair_code_prefetchit0_burst4_spaced32", None),
    ("code IT0 burst8", "fair_code_prefetchit0_burst8_spaced32", None),
    ("code IT0 burst4 longgap", "fair_code_prefetchit0_burst4_spaced128", None),
    ("code IT0 fixed path", "fair_code_prefetchit0_fixed_path_spaced32", None),
    ("code IT0 fixed path far", "fair_code_prefetchit0_fixed_path_before_far_big", None),
    ("code IT0 p2 far", "fair_code_prefetchit0_p2_far_tlb2", None),
    ("code IT0 p4 far", "fair_code_prefetchit0_p4_far_tlb2", None),
    ("code IT0 p2 far4", "fair_code_prefetchit0_p2_far_tlb4", None),
    ("code IT0 fixed p2 far", "fair_code_prefetchit0_fixed_p2_far_tlb2", None),
    ("code IT0 fixed p4 far", "fair_code_prefetchit0_fixed_p4_far_tlb4", None),
    ("code IT0 p far p far", "fair_code_prefetchit0_p_far_p_far", None),
    ("code IT0 far p2 far", "fair_code_prefetchit0_far_p2_far", None),
    ("code IT0 far2 p2", "fair_code_prefetchit0_far2_p2", None),
    ("code IT0 p2 far cpuid", "fair_code_prefetchit0_p2_far_tlb2_cpuid_after", None),
    ("code IT0 p2 strong far", "fair_code_prefetchit0_p2_strong_far_tlb2", None),
    ("code IT0 p2 strong far4", "fair_code_prefetchit0_p2_strong_far_tlb4", None),
    ("code IT0 far p2 strong", "fair_code_prefetchit0_far_p2_strong_far", None),
    ("code IT0 p2 strong repeat", "fair_code_prefetchit0_p2_strong_far_repeat", None),
    ("code IT0 fixed p2 strong", "fair_code_prefetchit0_fixed_p2_strong_far_tlb4", None),
    ("code IT0 cpuid p2 cpuid far", "fair_code_prefetchit0_cpuid_p2_cpuid_far", None),
    ("code IT0 cpuid p2 far cpuid", "fair_code_prefetchit0_cpuid_p2_far_cpuid", None),
    ("code IT0 far cpuid p2 far", "fair_code_prefetchit0_far_cpuid_p2_far", None),
    ("code IT0 cpuid far p2 far cpuid", "fair_code_prefetchit0_cpuid_far_p2_far_cpuid", None),
    ("code IT0 far AB p2 far CD", "fair_code_prefetchit0_far_ab_p2_far_cd", None),
    ("code IT0 far AB p4 far CD", "fair_code_prefetchit0_far_ab_p4_far_cd", None),
    ("code IT0 fixed far AB p2 far CD", "fair_code_prefetchit0_fixed_far_ab_p2_far_cd", None),
    ("code IT0 strong farfunc burst", "fair_code_prefetchit0_strong_farfunc_burst4_far_tlb2", None),
    ("code IT0 strong farfunc path", "fair_code_prefetchit0_strong_farfunc_path_far_tlb2", None),
    ("code IT0 far burst4", "fair_code_prefetchit0_far_burst4_spaced32", None),
    ("code IT0 far burst8", "fair_code_prefetchit0_far_burst8_spaced32", None),
    ("code IT0 far burst4 longgap", "fair_code_prefetchit0_far_burst4_spaced128", None),
    ("code IT0 call pre", "fair_code_prefetchit0_call_window_pre10", None),
    ("code IT0 call post", "fair_code_prefetchit0_call_window_post10", None),
    ("code IT0 call burst pre", "fair_code_prefetchit0_call_window_burst4_pre10", None),
    ("code IT0 call burst post", "fair_code_prefetchit0_call_window_burst4_post10", None),
    ("code IT1 far lines", "fair_code_prefetchit1_lines", None),
    ("code IT1 before far big", "fair_code_prefetchit1_before_far_big", None),
    ("code IT1 after far coldline", "fair_code_prefetchit1_after_far_coldline_spaced32", None),
    ("code IT1 repeat16 cpuid", "fair_code_prefetchit1_repeat16_cpuid_after", None),
    ("code IT1 wrongpath branch", "fair_code_prefetchit1_wrongpath_slow_branch", None),
    ("code IT1 wrongpath chase", "fair_code_prefetchit1_wrongpath_chase256_cpuid_after", None),
    ("code IT1 deep spaced wrongpath", "fair_code_prefetchit1_deep_spaced32_trained_wrongpath_flush", None),
    ("code IT1 burst4", "fair_code_prefetchit1_burst4_spaced32", None),
    ("code IT1 p2 far", "fair_code_prefetchit1_p2_far_tlb2", None),
    ("code IT1 p2 strong far", "fair_code_prefetchit1_p2_strong_far_tlb4", None),
    ("code IT1 cpuid p2 cpuid far", "fair_code_prefetchit1_cpuid_p2_cpuid_far", None),
    ("code IT1 cpuid p2 far cpuid", "fair_code_prefetchit1_cpuid_p2_far_cpuid", None),
    ("code IT1 far cpuid p2 far", "fair_code_prefetchit1_far_cpuid_p2_far", None),
    ("code IT1 cpuid far p2 far cpuid", "fair_code_prefetchit1_cpuid_far_p2_far_cpuid", None),
    ("code IT1 strong farfunc burst", "fair_code_prefetchit1_strong_farfunc_burst4_far_tlb2", None),
    ("code IT1 far burst4", "fair_code_prefetchit1_far_burst4_spaced32", None),
    ("code IT1 call burst pre", "fair_code_prefetchit1_call_window_burst4_pre10", None),
    ("advance execution", "fair_advance_execution", None),
]

BRANCHWIN_CASES = [
    ("baseline (no prefetch)", "baseline", None),
    ("data T0 multiline", "fair_data_prefetcht0_lines", None),
    ("code IT0 branchwin target o0", "fair_code_prefetchit0_branchwin_target_o0", None),
    ("code IT0 branchwin target o1", "fair_code_prefetchit0_branchwin_target_o1", None),
    ("code IT0 branchwin target o2", "fair_code_prefetchit0_branchwin_target_o2", None),
    ("code IT0 branchwin target o4", "fair_code_prefetchit0_branchwin_target_o4", None),
    ("code IT0 branchwin target o8", "fair_code_prefetchit0_branchwin_target_o8", None),
    ("code IT0 branchwin target o16", "fair_code_prefetchit0_branchwin_target_o16", None),
    ("code IT0 branchwin wrong o0", "fair_code_prefetchit0_branchwin_wrong_o0", None),
    ("code IT0 branchwin wrong o1", "fair_code_prefetchit0_branchwin_wrong_o1", None),
    ("code IT0 branchwin wrong o2", "fair_code_prefetchit0_branchwin_wrong_o2", None),
    ("code IT0 branchwin wrong o4", "fair_code_prefetchit0_branchwin_wrong_o4", None),
    ("code IT0 branchwin wrong o8", "fair_code_prefetchit0_branchwin_wrong_o8", None),
    ("code IT0 branchwin wrong o16", "fair_code_prefetchit0_branchwin_wrong_o16", None),
    ("code IT0 branchwin before o0", "fair_code_prefetchit0_branchwin_before_o0", None),
    ("code IT0 branchwin before o1", "fair_code_prefetchit0_branchwin_before_o1", None),
    ("code IT0 branchwin before o2", "fair_code_prefetchit0_branchwin_before_o2", None),
    ("code IT0 branchwin before o4", "fair_code_prefetchit0_branchwin_before_o4", None),
    ("code IT0 branchwin before o8", "fair_code_prefetchit0_branchwin_before_o8", None),
    ("code IT0 branchwin before o16", "fair_code_prefetchit0_branchwin_before_o16", None),
    ("code IT0 branchwin target head o0", "fair_code_prefetchit0_branchwin_target_head_o0", None),
    ("code IT0 branchwin target head o1", "fair_code_prefetchit0_branchwin_target_head_o1", None),
    ("code IT0 branchwin target head o2", "fair_code_prefetchit0_branchwin_target_head_o2", None),
    ("code IT0 branchwin target head o4", "fair_code_prefetchit0_branchwin_target_head_o4", None),
    ("code IT0 branchwin target head o8", "fair_code_prefetchit0_branchwin_target_head_o8", None),
    ("code IT0 branchwin target head o16", "fair_code_prefetchit0_branchwin_target_head_o16", None),
    ("code IT0 branchwin wrong head o0", "fair_code_prefetchit0_branchwin_wrong_head_o0", None),
    ("code IT0 branchwin wrong head o1", "fair_code_prefetchit0_branchwin_wrong_head_o1", None),
    ("code IT0 branchwin wrong head o2", "fair_code_prefetchit0_branchwin_wrong_head_o2", None),
    ("code IT0 branchwin wrong head o4", "fair_code_prefetchit0_branchwin_wrong_head_o4", None),
    ("code IT0 branchwin wrong head o8", "fair_code_prefetchit0_branchwin_wrong_head_o8", None),
    ("code IT0 branchwin wrong head o16", "fair_code_prefetchit0_branchwin_wrong_head_o16", None),
    ("code IT0 branchwin fallwrong o0", "fair_code_prefetchit0_branchwin_fallwrong_o0", None),
    ("code IT0 branchwin fallwrong o1", "fair_code_prefetchit0_branchwin_fallwrong_o1", None),
    ("code IT0 branchwin fallwrong o2", "fair_code_prefetchit0_branchwin_fallwrong_o2", None),
    ("code IT0 branchwin fallwrong o4", "fair_code_prefetchit0_branchwin_fallwrong_o4", None),
    ("code IT0 branchwin fallwrong o8", "fair_code_prefetchit0_branchwin_fallwrong_o8", None),
    ("code IT0 branchwin fallwrong o16", "fair_code_prefetchit0_branchwin_fallwrong_o16", None),
    ("code IT0 branchwin fallcorrect o0", "fair_code_prefetchit0_branchwin_fallcorrect_o0", None),
    ("code IT0 branchwin fallcorrect o1", "fair_code_prefetchit0_branchwin_fallcorrect_o1", None),
    ("code IT0 branchwin fallcorrect o2", "fair_code_prefetchit0_branchwin_fallcorrect_o2", None),
    ("code IT0 branchwin fallcorrect o4", "fair_code_prefetchit0_branchwin_fallcorrect_o4", None),
    ("code IT0 branchwin fallcorrect o8", "fair_code_prefetchit0_branchwin_fallcorrect_o8", None),
    ("code IT0 branchwin fallcorrect o16", "fair_code_prefetchit0_branchwin_fallcorrect_o16", None),
    ("code IT0 branchwin fallwrong head o0", "fair_code_prefetchit0_branchwin_fallwrong_head_o0", None),
    ("code IT0 branchwin fallwrong head o1", "fair_code_prefetchit0_branchwin_fallwrong_head_o1", None),
    ("code IT0 branchwin fallwrong head o2", "fair_code_prefetchit0_branchwin_fallwrong_head_o2", None),
    ("code IT0 branchwin fallwrong head o4", "fair_code_prefetchit0_branchwin_fallwrong_head_o4", None),
    ("code IT0 branchwin fallwrong head o8", "fair_code_prefetchit0_branchwin_fallwrong_head_o8", None),
    ("code IT0 branchwin fallwrong head o16", "fair_code_prefetchit0_branchwin_fallwrong_head_o16", None),
    ("code IT0 branchwin fallcorrect head o0", "fair_code_prefetchit0_branchwin_fallcorrect_head_o0", None),
    ("code IT0 branchwin fallcorrect head o1", "fair_code_prefetchit0_branchwin_fallcorrect_head_o1", None),
    ("code IT0 branchwin fallcorrect head o2", "fair_code_prefetchit0_branchwin_fallcorrect_head_o2", None),
    ("code IT0 branchwin fallcorrect head o4", "fair_code_prefetchit0_branchwin_fallcorrect_head_o4", None),
    ("code IT0 branchwin fallcorrect head o8", "fair_code_prefetchit0_branchwin_fallcorrect_head_o8", None),
    ("code IT0 branchwin fallcorrect head o16", "fair_code_prefetchit0_branchwin_fallcorrect_head_o16", None),
    ("advance execution", "fair_advance_execution", None),
]

BRANCHWIN_SLOW_CASES = [
    (
        f"code IT0 branchwin slow {family} {kind} o{offset}",
        f"fair_code_prefetchit0_branchwin_slow_{family}_{kind}_o{offset}",
        None,
    )
    for family in ("target", "fallwrong", "fallcorrect")
    for kind in ("head", "lines")
    for offset in range(9)
]

BRANCHWIN_CASES = BRANCHWIN_CASES[:-1] + BRANCHWIN_SLOW_CASES + BRANCHWIN_CASES[-1:]
BRANCHWIN_CASES = BRANCHWIN_CASES[:-1] + [
    ("data T0 branchwin slow target lines o5", "fair_data_prefetcht0_branchwin_slow_target_lines_o5", None),
    ("data T0 branchwin slow fallcorrect lines o1", "fair_data_prefetcht0_branchwin_slow_fallcorrect_lines_o1", None),
] + BRANCHWIN_CASES[-1:]

BRANCHWIN_FARBLOCK_CASES = [
    (
        f"code IT0 branchwin slow target farblock {kind} o{offset}",
        f"fair_code_prefetchit0_branchwin_slow_target_farblock_{kind}_o{offset}",
        None,
    )
    for kind in ("head", "lines")
    for offset in range(9)
]

BRANCHWIN_CASES = BRANCHWIN_CASES[:-1] + BRANCHWIN_FARBLOCK_CASES + [
    ("data T0 branchwin slow target farblock lines o0", "fair_data_prefetcht0_branchwin_slow_target_farblock_lines_o0", None),
] + BRANCHWIN_CASES[-1:]

BRANCHWIN_BEFOREFAR_CASES = [
    (
        f"code IT0 branchwin slow before farbranch {kind} o{offset}",
        f"fair_code_prefetchit0_branchwin_slow_before_farbranch_{kind}_o{offset}",
        None,
    )
    for kind in ("head", "lines")
    for offset in range(9)
]

BRANCHWIN_CASES = BRANCHWIN_CASES[:-1] + BRANCHWIN_BEFOREFAR_CASES + [
    ("data T0 branchwin slow before farbranch lines o0", "fair_data_prefetcht0_branchwin_slow_before_farbranch_lines_o0", None),
    ("code IT0 branchwin slow before farstorm lines", "fair_code_prefetchit0_branchwin_slow_before_farstorm_lines", None),
    ("data T0 branchwin slow before farstorm lines", "fair_data_prefetcht0_branchwin_slow_before_farstorm_lines", None),
    ("code IT1 branchwin slow target farblock lines o0", "fair_code_prefetchit1_branchwin_slow_target_farblock_lines_o0", None),
    ("code IT1 branchwin slow before farbranch lines o7", "fair_code_prefetchit1_branchwin_slow_before_farbranch_lines_o7", None),
    ("code IT1 branchwin slow before farstorm lines", "fair_code_prefetchit1_branchwin_slow_before_farstorm_lines", None),
    ("code IT0 branchwin slow both farblock lines", "fair_code_prefetchit0_branchwin_slow_both_farblock_lines", None),
    ("data T0 branchwin slow both farblock lines", "fair_data_prefetcht0_branchwin_slow_both_farblock_lines", None),
    ("code IT0 branchwin slow before farstorm bar lines", "fair_code_prefetchit0_branchwin_slow_before_farstorm_bar_lines", None),
    ("data T0 branchwin slow before farstorm bar lines", "fair_data_prefetcht0_branchwin_slow_before_farstorm_bar_lines", None),
    ("code branchwin slow before farstorm nopref", "fair_code_branchwin_slow_before_farstorm_nopref", None),
] + BRANCHWIN_CASES[-1:]

IT0_SEARCH_CASES = [
    ("baseline (no prefetch)", "baseline", ["none"]),
    ("advance execution", "fair_advance_execution", None),
    ("data T0", "fair_data_prefetcht0", None),
    ("data T0 multiline", "fair_data_prefetcht0_lines", None),
    ("data T1", "fair_data_prefetcht1", None),
    ("data T1 multiline", "fair_data_prefetcht1_lines", None),
    ("code IT0 forced lines", "fair_code_prefetchit0_lines", None),
    ("code IT0 noflush lines", "fair_code_prefetchit0_noflush_lines", None),
    ("code IT0 repeat lines", "fair_code_prefetchit0_forced_repeat_lines", None),
    ("code IT0 branch miss", "fair_code_prefetchit0_branch_misp_lines", None),
    ("code IT0 branch call", "fair_code_prefetchit0_branch_call_lines", None),
    ("code IT0 indirect call", "fair_code_prefetchit0_indirect_call_lines", None),
    ("code IT0 complex flow", "fair_code_prefetchit0_complex_lines", None),
    ("code IT0 path lines", "fair_code_prefetchit0_path_lines", None),
    ("code IT0 path repeat", "fair_code_prefetchit0_path_repeat_lines", None),
    ("code IT0 path branch", "fair_code_prefetchit0_path_branch_call_lines", None),
    ("code IT0 path indirect", "fair_code_prefetchit0_path_indirect_call_lines", None),
    ("code IT0 path complex", "fair_code_prefetchit0_path_complex_lines", None),
    ("code IT0 nested scatter", "fair_code_prefetchit0_nested_scatter", None),
    ("code IT0 nested far", "fair_code_prefetchit0_nested_far_scatter", None),
    ("code IT0 nested far deep", "fair_code_prefetchit0_nested_far_deep_scatter", None),
    ("code IT0 nested per target", "fair_code_prefetchit0_nested_per_target_far", None),
    ("code IT0 dtlb prime", "fair_code_prefetchit0_dtlb_prime_lines", None),
    ("code IT0 dtlb path", "fair_code_prefetchit0_dtlb_prime_path_lines", None),
    ("code IT0 dtlb repeat", "fair_code_prefetchit0_dtlb_prime_repeat_lines", None),
    ("code IT0 dtlb path repeat", "fair_code_prefetchit0_dtlb_prime_path_repeat_lines", None),
    ("code IT0 dtlb branch", "fair_code_prefetchit0_dtlb_prime_branch_call_lines", None),
    ("code IT0 dtlb indirect", "fair_code_prefetchit0_dtlb_prime_indirect_call_lines", None),
    ("code IT0 cpuid after", "fair_code_prefetchit0_cpuid_after_lines", None),
    ("code IT0 path cpuid after", "fair_code_prefetchit0_path_cpuid_after_lines", None),
    ("code IT0 before far small", "fair_code_prefetchit0_before_far_small", None),
    ("code IT0 before far big", "fair_code_prefetchit0_before_far_big", None),
    ("code IT0 before far huge", "fair_code_prefetchit0_before_far_huge", None),
    ("code IT0 before far cpuid after", "fair_code_prefetchit0_before_far_cpuid_after", None),
    ("code IT0 path before far big", "fair_code_prefetchit0_path_before_far_big", None),
    ("code IT1 before far big", "fair_code_prefetchit1_before_far_big", None),
    ("code shape after far coldline", "fair_code_shape_after_far_coldline", None),
    ("code IT0 after far coldline", "fair_code_prefetchit0_after_far_coldline", None),
    ("code IT0 after far coldline spaced32", "fair_code_prefetchit0_after_far_coldline_spaced32", None),
    ("code IT1 after far coldline spaced32", "fair_code_prefetchit1_after_far_coldline_spaced32", None),
    ("code IT0 before far coldline", "fair_code_prefetchit0_before_far_coldline", None),
    ("code IT0 before far coldline spaced32", "fair_code_prefetchit0_before_far_coldline_spaced32", None),
    ("code IT0 between cold calls", "fair_code_prefetchit0_between_cold_calls", None),
    ("code IT0 before branch far", "fair_code_prefetchit0_before_branch_misp_far", None),
    ("code IT0 before indirect far", "fair_code_prefetchit0_before_indirect_misp_far", None),
    ("code IT0 repeat16 cpuid", "fair_code_prefetchit0_repeat16_cpuid_after", None),
    ("code IT0 repeat64 cpuid", "fair_code_prefetchit0_repeat64_cpuid_after", None),
    ("code IT1 repeat16 cpuid", "fair_code_prefetchit1_repeat16_cpuid_after", None),
    ("code IT0 repeat16 far", "fair_code_prefetchit0_repeat16_before_far_big", None),
    ("code IT0 repeat64 far", "fair_code_prefetchit0_repeat64_before_far_big", None),
    ("code IT0 wrongpath branch", "fair_code_prefetchit0_wrongpath_slow_branch", None),
    ("code IT0 wrongpath cpuid", "fair_code_prefetchit0_wrongpath_cpuid_after", None),
    ("code IT0 wrongpath far", "fair_code_prefetchit0_wrongpath_far_after", None),
    ("code IT0 path wrongpath", "fair_code_prefetchit0_path_wrongpath_slow_branch", None),
    ("code IT1 wrongpath branch", "fair_code_prefetchit1_wrongpath_slow_branch", None),
    ("code IT0 wrongpath data branch", "fair_code_prefetchit0_wrongpath_data_slow_branch", None),
    ("code IT0 wrongpath data cpuid", "fair_code_prefetchit0_wrongpath_data_cpuid_after", None),
    ("code IT0 wrongpath data far", "fair_code_prefetchit0_wrongpath_data_far_after", None),
    ("code IT0 path wrongpath data", "fair_code_prefetchit0_path_wrongpath_data_slow_branch", None),
    ("code IT0 spaced8 cpuid", "fair_code_prefetchit0_spaced8_cpuid_after", None),
    ("code IT0 spaced32 cpuid", "fair_code_prefetchit0_spaced32_cpuid_after", None),
    ("code IT0 spaced128 cpuid", "fair_code_prefetchit0_spaced128_cpuid_after", None),
    ("code IT1 spaced32 cpuid", "fair_code_prefetchit1_spaced32_cpuid_after", None),
    ("code IT0 arith gap16", "fair_code_prefetchit0_arith_gap16", None),
    ("code IT0 arith gap64", "fair_code_prefetchit0_arith_gap64", None),
    ("code IT0 control gap16", "fair_code_prefetchit0_control_gap16", None),
    ("code IT0 control gap64", "fair_code_prefetchit0_control_gap64", None),
    ("code IT1 arith gap64", "fair_code_prefetchit1_arith_gap64", None),
    ("code IT0 twophase", "fair_code_prefetchit0_twophase", None),
    ("code IT0 twophase longgap", "fair_code_prefetchit0_twophase_longgap", None),
    ("code IT1 twophase", "fair_code_prefetchit1_twophase", None),
    ("code IT0 unrolled spaced32 cpuid", "fair_code_prefetchit0_unrolled_spaced32_cpuid_after", None),
    ("code IT0 unrolled spaced128 cpuid", "fair_code_prefetchit0_unrolled_spaced128_cpuid_after", None),
    ("code IT1 unrolled spaced32 cpuid", "fair_code_prefetchit1_unrolled_spaced32_cpuid_after", None),
    ("code shape far spaced128", "fair_code_shape_far_spaced128", None),
    ("code IT0 far spaced32", "fair_code_prefetchit0_far_spaced32", None),
    ("code IT0 far spaced128", "fair_code_prefetchit0_far_spaced128", None),
    ("code IT1 far spaced32", "fair_code_prefetchit1_far_spaced32", None),
    ("code IT0 spaced32 far", "fair_code_prefetchit0_spaced32_before_far_big", None),
    ("code IT0 dtlb spaced32 cpuid", "fair_code_prefetchit0_dtlb_prime_spaced32_cpuid_after", None),
    ("code IT1 dtlb spaced32 cpuid", "fair_code_prefetchit1_dtlb_prime_spaced32_cpuid_after", None),
    ("code IT0 dtlb spaced32 far", "fair_code_prefetchit0_dtlb_prime_spaced32_before_far_big", None),
    ("code IT0 wrongpath deep repeat4", "fair_code_prefetchit0_wrongpath_deep_repeat4_cpuid_after", None),
    ("code IT0 wrongpath per page", "fair_code_prefetchit0_wrongpath_per_page_cpuid_after", None),
    ("code IT0 wrongpath chase256", "fair_code_prefetchit0_wrongpath_chase256", None),
    ("code IT0 wrongpath chase1024", "fair_code_prefetchit0_wrongpath_chase1024", None),
    ("code IT0 wrongpath chase256 cpuid", "fair_code_prefetchit0_wrongpath_chase256_cpuid_after", None),
    ("code IT1 wrongpath chase256 cpuid", "fair_code_prefetchit1_wrongpath_chase256_cpuid_after", None),
    ("code IT0 inline chase burst", "fair_code_prefetchit0_inline_chase4096_burst4", None),
    ("code IT0 inline long chase burst", "fair_code_prefetchit0_inline_chase16384_burst4", None),
    ("code IT0 inline chase fixed burst", "fair_code_prefetchit0_inline_chase4096_fixed_burst4", None),
    ("code IT0 inline long chase fixed burst", "fair_code_prefetchit0_inline_chase16384_fixed_burst4", None),
    ("code IT0 trained inline chase burst", "fair_code_prefetchit0_trained_inline_chase4096_burst4", None),
    ("code IT0 trained inline chase fixed burst", "fair_code_prefetchit0_trained_inline_chase4096_fixed_burst4", None),
    ("code IT0 slow taken branch", "fair_code_prefetchit0_slow_taken_branch", None),
    ("code IT0 slow taken cpuid", "fair_code_prefetchit0_slow_taken_cpuid_after", None),
    ("code IT0 path slow taken", "fair_code_prefetchit0_path_slow_taken_branch", None),
    ("code IT0 slow taken per page", "fair_code_prefetchit0_slow_taken_per_page", None),
    ("code IT0 trained wrongpath flush", "fair_code_prefetchit0_trained_wrongpath_flush", None),
    ("code IT1 trained wrongpath flush", "fair_code_prefetchit1_trained_wrongpath_flush", None),
    ("code IT0 data trained wrongpath flush", "fair_code_prefetchit0_data_trained_wrongpath_flush", None),
    ("code IT1 data trained wrongpath flush", "fair_code_prefetchit1_data_trained_wrongpath_flush", None),
    ("code IT0 deep trained wrongpath flush", "fair_code_prefetchit0_deep_trained_wrongpath_flush", None),
    ("code IT0 deep spaced trained wrongpath flush", "fair_code_prefetchit0_deep_spaced32_trained_wrongpath_flush", None),
    ("code IT1 deep spaced trained wrongpath flush", "fair_code_prefetchit1_deep_spaced32_trained_wrongpath_flush", None),
    ("code IT0 ptr wrongpath dummytrain", "fair_code_prefetchit0_ptr_wrongpath_dummytrain_spaced32", None),
    ("code IT0 ptr wrongpath per page", "fair_code_prefetchit0_ptr_wrongpath_dummytrain_per_page", None),
    ("code tlb offset prime only", "fair_code_tlb_offset_prime_only", None),
    ("code IT0 tlb offset prime", "fair_code_prefetchit0_tlb_offset_prime_lines", None),
    ("code IT0 tlb offset prime spaced", "fair_code_prefetchit0_tlb_offset_prime_spaced32", None),
    ("code IT1 tlb offset prime", "fair_code_prefetchit1_tlb_offset_prime_lines", None),
    ("code IT1 tlb offset prime spaced", "fair_code_prefetchit1_tlb_offset_prime_spaced32", None),
    ("code IT0 burst4", "fair_code_prefetchit0_burst4_spaced32", None),
    ("code IT0 burst8", "fair_code_prefetchit0_burst8_spaced32", None),
    ("code IT0 burst4 longgap", "fair_code_prefetchit0_burst4_spaced128", None),
    ("code IT1 burst4", "fair_code_prefetchit1_burst4_spaced32", None),
    ("code IT0 fixed path", "fair_code_prefetchit0_fixed_path", None),
    ("code IT0 fixed path spaced", "fair_code_prefetchit0_fixed_path_spaced32", None),
    ("code IT0 fixed path burst", "fair_code_prefetchit0_fixed_path_burst4", None),
    ("code IT0 fixed path far", "fair_code_prefetchit0_fixed_path_before_far_big", None),
    ("code IT0 fixed path tlb far", "fair_code_prefetchit0_fixed_path_tlb_offset_far_burst4", None),
    ("code IT0 p2 far tlb2", "fair_code_prefetchit0_p2_far_tlb2", None),
    ("code IT0 p4 far tlb2", "fair_code_prefetchit0_p4_far_tlb2", None),
    ("code IT0 p2 far tlb4", "fair_code_prefetchit0_p2_far_tlb4", None),
    ("code IT0 fixed p2 far tlb2", "fair_code_prefetchit0_fixed_p2_far_tlb2", None),
    ("code IT0 fixed p4 far tlb4", "fair_code_prefetchit0_fixed_p4_far_tlb4", None),
    ("code IT0 p far p far", "fair_code_prefetchit0_p_far_p_far", None),
    ("code IT0 far p2 far", "fair_code_prefetchit0_far_p2_far", None),
    ("code IT0 far2 p2", "fair_code_prefetchit0_far2_p2", None),
    ("code IT0 p2 far tlb2 cpuid", "fair_code_prefetchit0_p2_far_tlb2_cpuid_after", None),
    ("code IT1 p2 far tlb2", "fair_code_prefetchit1_p2_far_tlb2", None),
    ("code IT0 p2 strong far tlb2", "fair_code_prefetchit0_p2_strong_far_tlb2", None),
    ("code IT0 p2 strong far tlb4", "fair_code_prefetchit0_p2_strong_far_tlb4", None),
    ("code IT0 far p2 strong far", "fair_code_prefetchit0_far_p2_strong_far", None),
    ("code IT0 p2 strong far repeat", "fair_code_prefetchit0_p2_strong_far_repeat", None),
    ("code IT0 fixed p2 strong far", "fair_code_prefetchit0_fixed_p2_strong_far_tlb4", None),
    ("code IT1 p2 strong far", "fair_code_prefetchit1_p2_strong_far_tlb4", None),
    ("code IT0 cpuid p2 cpuid far", "fair_code_prefetchit0_cpuid_p2_cpuid_far", None),
    ("code IT0 cpuid p2 far cpuid", "fair_code_prefetchit0_cpuid_p2_far_cpuid", None),
    ("code IT0 far cpuid p2 far", "fair_code_prefetchit0_far_cpuid_p2_far", None),
    ("code IT0 cpuid far p2 far cpuid", "fair_code_prefetchit0_cpuid_far_p2_far_cpuid", None),
    ("code IT1 cpuid p2 cpuid far", "fair_code_prefetchit1_cpuid_p2_cpuid_far", None),
    ("code IT1 cpuid p2 far cpuid", "fair_code_prefetchit1_cpuid_p2_far_cpuid", None),
    ("code IT1 far cpuid p2 far", "fair_code_prefetchit1_far_cpuid_p2_far", None),
    ("code IT1 cpuid far p2 far cpuid", "fair_code_prefetchit1_cpuid_far_p2_far_cpuid", None),
    ("code IT0 far AB p2 far CD", "fair_code_prefetchit0_far_ab_p2_far_cd", None),
    ("code IT0 far AB p4 far CD", "fair_code_prefetchit0_far_ab_p4_far_cd", None),
    ("code IT0 fixed far AB p2 far CD", "fair_code_prefetchit0_fixed_far_ab_p2_far_cd", None),
    ("code IT0 strong farfunc burst", "fair_code_prefetchit0_strong_farfunc_burst4_far_tlb2", None),
    ("code IT0 strong farfunc path", "fair_code_prefetchit0_strong_farfunc_path_far_tlb2", None),
    ("code IT1 strong farfunc burst", "fair_code_prefetchit1_strong_farfunc_burst4_far_tlb2", None),
    ("code IT0 far burst4", "fair_code_prefetchit0_far_burst4_spaced32", None),
    ("code IT0 far burst8", "fair_code_prefetchit0_far_burst8_spaced32", None),
    ("code IT0 far burst4 longgap", "fair_code_prefetchit0_far_burst4_spaced128", None),
    ("code IT1 far burst4", "fair_code_prefetchit1_far_burst4_spaced32", None),
    ("code IT0 tlb far burst4", "fair_code_prefetchit0_tlb_offset_far_burst4_spaced32", None),
    ("code IT0 tlb far burst8", "fair_code_prefetchit0_tlb_offset_far_burst8_spaced32", None),
    ("code IT1 tlb far burst4", "fair_code_prefetchit1_tlb_offset_far_burst4_spaced32", None),
    ("code IT0 call pre", "fair_code_prefetchit0_call_window_pre10", None),
    ("code IT0 call post", "fair_code_prefetchit0_call_window_post10", None),
    ("code IT0 call burst pre", "fair_code_prefetchit0_call_window_burst4_pre10", None),
    ("code IT0 call burst post", "fair_code_prefetchit0_call_window_burst4_post10", None),
    ("code IT1 call burst pre", "fair_code_prefetchit1_call_window_burst4_pre10", None),
    ("code IT0 tlb call burst pre", "fair_code_prefetchit0_tlb_offset_call_window_burst4_pre10", None),
    ("code IT0 tlb call burst post", "fair_code_prefetchit0_tlb_offset_call_window_burst4_post10", None),
    ("code IT1 tlb call burst pre", "fair_code_prefetchit1_tlb_offset_call_window_burst4_pre10", None),
    ("code IT0 nested window", "fair_code_prefetchit0_nested_window_p2_far", None),
    ("code IT0 nested per target", "fair_code_prefetchit0_nested_window_per_target", None),
    ("code IT0 nested far window", "fair_code_prefetchit0_nested_window_far_p2_far", None),
    ("code IT0 branch actual", "fair_code_prefetchit0_branch_actual_p2_far", None),
    ("code IT0 branch far actual", "fair_code_prefetchit0_branch_actual_far_p2_far", None),
    ("code IT0 branch nested actual", "fair_code_prefetchit0_branch_actual_nested_p2_far", None),
    ("code IT0 branch repeat", "fair_code_prefetchit0_branch_actual_repeat", None),
    ("code IT0 far branch", "fair_code_prefetchit0_far_branch_actual_p2_far", None),
    ("code IT0 far branch repeat", "fair_code_prefetchit0_far_branch_actual_repeat", None),
    ("code IT0 branch farpath", "fair_code_prefetchit0_branch_farpath_p2_far", None),
    ("code IT0 branch farpath far", "fair_code_prefetchit0_branch_farpath_far_p2_far", None),
    ("code IT0 branch farpath repeat", "fair_code_prefetchit0_branch_farpath_repeat", None),
    ("code IT0 far branch farpath", "fair_code_prefetchit0_far_branch_farpath_p2_far", None),
    ("code page prime only", "fair_code_page_prime_only", None),
    ("code page shape lines", "fair_code_page_shape_lines", None),
    ("code page shape spaced32", "fair_code_page_shape_spaced32_lines", None),
    ("code page IT0 lines", "fair_code_page_prefetchit0_lines", None),
    ("code page IT0 spaced32", "fair_code_page_prefetchit0_spaced32_lines", None),
    ("code page IT0 spaced128", "fair_code_page_prefetchit0_spaced128_lines", None),
    ("code page IT0 repeat4", "fair_code_page_prefetchit0_repeat4_lines", None),
    ("code page IT1 lines", "fair_code_page_prefetchit1_lines", None),
    ("code page IT1 spaced32", "fair_code_page_prefetchit1_spaced32_lines", None),
    ("code adjacent shape", "fair_code_adjacent_shape_spaced32_lines", None),
    ("code adjacent IT0", "fair_code_adjacent_prefetchit0_spaced32_lines", None),
    ("code adjacent IT0 longgap", "fair_code_adjacent_prefetchit0_spaced128_lines", None),
    ("code adjacent IT1", "fair_code_adjacent_prefetchit1_spaced32_lines", None),
    ("code tlb spaced32 shape", "fair_code_tlb_prime_spaced32_shape", None),
    ("code IT0 code-tlb prime", "fair_code_prefetchit0_code_tlb_prime_lines", None),
    ("code IT0 code-tlb spaced8", "fair_code_prefetchit0_code_tlb_prime_spaced8", None),
    ("code IT0 code-tlb spaced32", "fair_code_prefetchit0_code_tlb_prime_spaced32", None),
    ("code IT0 code-tlb spaced64", "fair_code_prefetchit0_code_tlb_prime_spaced64", None),
    ("code IT0 code-tlb spaced128", "fair_code_prefetchit0_code_tlb_prime_spaced128", None),
    ("code IT1 code-tlb prime", "fair_code_prefetchit1_code_tlb_prime_lines", None),
    ("code IT1 code-tlb spaced32", "fair_code_prefetchit1_code_tlb_prime_spaced32", None),
]

CASE_SETS = {
    "branchwin": BRANCHWIN_CASES,
    "cpuidfar": CPUID_FAR_CASES,
    "core": CORE_ROUND_CASES,
    "fair": FAIR_CASES,
    "it0search": IT0_SEARCH_CASES,
    "nohelper": NOHELPER_SEARCH_CASES,
}

PLOT_EXCLUDED_STRATEGIES = {
    "fair_code_page_shape_lines",
    "fair_code_page_shape_spaced32_lines",
    "fair_code_tlb_prime_spaced32_shape",
}


def percentile(values, pct):
    if not values:
        return 0
    vals = sorted(values)
    idx = ((len(vals) - 1) * pct) // 100
    return vals[idx]


def parse_one_row(stdout):
    lines = [line for line in stdout.splitlines() if line.strip()]
    if len(lines) < 2:
        raise RuntimeError(f"prefetch_test did not print a CSV row: {stdout!r}")
    return next(csv.DictReader(lines[-2:]))


def run_dummy(dummy_bin, cpu, dummy_kib, dummy_passes):
    subprocess.run(
        [str(dummy_bin), str(dummy_kib), str(cpu), str(dummy_passes)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )


def run_one(prefetch_bin, cpu, strategy, delay, cold_mode):
    proc = subprocess.run(
        [
            str(prefetch_bin),
            "1",
            "0",
            str(cpu),
            f"={delay}",
            f"={strategy}",
            cold_mode,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    return parse_one_row(proc.stdout)


def summarize(rows):
    by_case_delay = {}
    for row in rows:
        key = (row["case"], row["strategy"], row["delay"])
        by_case_delay.setdefault(key, []).append(row)

    summary = []
    for (case, strategy, delay), group in sorted(by_case_delay.items()):
        cycles = [int(r["p50"]) for r in group]
        l2 = [int(r["l2_code_miss_p50"]) for r in group]
        l3 = [int(r["llc_miss_p50"]) for r in group]
        itlb = [int(r["itlb_miss_p50"]) for r in group]
        stlb = [int(r["stlb_miss_p50"]) for r in group]
        prep_itlb = [int(r.get("prep_itlb_walk_p50", 0) or 0) for r in group]
        prep_dtlb = [int(r.get("prep_dtlb_walk_p50", 0) or 0) for r in group]
        prep_branch = [int(r.get("prep_branch_miss_p50", 0) or 0) for r in group]
        summary.append({
            "case": case,
            "strategy": strategy,
            "delay": delay,
            "samples": len(group),
            "p50_cycles": percentile(cycles, 50),
            "p75_cycles": percentile(cycles, 75),
            "p95_cycles": percentile(cycles, 95),
            "itlb_miss_p50": percentile(itlb, 50),
            "stlb_miss_p50": percentile(stlb, 50),
            "l2_code_miss_p50": percentile(l2, 50),
            "llc_miss_p50": percentile(l3, 50),
            "prep_itlb_walk_p50": percentile(prep_itlb, 50),
            "prep_dtlb_walk_p50": percentile(prep_dtlb, 50),
            "prep_branch_miss_p50": percentile(prep_branch, 50),
        })
    return summary


def choose_best(cases, summary):
    best = []
    for case, strategy, _ in cases:
        candidates = [r for r in summary if r["strategy"] == strategy]
        best.append(min(candidates, key=lambda r: (r["p50_cycles"], r["p95_cycles"])))
    return best


def write_csv(path, rows, fields):
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def delay_sort_key(delay):
    if delay == "none":
        return 0
    digits = "".join(ch for ch in delay if ch.isdigit())
    return int(digits) if digits else 0


def filter_cases(cases, filter_text):
    if not filter_text or filter_text == "all":
        return cases
    tokens = [item.strip() for item in filter_text.split(",") if item.strip()]
    filtered = []
    for case, strategy, delays in cases:
        haystack = f"{case} {strategy}"
        if any(
            (token.startswith("=") and token[1:] in (case, strategy)) or
            (not token.startswith("=") and token in haystack)
            for token in tokens
        ):
            filtered.append((case, strategy, delays))
    if not filtered:
        raise ValueError(f"case filter matched nothing: {filter_text}")
    return filtered


def build_jobs(cases, delays, all_cases_all_delays):
    jobs = []
    for case, strategy, case_delays in cases:
        active_delays = delays if all_cases_all_delays else (case_delays or delays)
        for delay in active_delays:
            jobs.append((case, strategy, delay))
    return jobs


def ordered_round_jobs(cases, delays, all_cases_all_delays):
    jobs = []
    for delay in delays:
        for case, strategy, case_delays in cases:
            if all_cases_all_delays or case_delays is None or delay in case_delays:
                jobs.append((case, strategy, delay))
    return jobs


def display_label(row):
    strategy = row["strategy"]
    case = row["case"]
    labels = {
        "baseline": "Baseline",
        "fair_advance_execution": "Actual",
        "fair_data_prefetcht0": "Data T0",
        "fair_data_prefetcht0_lines": "Data T0",
        "fair_data_prefetcht1": "Data T1",
        "fair_data_prefetcht1_lines": "Data T1",
        "fair_code_page_shape_spaced32_lines": "Control",
        "fair_code_page_shape_lines": "Control",
        "fair_code_tlb_prime_spaced32_shape": "Control",
        "fair_code_page_prefetchit0_lines": "IT0",
        "fair_code_page_prefetchit0_spaced32_lines": "IT0",
        "fair_code_page_prefetchit0_spaced128_lines": "IT0",
        "fair_code_page_prefetchit0_repeat4_lines": "IT0",
        "fair_code_page_prefetchit1_lines": "IT1",
        "fair_code_page_prefetchit1_spaced32_lines": "IT1",
        "fair_code_prefetchit0_lines": "IT0",
        "fair_code_prefetchit1_lines": "IT1",
        "fair_code_prefetchit0_p2_far_tlb2": "IT0",
    }
    if strategy in labels:
        return labels[strategy]
    if "prefetchit0" in strategy:
        return "IT0"
    if "prefetchit1" in strategy:
        return "IT1"

    label = case
    label = label.replace("baseline (no prefetch)", "Baseline")
    label = label.replace("advance execution", "Actual")
    label = label.replace("data ", "Data ")
    label = label.replace("code page ", "")
    label = label.replace("code ", "")
    label = label.replace("PREFETCH", "")
    label = re.sub(r"\bspaced\d+\b", "", label)
    label = re.sub(r"\bpause\d+\b", "", label)
    label = re.sub(r"\bmultiline\b|\blines\b|\brepeat\d+\b", "", label)
    label = re.sub(r"\s+", " ", label).strip()
    return label.title() if label else case


def prefetchi_kind(strategy):
    if "prefetchit0" in strategy:
        return "IT0"
    if "prefetchit1" in strategy:
        return "IT1"
    return None


def compact_prefetchi_rows(rows):
    compacted = []
    best_by_kind = {}
    for row in rows:
        kind = prefetchi_kind(row["strategy"])
        if not kind:
            compacted.append(row)
            continue
        current = best_by_kind.get(kind)
        if current is None or (int(row["p50_cycles"]), int(row["p95_cycles"])) < (
            int(current["p50_cycles"]),
            int(current["p95_cycles"]),
        ):
            best_by_kind[kind] = row

    inserted = set()
    output = []
    for row in compacted:
        output.append(row)
        if row["strategy"].startswith("fair_data_prefetch"):
            for kind in ("IT0", "IT1"):
                if kind in best_by_kind and kind not in inserted:
                    output.append(best_by_kind[kind])
                    inserted.add(kind)
    for kind in ("IT0", "IT1"):
        if kind in best_by_kind and kind not in inserted:
            output.append(best_by_kind[kind])
    return output


def plot_results(result_dir, best_rows, summary_rows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    best_rows = [r for r in best_rows if r["strategy"] not in PLOT_EXCLUDED_STRATEGIES]
    summary_rows = [r for r in summary_rows if r["strategy"] not in PLOT_EXCLUDED_STRATEGIES]
    best_rows = compact_prefetchi_rows(best_rows)
    plotted_strategies = {r["strategy"] for r in best_rows}
    summary_rows = [r for r in summary_rows if r["strategy"] in plotted_strategies]

    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 24,
        "axes.titlesize": 28,
        "axes.labelsize": 26,
        "xtick.labelsize": 24,
        "ytick.labelsize": 24,
        "legend.fontsize": 22,
    })

    labels = [display_label(r) for r in best_rows]
    x = np.arange(len(best_rows))
    width = 0.38

    p50 = [int(r["p50_cycles"]) for r in best_rows]
    p95 = [int(r["p95_cycles"]) for r in best_rows]
    fig, ax = plt.subplots(figsize=(11, 5.6))
    ax.bar(x - width / 2, p50, width, label="p50 cycles", color="#3f6fb5")
    ax.bar(x + width / 2, p95, width, label="p95 cycles", color="#d28a2e")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=0, ha="center")
    ax.set_ylabel("cycles")
    ax.set_title("Process-level cycle comparison")
    ax.set_ylim(0, max(p95) * 1.18)
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False)
    for i, v in enumerate(p50):
        ax.text(i - width / 2, v + 20, str(v), ha="center", va="bottom", fontsize=22)
    for i, v in enumerate(p95):
        ax.text(i + width / 2, v + 20, str(v), ha="center", va="bottom", fontsize=22)
    fig.tight_layout()
    fig.savefig(result_dir / "latest_process_cycle_comparison.png", dpi=180)
    plt.close(fig)

    l2 = [int(r["l2_code_miss_p50"]) for r in best_rows]
    l3 = [int(r["llc_miss_p50"]) for r in best_rows]
    itlb = [int(r["itlb_miss_p50"]) for r in best_rows]
    stlb = [int(r["stlb_miss_p50"]) for r in best_rows]
    fig, ax = plt.subplots(figsize=(11, 5.6))
    sub_width = 0.2
    ax.bar(x - 1.5 * sub_width, l2, sub_width, label="L2 code miss p50", color="#4a75b8")
    ax.bar(x - 0.5 * sub_width, l3, sub_width, label="L3 miss p50", color="#d28a2e")
    ax.bar(x + 0.5 * sub_width, itlb, sub_width, label="iTLB miss p50", color="#a05ca6")
    ax.bar(x + 1.5 * sub_width, stlb, sub_width, label="sTLB miss p50", color="#4f9b79")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=0, ha="center")
    ax.set_ylabel("miss count")
    ax.set_title("Process-level cache and frontend TLB miss comparison")
    ax.set_ylim(0, max(12, max(l2 + l3 + itlb + stlb) * 1.18))
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False)
    for i, v in enumerate(l2):
        ax.text(i - 1.5 * sub_width, v + 0.2, str(v), ha="center", va="bottom", fontsize=22)
    for i, v in enumerate(l3):
        ax.text(i - 0.5 * sub_width, v + 0.2, str(v), ha="center", va="bottom", fontsize=22)
    for i, v in enumerate(itlb):
        ax.text(i + 0.5 * sub_width, v + 0.2, str(v), ha="center", va="bottom", fontsize=22)
    for i, v in enumerate(stlb):
        ax.text(i + 1.5 * sub_width, v + 0.2, str(v), ha="center", va="bottom", fontsize=22)
    fig.tight_layout()
    fig.savefig(result_dir / "latest_process_cache_miss_comparison.png", dpi=180)
    plt.close(fig)

    plotted = [r for r in summary_rows if r["delay"] != "none"]
    by_case = {}
    for row in plotted:
        by_case.setdefault(row["case"], []).append(row)
    fig, ax = plt.subplots(figsize=(11, 5.8))
    for case, rows in by_case.items():
        rows = sorted(rows, key=lambda r: delay_sort_key(r["delay"]))
        ax.plot(
            [delay_sort_key(r["delay"]) for r in rows],
            [int(r["p50_cycles"]) for r in rows],
            marker="o",
            linewidth=3.6,
            markersize=7,
            label=display_label(rows[0]),
        )
    ax.set_xlabel("delay length")
    ax.set_ylabel("p50 cycles")
    ax.set_title("Delay sweep latency")
    ax.grid(alpha=0.25)
    ax.legend(frameon=False, ncol=2)
    fig.tight_layout()
    fig.savefig(result_dir / "latest_process_delay_latency.png", dpi=180)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    here = Path(__file__).resolve().parent
    parser.add_argument("--prefetch-bin", type=Path, default=here / "prefetch_test")
    parser.add_argument("--dummy-bin", type=Path, default=here / "icache_flush_dummy")
    parser.add_argument("--result-dir", type=Path, default=here.parent / "result")
    parser.add_argument("--cpu", type=int, default=10)
    parser.add_argument("--reps", type=int, default=30)
    parser.add_argument("--dummy-kib", type=int, default=8192)
    parser.add_argument("--dummy-passes", type=int, default=1)
    parser.add_argument(
        "--delays",
        default="none,pause8,pause16,pause32,pause48,pause64,pause96,pause128,pause160,pause192,pause224,pause256,pause384,pause512",
    )
    parser.add_argument("--seed", type=int, default=12345)
    parser.add_argument("--clear-result", action="store_true")
    parser.add_argument("--case-set", choices=sorted(CASE_SETS), default="fair")
    parser.add_argument("--case-filter", default="all")
    parser.add_argument("--cold-mode", default="perf_once")
    parser.add_argument("--schedule", choices=("round", "shuffle"), default="round")
    parser.add_argument("--all-cases-all-delays", action="store_true")
    args = parser.parse_args()

    args.result_dir.mkdir(parents=True, exist_ok=True)
    if args.clear_result:
        for path in args.result_dir.iterdir():
            if path.is_file():
                path.unlink()

    delays = [item.strip() for item in args.delays.split(",") if item.strip()]
    cases = filter_cases(CASE_SETS[args.case_set], args.case_filter)

    rng = random.Random(args.seed)
    jobs = build_jobs(cases, delays, args.all_cases_all_delays)
    round_jobs = ordered_round_jobs(cases, delays, args.all_cases_all_delays)

    raw_rows = []
    for rep in range(args.reps):
        active_jobs = jobs[:]
        if args.schedule == "shuffle":
            rng.shuffle(active_jobs)
        else:
            active_jobs = round_jobs

        for slot, (case, strategy, delay) in enumerate(active_jobs):
            run_dummy(args.dummy_bin, args.cpu, args.dummy_kib, args.dummy_passes)
            row = run_one(
                args.prefetch_bin,
                args.cpu,
                strategy,
                delay,
                args.cold_mode,
            )
            row = dict(row)
            row["case"] = case
            row["rep"] = rep
            row["slot"] = slot
            raw_rows.append(row)
        if args.schedule == "round" and active_jobs:
            run_dummy(args.dummy_bin, args.cpu, args.dummy_kib, args.dummy_passes)

    raw_fields = ["case", "rep", "slot"] + [k for k in raw_rows[0].keys() if k not in ("case", "rep", "slot")]
    write_csv(args.result_dir / "latest_process_raw.csv", raw_rows, raw_fields)

    summary = summarize(raw_rows)
    summary_fields = [
        "case", "strategy", "delay", "samples", "p50_cycles", "p75_cycles",
        "p95_cycles", "itlb_miss_p50", "stlb_miss_p50",
        "l2_code_miss_p50", "llc_miss_p50",
        "prep_itlb_walk_p50", "prep_dtlb_walk_p50", "prep_branch_miss_p50",
    ]
    write_csv(args.result_dir / "latest_process_summary.csv", summary, summary_fields)

    best = choose_best(cases, summary)
    write_csv(args.result_dir / "latest_process_best.csv", best, summary_fields)
    write_csv(args.result_dir / "latest_process_plot_best.csv", compact_prefetchi_rows(best), summary_fields)
    plot_results(args.result_dir, best, summary)

    with (args.result_dir / "latest_process_run.log").open("w") as f:
        f.write(f"cpu={args.cpu}\n")
        f.write(f"reps={args.reps}\n")
        f.write(f"dummy_kib={args.dummy_kib}\n")
        f.write(f"dummy_passes={args.dummy_passes}\n")
        f.write(f"delays={','.join(delays)}\n")
        f.write(f"case_set={args.case_set}\n")
        f.write(f"case_filter={args.case_filter}\n")
        f.write(f"cold_mode={args.cold_mode}\n")
        f.write(f"schedule={args.schedule}\n")
        f.write(f"all_cases_all_delays={int(args.all_cases_all_delays)}\n")
        if args.schedule == "round":
            f.write("mode=flush dummy -> case0 -> flush dummy -> case1 -> ... -> final flush dummy per rep\n")
        else:
            f.write("mode=shuffled jobs, with flush dummy before each sample\n")

    for row in best:
        print(row)


if __name__ == "__main__":
    main()
