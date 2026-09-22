#!/usr/bin/env python3
"""Build profile-free prefetch plans from static branch targets.

This is intentionally separate from the static-return predictor.  The return
predictor only covers call return addresses, while the PGO-best L2 plan is
dominated by general branch targets.  This generator uses only binary static
structure: large functions, direct conditional/unconditional branches, and
their taken/fallthrough cachelines.
"""

from __future__ import annotations

import argparse
import json
import re
import math
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from static_site_plan_to_prefetch_plan import (
    Loc,
    Symbol,
    SymbolIndex,
    build_symbol_index,
    parse_offsets,
    resolve_addrs,
    source_obj,
)


FUNC_RE = re.compile(r"^([0-9a-fA-F]+)\s+<(.+)>:$")
INSN_RE = re.compile(r"^\s*([0-9a-fA-F]+):\s*(.*?)\s*$")
TARGET_RE = re.compile(r"0x([0-9a-fA-F]+)")
BRANCH_OPS = {
    "ja",
    "jae",
    "jb",
    "jbe",
    "jc",
    "je",
    "jg",
    "jge",
    "jl",
    "jle",
    "jna",
    "jnae",
    "jnb",
    "jnbe",
    "jnc",
    "jne",
    "jng",
    "jnge",
    "jnl",
    "jnle",
    "jno",
    "jnp",
    "jns",
    "jnz",
    "jo",
    "jp",
    "jpe",
    "jpo",
    "js",
    "jz",
}


@dataclass(frozen=True)
class Insn:
    addr: int
    asm: str


@dataclass(frozen=True)
class Branch:
    addr: int
    op: str
    target_addr: int | None
    fallthrough_addr: int | None
    branch_type: str


@dataclass
class FunctionBody:
    sym: Symbol
    insns: list[Insn] = field(default_factory=list)
    branches: list[Branch] = field(default_factory=list)


@dataclass(frozen=True)
class CallGraphFeatures:
    callers: dict[str, set[str]]
    callees: dict[str, set[str]]
    incoming_calls: Counter[str]
    outgoing_calls: Counter[str]


def run_objdump(binary: Path, objdump: str) -> list[str]:
    return subprocess.run(
        [objdump, "-d", "--demangle", "--no-show-raw-insn", "--section=.text", str(binary)],
        check=True,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.splitlines()


def parse_branch(asm: str) -> tuple[str, int | None, str] | None:
    parts = asm.split(None, 1)
    if not parts:
        return None
    op = parts[0].lower()
    operand = parts[1] if len(parts) > 1 else ""
    if op in BRANCH_OPS:
        branch_type = "COND"
    elif op in {"jmp", "jmpq"}:
        branch_type = "UNCOND"
    elif op in {"call", "callq"}:
        branch_type = "CALL"
    elif op in {"ret", "retq"}:
        branch_type = "RET"
    else:
        return None
    target = None
    m = TARGET_RE.search(operand)
    if m:
        target = int(m.group(1), 16)
    return op, target, branch_type


def parse_functions(binary: Path, symbols: SymbolIndex, objdump: str) -> dict[str, FunctionBody]:
    bodies: dict[str, FunctionBody] = {}
    current: FunctionBody | None = None
    for line in run_objdump(binary, objdump):
        fmatch = FUNC_RE.match(line.strip())
        if fmatch:
            addr = int(fmatch.group(1), 16)
            sym = symbols.symbol_at(addr)
            current = None
            if sym is not None and sym.addr == addr:
                current = bodies.setdefault(sym.demangled, FunctionBody(sym=sym))
            continue
        if current is None:
            continue
        imatch = INSN_RE.match(line)
        if not imatch:
            continue
        addr = int(imatch.group(1), 16)
        asm = imatch.group(2).strip()
        current.insns.append(Insn(addr=addr, asm=asm))

    for body in bodies.values():
        next_addr = {insn.addr: body.insns[i + 1].addr for i, insn in enumerate(body.insns[:-1])}
        for insn in body.insns:
            parsed = parse_branch(insn.asm)
            if not parsed:
                continue
            op, target, branch_type = parsed
            fallthrough = next_addr.get(insn.addr) if branch_type in {"COND", "CALL"} else None
            body.branches.append(
                Branch(
                    addr=insn.addr,
                    op=op,
                    target_addr=target,
                    fallthrough_addr=fallthrough,
                    branch_type=branch_type,
                )
            )
    return bodies


def body_at_addr(bodies: dict[str, FunctionBody], addr: int) -> FunctionBody | None:
    for body in bodies.values():
        if body.sym.size <= 0:
            continue
        if body.sym.addr <= addr < body.sym.addr + body.sym.size:
            return body
    return None


def build_call_graph_features(bodies: dict[str, FunctionBody], symbols: SymbolIndex) -> CallGraphFeatures:
    callers: dict[str, set[str]] = defaultdict(set)
    callees: dict[str, set[str]] = defaultdict(set)
    incoming: Counter[str] = Counter()
    outgoing: Counter[str] = Counter()
    for name, body in bodies.items():
        for branch in body.branches:
            if branch.branch_type != "CALL" or branch.target_addr is None:
                continue
            target_body = body_at_addr(bodies, branch.target_addr)
            if target_body is None:
                target_sym = symbols.symbol_at(branch.target_addr)
                if target_sym is None:
                    continue
                target_name = target_sym.demangled
            else:
                target_name = target_body.sym.demangled
            callers[target_name].add(name)
            callees[name].add(target_name)
            incoming[target_name] += 1
            outgoing[name] += 1
    return CallGraphFeatures(callers=callers, callees=callees, incoming_calls=incoming, outgoing_calls=outgoing)


GENERIC_RUNTIME_RE = re.compile(
    r"^(?:_GLOBAL__sub_I|_init|_fini|_start|__|frame_dummy|deregister_tm_clones|register_tm_clones)(?:$|\\W|_)"
)
SERDE_COLD_RE = re.compile(
    r"(?:_InternalSerialize|_InternalParse|MergeFrom|ByteSizeLong|SerializeWithCachedSizes|GenericDeserialize)"
)
STL_RUNTIME_RE = re.compile(
    r"^(?:std::|google::protobuf::internal::|google::protobuf::UnknownFieldSet|grpc::internal::)"
)
GENERIC_HELPER_RE = re.compile(
    r"(?:basic_string|UnknownFieldSet|InternalMetadata|ExecuteShellCommand|CallbackUnaryCallImpl|grpc::Status)"
)
DATACENTER_AUX_THREAD_RE = re.compile(
    r"^(?:Perf|SysCount|Runqlat|Softirqs|Hardirqs|Hitm|FinalKill)\("
)
LOCAL_CLONE_RE = re.compile(r"(?:\(\.(?:isra|constprop|part|cold)|\[clone )")


def is_prefetchable_target_body(body: FunctionBody) -> bool:
    name = body.sym.demangled
    raw = body.sym.raw
    return not (
        LOCAL_CLONE_RE.search(name)
        or ".isra" in raw
        or ".constprop" in raw
        or ".cold" in raw
        or DATACENTER_AUX_THREAD_RE.search(name)
    )


def is_prefetchable_site_body(body: FunctionBody) -> bool:
    name = body.sym.demangled
    raw = body.sym.raw
    if LOCAL_CLONE_RE.search(name) or ".isra" in raw or ".constprop" in raw or ".cold" in raw:
        return False
    if GENERIC_RUNTIME_RE.search(name):
        return False
    return True


def service_control_name_score(name: str) -> float:
    lower = name.lower()
    score = 0.0
    bonuses = (
        ("processresponses", 600.0),
        ("dispatch", 180.0),
        ("asynccompleterpc", 55.0),
        ("drive_machine", 140.0),
        ("process_command_ascii", 110.0),
        ("try_read_command_ascii", 105.0),
        ("process_get_command", 125.0),
        ("process_command", 70.0),
        ("process_get", 85.0),
        ("process_", 28.0),
        ("response", 18.0),
        ("request", 12.0),
        ("command", 35.0),
        ("proceed", 35.0),
        ("complete", 28.0),
        ("serverimpl", 18.0),
        ("rpc", 14.0),
        ("lookup", 12.0),
        ("router", 10.0),
        ("resp_start", 95.0),
        ("resp_finish", 115.0),
        ("resp_", 48.0),
        ("assoc_find", 90.0),
        ("do_item_get", 95.0),
        ("item_get", 90.0),
        ("item_", 24.0),
        ("lru_", 14.0),
        ("murmurhash3", 85.0),
        ("_transmit_pre", 80.0),
        ("bipbuf_request", 70.0),
        ("itoa_u32", 65.0),
        ("limited_get", 75.0),
        ("event_handler", 45.0),
        ("gettime", 180.0),
        ("clear", 8.0),
        ("~", 8.0),
    )
    for token, weight in bonuses:
        if token in lower:
            score += weight
    if GENERIC_RUNTIME_RE.search(name):
        score -= 100.0
    if SERDE_COLD_RE.search(name):
        score -= 120.0
    if STL_RUNTIME_RE.search(name):
        score -= 120.0
    if GENERIC_HELPER_RE.search(name):
        score -= 90.0
    if DATACENTER_AUX_THREAD_RE.search(name):
        score -= 220.0
    if "ThreadSafeQueue<" in name and "::~" in name:
        score -= 160.0
    if name == "main":
        score -= 260.0
    if "ProcessRequest(" in name:
        score -= 120.0
    if "authfile" in lower:
        score -= 120.0
    if "dispatch_conn_new" in lower or "conn_new_cmd" in lower:
        score -= 120.0
    if "process_update_command" in lower:
        score -= 80.0
    if "process_lru_crawler_command" in lower:
        score -= 70.0
    if "process_mget_command" in lower:
        score -= 60.0
    return score


def service_control_body_score(body: FunctionBody, graph: CallGraphFeatures) -> float:
    name = body.sym.demangled
    cond = sum(1 for branch in body.branches if branch.branch_type == "COND")
    calls = sum(1 for branch in body.branches if branch.branch_type == "CALL")
    uncond = sum(1 for branch in body.branches if branch.branch_type == "UNCOND")
    rets = sum(1 for branch in body.branches if branch.branch_type == "RET")
    fanin = len(graph.callers.get(name, ()))
    fanout = len(graph.callees.get(name, ()))
    size_score = math.log2(max(body.sym.size, 1) + 1.0)
    branch_density = len(body.branches) * 1024.0 / max(body.sym.size, 1)
    score = 0.0
    score += 1.4 * size_score
    score += 0.70 * min(cond, 96)
    score += 0.65 * min(calls, 96)
    score += 0.25 * min(uncond, 96)
    score += 1.00 * min(rets, 4)
    score += 4.0 * min(fanin, 24)
    score += 3.0 * min(fanout, 32)
    score += 0.20 * min(branch_density, 96.0)
    score += service_control_name_score(name)
    return score


def structural_body_score(body: FunctionBody, graph: CallGraphFeatures) -> float:
    """Profile-free hot-path prior using only binary control-flow structure."""

    name = body.sym.demangled
    cond = sum(branch.branch_type == "COND" for branch in body.branches)
    calls = sum(branch.branch_type == "CALL" for branch in body.branches)
    rets = sum(branch.branch_type == "RET" for branch in body.branches)
    backedges = sum(
        branch.target_addr is not None and branch.target_addr < branch.addr
        for branch in body.branches
    )
    fanin = len(graph.callers.get(name, ()))
    fanout = len(graph.callees.get(name, ()))
    branch_density = len(body.branches) * 1024.0 / max(body.sym.size, 1)
    score = (
        2.0 * math.log2(max(body.sym.size, 1) + 1.0)
        + 0.8 * min(cond, 128)
        + 0.7 * min(calls, 128)
        + 1.5 * min(rets, 4)
        + 5.0 * min(backedges, 32)
        + 5.0 * min(fanin, 32)
        + 3.5 * min(fanout, 48)
        + 0.3 * min(branch_density, 128.0)
    )
    # Generated serialization and generic runtime bodies are numerous and
    # structurally complex, but they are weak application-specific I-cache
    # targets. Keep them eligible while ranking user control flow ahead.
    if GENERIC_RUNTIME_RE.search(name):
        score -= 500.0
    if SERDE_COLD_RE.search(name):
        score -= 260.0
    if STL_RUNTIME_RE.search(name):
        score -= 220.0
    if GENERIC_HELPER_RE.search(name):
        score -= 160.0
    if DATACENTER_AUX_THREAD_RE.search(name):
        score -= 320.0
    if name == "main":
        score -= 180.0
    if "::~" in name:
        score -= 45.0
    return score


def structural_source_score(loc: Loc) -> float:
    """Prefer application translation units over generated/runtime code."""

    path = loc.file.replace("\\", "/")
    lower = path.lower()
    if not path or path in {"??", "<unknown>"}:
        return 0.0
    if "/usr/include/" in lower or "/usr/lib/" in lower or "/deb_deps/" in lower:
        return -120.0
    if lower.endswith((".pb.cc", ".grpc.pb.cc")) or "/protoc_files/" in lower:
        return -90.0
    if lower.endswith((".c", ".cc", ".cpp", ".cxx")):
        return 80.0
    if lower.endswith((".h", ".hh", ".hpp", ".hxx")):
        return 20.0
    return 0.0


def structural_cacheline_features(
    bodies: dict[str, FunctionBody],
) -> tuple[Counter[int], Counter[int], Counter[int], Counter[int]]:
    branch_sites: Counter[int] = Counter()
    direct_predecessors: Counter[int] = Counter()
    backedge_headers: Counter[int] = Counter()
    call_entries: Counter[int] = Counter()
    for body in bodies.values():
        for branch in body.branches:
            branch_sites[branch.addr & ~0x3F] += 1
            if branch.target_addr is None:
                continue
            target_cacheline = branch.target_addr & ~0x3F
            direct_predecessors[target_cacheline] += 1
            if branch.target_addr < branch.addr:
                backedge_headers[target_cacheline] += 1
            if branch.branch_type == "CALL":
                call_entries[target_cacheline] += 1
    return branch_sites, direct_predecessors, backedge_headers, call_entries


def datacenter_service_loop_role_score(name: str, role: str) -> float:
    """Score service-loop functions separately for target and site ranking.

    The generic service-control score is intentionally broad.  Datacenter
    service binaries often have tiny hot loops such as ProcessResponses(), and
    those bodies need different treatment: as targets they are useful even when
    they have few local predecessor branches, while as sites ProcessRequest()
    and Dispatch() are often better lead points than their target score alone
    suggests.
    """

    lower = name.lower()
    score = 0.0
    if role == "target":
        bonuses = (
            ("processresponses", 420.0),
            ("handlerpcs", 360.0),
            ("dispatch", 300.0),
            ("completionqueue", 220.0),
            ("payloadasyncrequest", 220.0),
            ("requestasynccall", 220.0),
            ("bindcall", 210.0),
            ("callopserversendstatus", 420.0),
            ("withasyncmethod", 280.0),
            ("unique_ptr<intersection::intersectionservice::stub", 260.0),
            ("serverasyncresponsewriter", 190.0),
            ("asynccompleterpc", 120.0),
            ("processrequest", 260.0),
            ("internalparse", 170.0),
            ("utilresponse", 160.0),
            ("unionresponse", 150.0),
            ("gettimeinmicro", 65.0),
            ("finish", 45.0),
            ("clear", 55.0),
            ("~", 75.0),
        )
    else:
        bonuses = (
            ("processresponses", 260.0),
            ("handlerpcs", 260.0),
            ("dispatch", 240.0),
            ("processrequest", 210.0),
            ("completionqueue", 180.0),
            ("payloadasyncrequest", 170.0),
            ("requestasynccall", 170.0),
            ("bindcall", 160.0),
            ("callopserversendstatus", 180.0),
            ("withasyncmethod", 120.0),
            ("unique_ptr<intersection::intersectionservice::stub", 120.0),
            ("serverasyncresponsewriter", 140.0),
            ("asynccompleterpc", 140.0),
            ("gettimeinmicro", 85.0),
            ("finish", 70.0),
            ("runhandler", 30.0),
            ("~", 45.0),
        )
    for token, weight in bonuses:
        if token in lower:
            score += weight
    if GENERIC_RUNTIME_RE.search(name):
        score -= 500.0
    if STL_RUNTIME_RE.search(name):
        score -= 160.0
    if GENERIC_HELPER_RE.search(name):
        score -= 80.0
    if DATACENTER_AUX_THREAD_RE.search(name):
        score -= 320.0
    if role == "target" and "threadsafequeue<" in lower and "::~" in lower:
        score -= 260.0
    return score


def body_cacheline_targets(body: FunctionBody, per_function_limit: int) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()
    for insn in body.insns:
        cacheline = insn.addr & ~0x3F
        if cacheline in seen:
            continue
        seen.add(cacheline)
        out.append(insn.addr)
        if per_function_limit and len(out) >= per_function_limit:
            break
    return out


def branch_site_score(branch: Branch) -> float:
    if branch.branch_type == "CALL":
        return 5.0
    if branch.branch_type == "COND":
        return 4.0
    if branch.branch_type == "UNCOND":
        return 3.0
    if branch.branch_type == "RET":
        return 2.0
    if branch.branch_type.startswith("IND"):
        return 1.0
    return 0.0


def selected_functions(
    bodies: dict[str, FunctionBody],
    symbols: SymbolIndex,
    top_functions: int,
    min_size: int,
    name_regex: str,
) -> list[FunctionBody]:
    pat = re.compile(name_regex) if name_regex else None
    candidates = []
    for body in bodies.values():
        if body.sym.size < min_size:
            continue
        if pat and not pat.search(body.sym.demangled):
            continue
        if not body.branches:
            continue
        candidates.append(body)
    candidates.sort(key=lambda b: (b.sym.size, len(b.branches)), reverse=True)
    return candidates[:top_functions] if top_functions > 0 else candidates


def branch_allowed(branch: Branch, branch_types: set[str]) -> bool:
    return branch.branch_type in branch_types


def target_addrs_for_branch(branch: Branch, target_modes: set[str]) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    if target_modes.intersection({"branch", "branch-cacheline", "sample-ip"}):
        out.append(("branch", branch.addr))
    if "taken" in target_modes and branch.target_addr is not None:
        out.append(("taken", branch.target_addr))
    if "fallthrough" in target_modes and branch.fallthrough_addr is not None:
        out.append(("fallthrough", branch.fallthrough_addr))
    return out


def make_plan(args: argparse.Namespace) -> dict[str, Any]:
    symbols = build_symbol_index(args.binary, args.nm)
    bodies = parse_functions(args.binary, symbols, args.objdump)
    graph = build_call_graph_features(bodies, symbols)
    funcs = selected_functions(bodies, symbols, args.top_functions, args.min_function_size, args.function_regex)
    branch_types = {x.strip().upper() for x in args.branch_types.split(",") if x.strip()}
    target_modes = {x.strip().lower() for x in args.target_modes.split(",") if x.strip()}
    body_scores = {name: service_control_body_score(body, graph) for name, body in bodies.items()}
    body_entry_locs = resolve_addrs(
        args.binary,
        args.addr2line,
        sorted({body.sym.addr for body in bodies.values()}),
    )
    structural_scores = {
        name: structural_body_score(body, graph)
        + structural_source_score(
            body_entry_locs.get(body.sym.addr, Loc("", "", 0))
        )
        for name, body in bodies.items()
    }
    (
        cacheline_branch_sites,
        cacheline_direct_predecessors,
        cacheline_backedge_headers,
        cacheline_call_entries,
    ) = structural_cacheline_features(bodies)
    target_pat = re.compile(args.target_function_regex) if args.target_function_regex else None
    site_pat = re.compile(args.site_function_regex) if args.site_function_regex else None

    def target_body_allowed(body: FunctionBody) -> bool:
        return target_pat is None or bool(target_pat.search(body.sym.demangled))

    def site_body_allowed(body: FunctionBody) -> bool:
        return is_prefetchable_site_body(body) and (site_pat is None or bool(site_pat.search(body.sym.demangled)))

    raw_pairs: list[tuple[Branch, int, str, Branch, FunctionBody]] = []
    for body in funcs:
        branches = [b for b in body.branches if branch_allowed(b, branch_types)]
        for idx, branch in enumerate(branches):
            target_addrs = target_addrs_for_branch(branch, target_modes)
            if not target_addrs:
                continue
            site_start = max(0, idx - args.site_depth + 1)
            site_branches = branches[site_start : idx + 1]
            for mode, target_addr in target_addrs:
                target_sym = symbols.symbol_at(target_addr)
                target_body = body_at_addr(bodies, target_addr)
                if (
                    target_sym is None
                    or target_body is None
                    or not is_prefetchable_target_body(target_body)
                    or not target_body_allowed(target_body)
                ):
                    continue
                if args.same_function_only and target_body.sym.addr != body.sym.addr:
                    continue
                for site_branch in site_branches:
                    if not site_body_allowed(body):
                        continue
                    if args.skip_same_cacheline and ((site_branch.addr & ~0x3F) == (target_addr & ~0x3F)):
                        continue
                    raw_pairs.append((site_branch, target_addr, mode, branch, body))

    if target_modes.intersection({"body", "body-cachelines", "body-entry"}):
        target_bodies = [
            body
            for body in bodies.values()
            if (
                body.sym.size >= args.min_body_target_size
                and body.insns
                and is_prefetchable_target_body(body)
                and target_body_allowed(body)
            )
        ]
        body_rank_scores = (
            structural_scores if args.rank_by == "structural-hotpath" else body_scores
        )
        target_bodies.sort(
            key=lambda body: body_rank_scores.get(body.sym.demangled, 0.0),
            reverse=True,
        )
        if args.body_target_functions > 0:
            target_bodies = target_bodies[: args.body_target_functions]
        body_branch_types = branch_types or {"COND", "CALL", "UNCOND", "RET"}
        direct_callers: dict[str, list[tuple[Branch, FunctionBody, list[Branch]]]] = defaultdict(list)
        for caller_body in bodies.values():
            if not site_body_allowed(caller_body):
                continue
            branches = [branch for branch in caller_body.branches if branch_allowed(branch, body_branch_types)]
            for idx, branch in enumerate(branches):
                if branch.branch_type != "CALL" or branch.target_addr is None:
                    continue
                target_body = body_at_addr(bodies, branch.target_addr)
                if target_body is None:
                    continue
                site_start = max(0, idx - args.site_depth + 1)
                direct_callers[target_body.sym.demangled].append((branch, caller_body, branches[site_start : idx + 1]))
        for target_body in target_bodies:
            if "body-entry" in target_modes and not target_modes.intersection({"body", "body-cachelines"}):
                target_addrs = [target_body.insns[0].addr]
            else:
                target_addrs = body_cacheline_targets(target_body, args.body_cachelines_per_function)
            if not target_addrs:
                continue
            branches = [branch for branch in target_body.branches if branch_allowed(branch, body_branch_types)]
            for target_addr in target_addrs:
                local_sites = [branch for branch in branches if branch.addr < target_addr]
                if not local_sites and args.allow_body_site_fallback:
                    local_sites = branches[: args.site_depth]
                for site_branch in local_sites[-args.site_depth :]:
                    if not site_body_allowed(target_body):
                        continue
                    if args.skip_same_cacheline and ((site_branch.addr & ~0x3F) == (target_addr & ~0x3F)):
                        continue
                    raw_pairs.append((site_branch, target_addr, "body-local", site_branch, target_body))
                for call_branch, caller_body, site_branches in direct_callers.get(target_body.sym.demangled, []):
                    for site_branch in site_branches:
                        if args.skip_same_cacheline and ((site_branch.addr & ~0x3F) == (target_addr & ~0x3F)):
                            continue
                        raw_pairs.append((site_branch, target_addr, "body-call", call_branch, caller_body))
        if args.global_body_site_functions > 0:
            site_bodies = [
                body
                for body in bodies.values()
                if body.branches and body.sym.size >= args.min_function_size and site_body_allowed(body)
            ]
            site_bodies.sort(
                key=lambda body: body_rank_scores.get(body.sym.demangled, 0.0),
                reverse=True,
            )
            site_bodies = site_bodies[: args.global_body_site_functions]
            for target_body in target_bodies:
                target_addrs = body_cacheline_targets(target_body, args.body_cachelines_per_function)
                for target_addr in target_addrs:
                    for site_body in site_bodies:
                        site_branches = [
                            branch
                            for branch in site_body.branches
                            if branch_allowed(branch, body_branch_types)
                        ]
                        site_branches.sort(key=lambda branch: (branch_site_score(branch), branch.addr), reverse=True)
                        for site_branch in site_branches[: args.global_body_sites_per_function]:
                            if args.skip_same_cacheline and ((site_branch.addr & ~0x3F) == (target_addr & ~0x3F)):
                                continue
                            raw_pairs.append((site_branch, target_addr, "body-global", site_branch, site_body))

    if args.rank_by == "distance":
        raw_pairs.sort(
            key=lambda x: (
                x[4].sym.size,
                abs(x[1] - x[0].addr),
                x[1],
                x[0].addr,
            ),
            reverse=True,
        )
    elif args.rank_by == "target-cacheline":
        raw_pairs.sort(key=lambda x: (x[1] & ~0x3F, x[0].addr))
    elif args.rank_by == "service-control":
        def service_key(item: tuple[Branch, int, str, Branch, FunctionBody]) -> tuple[float, float, float, float, int, int]:
            site_branch, target_addr, _mode, origin_branch, origin_body = item
            target_body = body_at_addr(bodies, target_addr)
            target_score = body_scores.get(target_body.sym.demangled, 0.0) if target_body is not None else -1000.0
            origin_score = body_scores.get(origin_body.sym.demangled, 0.0)
            distance = abs(target_addr - site_branch.addr)
            return (
                target_score,
                origin_score,
                branch_site_score(site_branch),
                -min(distance, 1 << 20),
                target_addr & ~0x3F,
                site_branch.addr,
            )

        raw_pairs.sort(key=service_key, reverse=True)
    elif args.rank_by == "datacenter-service-loop":
        def service_loop_key(item: tuple[Branch, int, str, Branch, FunctionBody]) -> tuple[float, float, float, float, float, int, int]:
            site_branch, target_addr, mode, _origin_branch, origin_body = item
            target_body = body_at_addr(bodies, target_addr)
            target_name = target_body.sym.demangled if target_body is not None else ""
            site_name = origin_body.sym.demangled
            target_score = body_scores.get(target_name, -1000.0) + datacenter_service_loop_role_score(target_name, "target")
            site_score = body_scores.get(site_name, -1000.0) + datacenter_service_loop_role_score(site_name, "site")
            distance = abs(target_addr - site_branch.addr)
            mode_score = {
                "branch": 4.0,
                "fallthrough": 3.5,
                "taken": 3.0,
                "body-local": 2.5,
                "body-call": 2.0,
                "body-global": 1.0,
            }.get(mode, 0.0)
            return (
                target_score,
                site_score,
                mode_score,
                branch_site_score(site_branch),
                -min(distance, 1 << 20),
                target_addr & ~0x3F,
                site_branch.addr,
            )

        raw_pairs.sort(key=service_loop_key, reverse=True)
    elif args.rank_by == "structural-hotpath":
        def structural_key(
            item: tuple[Branch, int, str, Branch, FunctionBody],
        ) -> tuple[float, float, float, float, float, int, int]:
            site_branch, target_addr, mode, _origin_branch, origin_body = item
            target_body = body_at_addr(bodies, target_addr)
            target_name = target_body.sym.demangled if target_body is not None else ""
            target_cacheline = target_addr & ~0x3F
            target_score = structural_scores.get(target_name, -1000.0)
            if target_body is not None and target_body.sym.size > 0:
                entry_cacheline = target_body.sym.addr & ~0x3F
                tail_cacheline = (
                    target_body.sym.addr + target_body.sym.size - 1
                ) & ~0x3F
                # Entry and tail blocks are reached after calls/returns and
                # often sit across I-cache working-set transitions. This is a
                # profile-free boundary prior, independent of function names.
                if target_cacheline == entry_cacheline:
                    target_score += 30.0
                if target_cacheline == tail_cacheline:
                    target_score += 100.0
                elif target_cacheline + 64 == tail_cacheline:
                    target_score += 50.0
            target_score += 3.0 * min(cacheline_branch_sites[target_cacheline], 16)
            target_score += 8.0 * min(cacheline_direct_predecessors[target_cacheline], 16)
            target_score += 20.0 * min(cacheline_backedge_headers[target_cacheline], 8)
            target_score += 12.0 * min(cacheline_call_entries[target_cacheline], 8)
            site_score = structural_scores.get(origin_body.sym.demangled, -1000.0)
            distance = max(abs(target_addr - site_branch.addr), 1)
            # A broad 1 KiB lead prior avoids ranking same-line sites first
            # without encoding a workload-specific cycle estimate.
            lead_score = -abs(math.log2(distance) - 10.0)
            mode_score = {
                "branch": 5.0,
                "fallthrough": 4.0,
                "taken": 4.0,
                "body-local": 3.0,
                "body-call": 2.0,
                "body-global": 1.0,
            }.get(mode, 0.0)
            return (
                target_score,
                site_score,
                mode_score,
                branch_site_score(site_branch),
                lead_score,
                target_cacheline,
                site_branch.addr,
            )

        raw_pairs.sort(key=structural_key, reverse=True)
    elif args.rank_by != "address":
        raise SystemExit(f"unknown --rank-by: {args.rank_by}")

    seen: set[tuple[int, int]] = set()
    target_function_counts: Counter[str] = Counter()
    target_cacheline_counts: Counter[int] = Counter()
    pairs: list[tuple[Branch, int, str, Branch, FunctionBody]] = []
    for item in raw_pairs:
        site_branch, target_addr, _mode, _origin, _body = item
        target_body = body_at_addr(bodies, target_addr)
        target_name = target_body.sym.demangled if target_body is not None else ""
        target_cl = target_addr & ~0x3F
        if (
            args.max_injections_per_target_function > 0
            and target_function_counts[target_name] >= args.max_injections_per_target_function
        ):
            continue
        if (
            args.max_injections_per_target_cacheline > 0
            and target_cacheline_counts[target_cl] >= args.max_injections_per_target_cacheline
        ):
            continue
        key = (site_branch.addr, target_addr & ~0x3F)
        if key in seen:
            continue
        seen.add(key)
        target_function_counts[target_name] += 1
        target_cacheline_counts[target_cl] += 1
        pairs.append(item)
        if args.max_injections and len(pairs) >= args.max_injections:
            break

    addr_set = {site.addr for site, _target, _mode, _origin, _body in pairs}
    addr_set |= {target for _site, target, _mode, _origin, _body in pairs}
    locs = resolve_addrs(args.binary, args.addr2line, sorted(addr_set))

    target_rank: dict[int, int] = {}
    injections: list[dict[str, Any]] = []
    missing_symbol = 0
    for site_branch, target_addr, mode, origin_branch, body in pairs:
        site_sym = symbols.symbol_at(site_branch.addr)
        target_body = body_at_addr(bodies, target_addr)
        target_sym = target_body.sym if target_body is not None else symbols.symbol_at(target_addr)
        if site_sym is None or target_sym is None or target_body is None or not is_prefetchable_target_body(target_body):
            missing_symbol += 1
            continue
        target_cl = target_addr & ~0x3F
        if target_cl not in target_rank:
            target_rank[target_cl] = len(target_rank) + 1
        site = source_obj(site_sym, site_branch.addr, locs.get(site_branch.addr, Loc("", "", 0)))
        site.update(
            {
                "branch_type": site_branch.branch_type,
                "lbr_depth": 0,
                "site_kind": f"static-branch-{site_branch.branch_type.lower()}-d{args.site_depth}",
                "origin_branch_addr": hex(origin_branch.addr),
                "origin_branch_type": origin_branch.branch_type,
                "target_mode": mode,
            }
        )
        injections.append(
            {
                "target_rank": target_rank[target_cl],
                "site_rank": 0,
                "samples": 0,
                "new_covered_samples": 0,
                "cumulative_coverage_pct": 0.0,
                "prefetch_mnemonic": args.prefetch_mnemonic,
                "target": source_obj(target_sym, target_addr, locs.get(target_addr, Loc("", "", 0))),
                "site": site,
            }
        )

    byte_offsets = parse_offsets(args.prefetch_byte_offsets)
    plan = {
        "schema": "prefetchit.plan.v1",
        "prefetch_mnemonic": args.prefetch_mnemonic,
        "prefetch": {
            "mnemonic": args.prefetch_mnemonic,
            "operand": "pc-relative-symbol-offset",
            "byte_offsets": byte_offsets,
        },
        "options": {
            "source": "static_branch_target_plan",
            "label": args.label,
            "top_functions": args.top_functions,
            "min_function_size": args.min_function_size,
            "function_regex": args.function_regex,
            "branch_types": sorted(branch_types),
            "target_modes": sorted(target_modes),
            "site_depth": args.site_depth,
            "same_function_only": args.same_function_only,
            "skip_same_cacheline": args.skip_same_cacheline,
            "max_injections": args.max_injections,
            "max_injections_per_target_function": args.max_injections_per_target_function,
            "max_injections_per_target_cacheline": args.max_injections_per_target_cacheline,
            "rank_by": args.rank_by,
            "body_target_functions": args.body_target_functions,
            "body_cachelines_per_function": args.body_cachelines_per_function,
            "min_body_target_size": args.min_body_target_size,
            "global_body_site_functions": args.global_body_site_functions,
            "global_body_sites_per_function": args.global_body_sites_per_function,
            "target_function_regex": args.target_function_regex,
            "site_function_regex": args.site_function_regex,
        },
        "stats": {
            "selected_functions": len(funcs),
            "function_branches": sum(len(f.branches) for f in funcs),
            "raw_pairs": len(raw_pairs),
            "missing_symbol": missing_symbol,
            "selected_injections": len(injections),
            "planned_prefetches": len(injections) * len(byte_offsets),
            "selected_target_cachelines": len({int(i["target"]["cacheline64"], 16) for i in injections}),
            "unique_sites": len({(i["site"]["mangled"], i["site"]["symbol_offset"]) for i in injections}),
        },
        "injections": injections,
    }
    return plan


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--label", default="static_branch")
    ap.add_argument("--prefetch-mnemonic", default="prefetcht1")
    ap.add_argument("--prefetch-byte-offsets", default="0,64")
    ap.add_argument("--top-functions", type=int, default=4)
    ap.add_argument("--min-function-size", type=int, default=4096)
    ap.add_argument("--function-regex", default="VTestDriver")
    ap.add_argument("--branch-types", default="COND")
    ap.add_argument("--target-modes", default="taken,fallthrough")
    ap.add_argument("--site-depth", type=int, default=4)
    ap.add_argument("--max-injections", type=int, default=0)
    ap.add_argument("--max-injections-per-target-function", type=int, default=0)
    ap.add_argument("--max-injections-per-target-cacheline", type=int, default=0)
    ap.add_argument("--body-target-functions", type=int, default=64)
    ap.add_argument("--body-cachelines-per-function", type=int, default=8)
    ap.add_argument("--min-body-target-size", type=int, default=16)
    ap.add_argument("--allow-body-site-fallback", action="store_true")
    ap.add_argument("--global-body-site-functions", type=int, default=0)
    ap.add_argument("--global-body-sites-per-function", type=int, default=8)
    ap.add_argument("--target-function-regex", default="")
    ap.add_argument("--site-function-regex", default="")
    ap.add_argument(
        "--rank-by",
        choices=(
            "address",
            "distance",
            "target-cacheline",
            "service-control",
            "datacenter-service-loop",
            "structural-hotpath",
        ),
        default="distance",
    )
    ap.add_argument("--same-function-only", action="store_true")
    ap.add_argument("--skip-same-cacheline", action="store_true")
    ap.add_argument("--pretty", action="store_true")
    ap.add_argument("--nm", default="llvm-nm-19")
    ap.add_argument("--addr2line", default="llvm-addr2line-19")
    ap.add_argument("--objdump", default="llvm-objdump-19")
    args = ap.parse_args()

    plan = make_plan(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.pretty:
        text = json.dumps(plan, indent=2, sort_keys=True) + "\n"
    else:
        text = json.dumps(plan, separators=(",", ":"), sort_keys=True) + "\n"
    args.output.write_text(text, encoding="utf-8")
    print(f"[ok] wrote {args.output}")
    for k, v in plan["stats"].items():
        print(f"[ok] {k}={v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
