// Included after the shared placement helpers in PrefetchITPass.cpp.
// Late IR placement: blockaddress operands survive machine layout changes.

static unsigned domOption(const char *Name, unsigned Default) {
  const char *V = std::getenv(Name);
  unsigned N;
  if (!V) return Default;
  if (StringRef(V).getAsInteger(10, N)) report_fatal_error(Twine("invalid ") + Name);
  return N;
}

// Dijkstra, not FIFO BFS: BB instruction counts are unequal edge weights.
static unsigned domLead(Instruction *From, Instruction *Use, unsigned Cap) {
  using Item = std::pair<unsigned, BasicBlock *>;
  std::priority_queue<Item, std::vector<Item>, std::greater<Item>> Q;
  DenseMap<BasicBlock *, unsigned> Best;
  auto scan = [&](Instruction *Begin, unsigned Cost) -> std::pair<bool, unsigned> {
    for (auto I = Begin->getIterator(); I != Begin->getParent()->end(); ++I) {
      if (&*I == Use) return {true, Cost};
      if (!isIgnorableInstruction(*I)) ++Cost;
    }
    return {false, Cost};
  };
  auto First = scan(From, 0);
  if (First.first) return First.second;
  Best[From->getParent()] = 0;
  for (BasicBlock *B : successors(From->getParent())) {
    if (Best.count(B)) continue;
    Q.emplace(First.second, B); Best[B] = First.second;
  }
  while (!Q.empty()) {
    auto [D, B] = Q.top(); Q.pop();
    if (D > Cap) break;
    if (Best.lookup(B) != D) continue;
    auto Result = scan(&B->front(), D);
    if (Result.first) return Result.second;
    for (BasicBlock *S : successors(B)) {
      auto It = Best.find(S);
      if (It == Best.end() || Result.second < It->second) {
        Best[S] = Result.second; Q.emplace(Result.second, S);
      }
    }
  }
  return Cap + 1;
}

static Instruction *domPlace(Instruction *Use, DominatorTree &DT,
                             unsigned MinLead, unsigned MaxLead) {
  // Start locally, then walk actual dominators. Do not equate dominance with
  // path certainty: issuing on a dominator may prefetch an untaken successor.
  Instruction *Fallback = moveInsertionEarlier(*Use, MinLead);
  Instruction *At = Fallback;
  for (BasicBlock *B = Use->getParent(); B;) {
    if (!B->isEHPad()) {
      unsigned Lead = domLead(At, Use, MaxLead);
      if (Lead >= MinLead && Lead <= MaxLead) return At;
      if (Lead > MaxLead) break;
      Fallback = At;
    }
    DomTreeNode *N = DT.getNode(B);
    if (!N || !N->getIDom()) break;
    B = N->getIDom()->getBlock();
    At = &*B->getFirstInsertionPt();
  }
  return Fallback; // counted separately; caller placement adds another chance
}

static uint64_t runDominatorPrefetch(Module &M, const SeqConfig &C) {
  if (!domOption("PREFETCHIT_DOMINATOR", 0)) return 0;
  if (!moduleAllowed(M, "prefetchit-dominator")) return 0;
  if (!StringRef(M.getTargetTriple()).starts_with("x86_64"))
    report_fatal_error("dominator prefetch requires x86-64");
  const unsigned MinLead = domOption("PREFETCHIT_DOM_LEAD", 24);
  const unsigned MaxLead = domOption("PREFETCHIT_DOM_MAX_LEAD", 600);
  const unsigned Batch = domOption("PREFETCHIT_DOM_BATCH", 4);
  const unsigned CallerTargets = domOption("PREFETCHIT_DOM_CALLER_TARGETS", 4);
  const bool Gate = domOption("PREFETCHIT_DOM_SCHED_GATE", 1);
  const bool Lean = domOption("PREFETCHIT_DOM_LEAN", 0);
  const bool Window = domOption("PREFETCHIT_DOM_WINDOW", 0);
  const unsigned MaxSites = domOption("PREFETCHIT_DOM_MAX_SITES", Lean ? 2 : 0);
  const unsigned MinFunction = domOption("PREFETCHIT_DOM_MIN_FUNCTION", Lean ? 64 : 0);
  const bool SkipShort = domOption("PREFETCHIT_DOM_SKIP_SHORT", Lean);
  if (!Batch || Batch > 16 || MinLead > MaxLead)
    report_fatal_error("invalid dominator placement limits");
  LLVMContext &Ctx = M.getContext();
  const bool DiscardNames = Ctx.shouldDiscardValueNames();
  Ctx.setDiscardValueNames(false);
  if (Gate) {
    // Weak zero permits library configure probes without the runtime. The
    // service links a strong definition plus the mmap constructor. Hidden
    // binding is deliberate: each linked image owns its clock mapping.
    auto *G = M.getGlobalVariable("__prefetchit_sched_slots", true);
    if (!G) {
      G = new GlobalVariable(M, PointerType::getUnqual(Ctx), false,
          GlobalValue::WeakAnyLinkage, ConstantPointerNull::get(PointerType::getUnqual(Ctx)),
          "__prefetchit_sched_slots");
      G->setVisibility(GlobalValue::HiddenVisibility); G->setDSOLocal(true);
      G->setAlignment(Align(8)); appendToUsed(M, {G});
    }
  }
  std::optional<Regex> Include, Exclude;
  if (!C.Include.empty()) Include.emplace(C.Include);
  if (!C.Exclude.empty()) Exclude.emplace(C.Exclude);
  std::vector<Function *> Functions;
  for (Function &F : M)
    if (!F.isDeclaration() && !F.getName().starts_with("__prefetchit_") &&
        C.selects(F.getName(), Include, Exclude) && !F.hasFnAttribute(Attribute::Naked))
      Functions.push_back(&F);

  // Give normal call continuations real BB labels. Musttail and inline asm
  // are excluded. Machine fallthrough remains possible; no hard-coded offsets.
  uint64_t Continuations = 0, Edges = 0, Calls = 0, Indirect = 0;
  for (Function *F : Functions) {
    if (Lean) continue;
    SmallVector<CallInst *, 32> Split;
    for (Instruction &I : instructions(F))
      if (auto *CI = dyn_cast<CallInst>(&I))
        if (!CI->isInlineAsm() && !isa<IntrinsicInst>(CI) && !CI->isMustTailCall() &&
            !CI->doesNotReturn() && !CI->getParent()->isEHPad()) Split.push_back(CI);
    for (auto *CI : Split) {
      SplitBlock(CI->getParent(), CI->getNextNode()); ++Continuations;
    }
  }
  std::map<Function *, std::vector<BasicBlock *>> EntryTargets;
  for (Function *F : Functions) {
    // LLVM textual IR cannot refer back to another function's numeric BB
    // labels. Named labels also make cross-function operand audits readable.
    unsigned Label = 0;
    for (BasicBlock &B : *F) {
      // Functions originally created with discarded names have no symbol
      // table to uniquify SplitBlock's repeated '.split' names. Rename ALL.
      B.setName("__prefetchit_bb_" + std::to_string(Label));
      ++Label;
    }
    // Cross-function blockaddress references into discardable COMDAT copies
    // are unsafe. Such calls still prefetch the linker-selected function entry.
    if (F->isWeakForLinker()) continue;
    SmallPtrSet<BasicBlock *, 32> Seen;
    std::deque<BasicBlock *> Q{&F->getEntryBlock()};
    Seen.insert(Q.front());
    while (!Q.empty() && EntryTargets[F].size() < CallerTargets) {
      BasicBlock *B = Q.front(); Q.pop_front();
      for (BasicBlock *S : successors(B))
        if (!S->isEHPad() && Seen.insert(S).second) {
          EntryTargets[F].push_back(S); Q.push_back(S);
          if (EntryTargets[F].size() == CallerTargets) break;
        }
    }
  }
  uint64_t Hints = 0, Groups = 0, Short = 0, Lifted = 0, SkippedEH = 0;
  uint64_t BudgetSkipped = 0, Duplicates = 0;
  for (Function *F : Functions) {
    if (F->getInstructionCount() < MinFunction) continue;
    DominatorTree DT(*F);
    struct Target { Value *Address; bool Direct; };
    std::map<Instruction *, std::vector<Target>> Sites;
    auto add = [&](Instruction *Use, Value *Address, bool Direct) {
      if (!DT.isReachableFromEntry(Use->getParent()) || Use->getParent()->isEHPad()) {
        ++SkippedEH; return;
      }
      Instruction *At = domPlace(Use, DT, MinLead, MaxLead);
      if (!Direct) {
        // No new speculative pointer dereference. The already-computed SSA
        // target must dominate issuance; otherwise leave it at the call.
        if (auto *Def = dyn_cast<Instruction>(Address))
          if (!DT.dominates(Def, At) || Def == At) At = Use;
      }
      if (domLead(At, Use, MaxLead) < MinLead) {
        ++Short;
        if (SkipShort) return;
      }
      auto &V = Sites[At];
      if (llvm::none_of(V, [&](const Target &T) { return T.Address == Address; }))
        V.push_back({Address, Direct});
    };
    for (BasicBlock &B : *F) {
      for (BasicBlock *S : successors(&B)) {
        if (S->isEHPad() || S == &F->getEntryBlock()) { ++SkippedEH; continue; }
        // A one-successor fallthrough rarely needs a separate code-line hint.
        if (Lean && B.getTerminator()->getNumSuccessors() == 1) continue;
        ++Edges; add(B.getTerminator(), BlockAddress::get(F, S), true);
      }
      for (Instruction &I : B) {
        auto *CB = dyn_cast<CallBase>(&I);
        if (!CB || CB->isInlineAsm() || isa<IntrinsicInst>(CB)) continue;
        Value *Address = CB->getCalledOperand()->stripPointerCasts();
        if (auto *G = dyn_cast<Function>(Address)) {
          if (G->isIntrinsic()) continue;
          ++Calls;
          // An explicit LLVM operand preserves strong archive extraction and
          // lets the backend handle external/interposable symbols via a reg.
          bool Direct = G->hasLocalLinkage() || G->isDSOLocal() || C.ColdDirectInPIC;
          add(CB, G, Direct);
          for (BasicBlock *S : EntryTargets[G]) {
            add(CB, BlockAddress::get(G, S), true); ++Lifted;
          }
        } else { ++Indirect; add(CB, Address, false); }
      }
    }
    // Emit in program order, never pointer-map order (ASLR-dependent builds).
    std::vector<Instruction *> Ordered;
    for (Instruction &I : instructions(F)) if (Sites.count(&I)) Ordered.push_back(&I);
    if (Lean) {
      // Rank shared dominator sites before applying a per-function budget.
      // Stable ties follow IR order; no pointer/ASLR-dependent selection.
      std::stable_sort(Ordered.begin(), Ordered.end(), [&](Instruction *A, Instruction *B) {
        return Sites.at(A).size() > Sites.at(B).size();
      });
      SmallPtrSet<Value *, 32> Seen;
      std::vector<Instruction *> Selected;
      for (Instruction *At : Ordered) {
        auto &V = Sites.at(At);
        if (MaxSites && Selected.size() >= MaxSites) { BudgetSkipped += V.size(); continue; }
        std::vector<Target> Unique;
        for (const Target &T : V) {
          if (Seen.count(T.Address)) { ++Duplicates; continue; }
          if (Unique.size() >= Batch) { ++BudgetSkipped; continue; }
          Seen.insert(T.Address); Unique.push_back(T);
        }
        V = std::move(Unique);
        if (!V.empty()) Selected.push_back(At);
      }
      Ordered.clear();
      for (Instruction &I : instructions(F))
        if (llvm::is_contained(Selected, &I)) Ordered.push_back(&I);
    }
    unsigned SiteIndex = 0;
    for (Instruction *At : Ordered) {
      const auto &Targets = Sites.at(At);
      for (unsigned Begin = 0; Begin < Targets.size(); Begin += Batch) {
        unsigned End = std::min<unsigned>(Targets.size(), Begin + Batch);
        // Rotate within each function; targets at a shared site are also
        // thinned. Tiny functions do not all receive the long-lived tier.
        unsigned Tier = ((SiteIndex + F->getName().size()) % 4 == 0) ? 2 :
               ((SiteIndex + F->getName().size()) % 4 == 1) ? 1 : 0;
        ++SiteIndex;
        std::string Asm, Constraints;
        if (Gate) {
          Asm = "movq __prefetchit_sched_slots(%rip), %r11\n\ttestq %r11, %r11\n\tje 9f\n\t"
                "rdtscp\n\tshlq $$32, %rdx\n\torq %rdx, %rax\n\t"
                "andl $$4095, %ecx\n\tshll $$6, %ecx\n\t"
                "cmpq " + std::to_string(Window ? 32 + Tier * 8 : 24) +
                "(%r11,%rcx), %rax\n\tjb 9f\n\tcmpq " +
                std::to_string(Tier * 8) + "(%r11,%rcx), %rax\n\tjae 9f\n\t";
        }
        SmallVector<Value *, 16> Args;
        SmallVector<Type *, 16> Types;
        for (unsigned J = Begin; J < End; ++J) {
          unsigned N = Args.size();
          Args.push_back(Targets[J].Address); Types.push_back(Args.back()->getType());
          if (!Constraints.empty()) Constraints += ",";
          Constraints += Targets[J].Direct ? "i" : "r";
          Asm += C.Mnemonic + (Targets[J].Direct ? " ${" + std::to_string(N) + ":c}(%rip)\n\t" :
                              " ($" + std::to_string(N) + ")\n\t");
          ++Hints;
        }
        if (Gate) {
          Asm += "9:\n\t";
          Constraints += ",~{rax},~{rdx},~{rcx},~{r11},~{flags},~{memory}";
        }
        auto *Ty = FunctionType::get(Type::getVoidTy(Ctx), Types, false);
        auto *CI = CallInst::Create(InlineAsm::get(Ty, Asm, Constraints, true), Args, "", At);
        CI->setDebugLoc(At->getDebugLoc()); ++Groups;
      }
    }
  }
  errs() << "prefetchit-dominator: functions=" << Functions.size() << " edges=" << Edges
         << " calls=" << Calls << " indirect=" << Indirect << " continuations=" << Continuations
         << " caller_targets=" << Lifted << " short_lead=" << Short << " skipped_eh=" << SkippedEH
         << " groups=" << Groups << " hints=" << Hints << " gate=" << Gate << "\n";
  if (Lean) errs() << "prefetchit-dominator-lean: budget_skipped=" << BudgetSkipped
                   << " duplicate_targets=" << Duplicates << " window=" << Window << "\n";
  Ctx.setDiscardValueNames(DiscardNames);
  return Hints;
}
