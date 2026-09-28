// Included after the shared placement helpers in PrefetchITPass.cpp.
// Late IR placement: blockaddress operands survive machine layout changes.

static unsigned domOption(const char *Name, unsigned Default) {
  const char *V = std::getenv(Name);
  unsigned N;
  if (!V) return Default;
  if (StringRef(V).getAsInteger(10, N)) report_fatal_error(Twine("invalid ") + Name);
  return N;
}

static uint64_t domHash(StringRef Text) {
  uint64_t H = 14695981039346656037ULL;
  for (unsigned char Ch : Text.bytes()) H = (H ^ Ch) * 1099511628211ULL;
  return H;
}

static std::string domHintKey(uint64_t ModuleID, uint64_t FunctionID,
                              unsigned Group, unsigned Argument) {
  return utohexstr(ModuleID) + ":" + utohexstr(FunctionID) + ":" +
         std::to_string(Group) + ":" + std::to_string(Argument);
}

static std::set<std::string> domDrops(StringRef Placement) {
  std::set<std::string> Result;
  const char *Path = std::getenv("PREFETCHIT_DOM_DROP_PLAN");
  if (!Path) return Result;
  auto Buffer = MemoryBuffer::getFile(Path);
  if (!Buffer) report_fatal_error("cannot read dominator drop plan");
  auto Parsed = json::parse((*Buffer)->getBuffer());
  if (!Parsed) report_fatal_error("invalid dominator drop plan JSON");
  auto *Object = Parsed->getAsObject();
  if (!Object || Object->getString("schema") != "prefetchit.dom_drop.v1" ||
      Object->getString("placement") != Placement)
    report_fatal_error("dominator drop plan placement mismatch");
  auto *Entries = Object->getArray("drop");
  if (!Entries) report_fatal_error("dominator drop plan has no drop array");
  for (auto &Entry : *Entries) {
    auto Key = Entry.getAsString();
    if (!Key || !Result.insert(Key->str()).second)
      report_fatal_error("invalid or duplicate dominator drop key");
  }
  return Result;
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

static Function *domGateHelper(Module &M, unsigned Tier) {
  std::string Name = "__prefetchit_gate_" + std::to_string(Tier);
  if (Function *F = M.getFunction(Name)) return F;
  LLVMContext &Ctx = M.getContext();
  auto *Ty = FunctionType::get(Type::getInt32Ty(Ctx), false);
  auto *F = Function::Create(Ty, GlobalValue::WeakAnyLinkage, Name, M);
  F->setVisibility(GlobalValue::HiddenVisibility); F->setDSOLocal(true);
  F->setCallingConv(CallingConv::PreserveAll);
  F->addFnAttr(Attribute::NoInline); F->addFnAttr(Attribute::OptimizeNone);
  F->addFnAttr(Attribute::NoUnwind);
  // Safe configure/link probes. The executable supplies the strong runtime.
  BasicBlock *B = BasicBlock::Create(Ctx, "entry", F);
  ReturnInst::Create(Ctx, ConstantInt::get(Type::getInt32Ty(Ctx), 0), B);
  return F;
}

static bool runDominatorPrefetch(Module &M, const SeqConfig &C) {
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
  const bool Outline = domOption("PREFETCHIT_DOM_OUTLINE", 0);
  const unsigned MaxSites = domOption("PREFETCHIT_DOM_MAX_SITES", Lean ? 2 : 0);
  const unsigned MinFunction = domOption("PREFETCHIT_DOM_MIN_FUNCTION", Lean ? 64 : 0);
  const bool SkipShort = domOption("PREFETCHIT_DOM_SKIP_SHORT", Lean);
  const bool Metadata = domOption("PREFETCHIT_DOM_METADATA", 0);
  const bool CalleeOnly = domOption("PREFETCHIT_DOM_CALLEE_ONLY", 0);
  const bool ProfileIndirect = domOption("PREFETCHIT_DOM_PROFILE_INDIRECT", 0);
  const char *CalleeProfile = std::getenv("PREFETCHIT_DOM_CALLEE_PROFILE");
  std::set<std::string> ProfileCallees;
  uint64_t CalleeProfileHash = 0;
  if (CalleeProfile) {
    auto Buffer = MemoryBuffer::getFile(CalleeProfile);
    if (!Buffer) report_fatal_error("cannot read dominator callee profile");
    CalleeProfileHash = domHash((*Buffer)->getBuffer());
    SmallVector<StringRef, 64> Lines;
    (*Buffer)->getBuffer().split(Lines, '\n');
    for (StringRef Line : Lines) {
      Line = Line.trim();
      if (!Line.empty() && !Line.starts_with("#")) ProfileCallees.insert(Line.str());
    }
    if (ProfileCallees.empty()) report_fatal_error("empty dominator callee profile");
  }
  // Miss/LBR training supplies a small static set for each indirect caller.
  // These are speculative code hints, never replacements for the real call.
  // All named targets must be audited as global definitions in the main ELF.
  const char *IndirectProfile = std::getenv("PREFETCHIT_DOM_INDIRECT_TARGETS");
  std::map<std::string, std::vector<std::string>> IndirectTargets;
  uint64_t IndirectProfileHash = 0;
  if (IndirectProfile) {
    if (!CalleeOnly || !CalleeProfile || !C.ColdDirectInPIC)
      report_fatal_error("profiled indirect hints require static callee mode");
    auto Buffer = MemoryBuffer::getFile(IndirectProfile);
    if (!Buffer) report_fatal_error("cannot read indirect target profile");
    IndirectProfileHash = domHash((*Buffer)->getBuffer());
    auto Parsed = json::parse((*Buffer)->getBuffer());
    if (!Parsed) report_fatal_error("invalid indirect target JSON");
    auto *Object = Parsed->getAsObject();
    if (!Object || Object->getString("schema") != "prefetchit.indirect_targets.v1")
      report_fatal_error("invalid indirect target schema");
    auto *Callers = Object->getObject("callers");
    if (!Callers) report_fatal_error("missing indirect callers");
    for (const auto &Entry : *Callers) {
      auto *Targets = Entry.second.getAsArray();
      if (!Targets || Targets->empty() || Targets->size() > 8)
        report_fatal_error("invalid indirect target budget");
      std::set<std::string> Seen;
      for (const auto &Target : *Targets) {
        auto Name = Target.getAsString();
        if (!Name || !ProfileCallees.count(Name->str()) || !Seen.insert(Name->str()).second)
          report_fatal_error("unlisted or duplicate indirect target");
        IndirectTargets[Entry.first.str()].push_back(Name->str());
      }
    }
  }
  const uint64_t ModuleID = domHash(M.getSourceFileName());
  std::string Placement;
  for (unsigned N : {MinLead, MaxLead, Batch, CallerTargets, unsigned(Gate), unsigned(Lean),
                     unsigned(Window), unsigned(Outline), MaxSites, MinFunction, unsigned(SkipShort)})
    Placement += (Placement.empty() ? "" : ",") + std::to_string(N);
  if (CalleeOnly || CalleeProfile)
    Placement += ",callee=" + std::to_string(CalleeOnly) + ",profile=" +
                 utohexstr(CalleeProfileHash) + ",indirect=" + std::to_string(ProfileIndirect);
  if (C.ColdDirectInPIC) Placement += ",direct_pic=1";
  if (IndirectProfile) Placement += ",indirect_targets=" + utohexstr(IndirectProfileHash);
  const auto Drops = domDrops(Placement);
  if (Metadata && !Lean) report_fatal_error("dominator metadata requires lean placement");
  if (!Batch || Batch > 16 || MinLead > MaxLead)
    report_fatal_error("invalid dominator placement limits");
  if (Outline && (!Gate || !Window))
    report_fatal_error("outlined dominator gate requires window gating");
  if (CalleeOnly && (!Lean || CallerTargets))
    report_fatal_error("callee-only mode requires lean placement and zero caller BB targets");
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
  uint64_t ProfileRemoved = 0, CalleeSkipped = 0;
  uint64_t PredictedIndirect = 0;
  DenseMap<BasicBlock *, Instruction *> OriginalHeads;
  std::vector<std::pair<CallInst *, std::vector<BasicBlock *>>> AnchoredCalls;
  if (Outline) for (Function *F : Functions) for (BasicBlock &B : *F)
    if (!B.isEHPad() && B.getFirstInsertionPt() != B.end())
      OriginalHeads[&B] = &*B.getFirstInsertionPt();
  for (Function *F : Functions) {
    if (F->getInstructionCount() < MinFunction) continue;
    const uint64_t FunctionID = domHash(F->getName());
    DominatorTree DT(*F);
    struct Target { Value *Address; bool Direct; };
    std::map<Instruction *, std::vector<Target>> Sites;
    auto add = [&](Instruction *Use, Value *Address, bool Direct) {
      if (!DT.isReachableFromEntry(Use->getParent()) || Use->getParent()->isEHPad()) {
        ++SkippedEH; return;
      }
      Instruction *At = domPlace(Use, DT, MinLead, MaxLead);
      if (Outline && At->getParent()->isEntryBlock()) {
        // Splitting before static entry allocas turns them into dynamic
        // allocas. Keep the allocation prefix in the original entry block.
        Instruction *First = &*At->getParent()->getFirstNonPHIOrDbgOrAlloca();
        if (DT.dominates(At, First)) At = First;
        if (!DT.dominates(At, Use)) { ++BudgetSkipped; return; }
      }
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
        if (CalleeOnly) continue;
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
          if (CalleeProfile && !ProfileCallees.count(G->getName().str())) {
            ++CalleeSkipped; continue;
          }
          // This explicit opt-in is only valid for profile targets verified
          // to bind to the final main image. PIC otherwise rejects Function
          // operands with an immediate constraint. Exact NOP controls retain
          // this binding too, including any changes to ordinary call codegen.
          if (CalleeOnly && CalleeProfile && C.ColdDirectInPIC) G->setDSOLocal(true);
          ++Calls;
          // An explicit LLVM operand preserves strong archive extraction and
          // lets the backend handle external/interposable symbols via a reg.
          bool Direct = G->hasLocalLinkage() || G->isDSOLocal() || C.ColdDirectInPIC;
          add(CB, G, Direct);
          for (BasicBlock *S : EntryTargets[G]) {
            add(CB, BlockAddress::get(G, S), true); ++Lifted;
          }
        } else {
          auto It = IndirectTargets.find(F->getName().str());
          if (It != IndirectTargets.end()) {
            for (const auto &Name : It->second) {
              Function *G = M.getFunction(Name);
              if (!G) {
                if (M.getNamedValue(Name))
                  report_fatal_error("indirect target is not a function");
                G = Function::Create(FunctionType::get(Type::getVoidTy(Ctx), false),
                                     GlobalValue::ExternalLinkage, Name, M);
              }
              G->setDSOLocal(true);
              add(CB, G, true); ++PredictedIndirect;
            }
          }
          if (CalleeProfile && !ProfileIndirect) { ++CalleeSkipped; continue; }
          ++Indirect; add(CB, Address, false);
        }
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
        unsigned GroupID = SiteIndex++;
        std::vector<bool> Active;
        for (unsigned J = Begin; J < End; ++J) {
          bool Keep = !Drops.count(domHintKey(ModuleID, FunctionID, GroupID, J - Begin));
          if (!Keep && !Targets[J].Direct)
            report_fatal_error("drop plan attempted to remove an indirect target");
          Active.push_back(Keep); ProfileRemoved += !Keep;
        }
        bool AnyActive = llvm::is_contained(Active, true);
        if (!AnyActive && !Metadata) continue;
        std::string Asm, Constraints;
        Instruction *Insert = At;
        if (Outline && AnyActive) {
          auto *Call = CallInst::Create(domGateHelper(M, Tier), "", At);
          Call->setCallingConv(CallingConv::PreserveAll);
          Call->setDoesNotThrow(); Call->setDebugLoc(At->getDebugLoc());
          auto *Cond = new ICmpInst(At, CmpInst::ICMP_NE, Call,
              ConstantInt::get(Type::getInt32Ty(Ctx), 0));
          Insert = SplitBlockAndInsertIfThen(Cond, At, false);
        }
        if (Gate && !Outline && AnyActive) {
          Asm = "movq __prefetchit_sched_slots(%rip), %r11\n\ttestq %r11, %r11\n\tje 9f\n\t"
                "rdtscp\n\tshlq $$32, %rdx\n\torq %rdx, %rax\n\t"
                "andl $$4095, %ecx\n\tshll $$6, %ecx\n\t"
                "cmpq " + std::to_string(Window ? 32 + Tier * 8 : 24) +
                "(%r11,%rcx), %rax\n\tjb 9f\n\tcmpq " +
                std::to_string(Tier * 8) + "(%r11,%rcx), %rax\n\tjae 9f\n\t";
        }
        SmallVector<Value *, 16> Args;
        SmallVector<Type *, 16> Types;
        std::vector<BasicBlock *> Anchors;
        std::string Records;
        for (unsigned J = Begin; J < End; ++J) {
          bool Keep = Active[J - Begin];
          if (!Keep && !Metadata) continue;
          unsigned N = Args.size();
          Args.push_back(Targets[J].Address); Types.push_back(Args.back()->getType());
          auto *BA = dyn_cast<BlockAddress>(Targets[J].Address);
          Anchors.push_back(BA ? BA->getBasicBlock() : nullptr);
          if (!Constraints.empty()) Constraints += ",";
          Constraints += Targets[J].Direct ? "i" : "r";
          std::string Label = ".Lpf_" + utohexstr(ModuleID) + "_" + utohexstr(FunctionID) +
                              "_" + std::to_string(GroupID) + "_" + std::to_string(J - Begin) + "_${:uid}";
          if (Keep) {
            if (Metadata) Asm += Label + ":\n\t";
            Asm += C.Mnemonic + (Targets[J].Direct ? " ${" + std::to_string(N) + ":c}(%rip)\n\t" :
                                " ($" + std::to_string(N) + ")\n\t");
            ++Hints;
          }
          if (Metadata) {
            // Codegen can duplicate an asm group. LLVM's uid names each
            // physical copy, while the logical key stays stable for plans.
            // Non-allocated records contain five u64 words plus group/arg/
            // flags: 48 bytes. The uid is shared by this asm's operands.
            Records += ".quad " + (Keep ? Label : "0") + "\n\t.quad " +
              (Targets[J].Direct ? "${" + std::to_string(N) + ":c}" : "0") +
              "\n\t.quad 0x" + utohexstr(ModuleID) + "\n\t.quad 0x" + utohexstr(FunctionID) +
              "\n\t.quad ${:uid}\n\t.long " + std::to_string(GroupID) + "\n\t.short " + std::to_string(J - Begin) +
              "\n\t.short " + std::to_string(unsigned(Keep) | (unsigned(Targets[J].Direct) << 1)) + "\n\t";
          }
        }
        if (Gate && !Outline && AnyActive) {
          Asm += "9:\n\t";
          Constraints += ",~{rax},~{rdx},~{rcx},~{r11},~{flags},~{memory}";
        }
        if (Metadata) {
          // Keep COMDAT metadata with its owning function. Discarded weak
          // copies must not leave dangling local-label relocations behind.
          Asm += ".pushsection .debug_prefetchit_v2,\"";
          if (F->hasComdat())
            Asm += "G\",@progbits," + F->getComdat()->getName().str() + ",comdat\n\t";
          else Asm += "\",@progbits\n\t";
          Asm += Records + ".popsection\n\t";
        }
        auto *Ty = FunctionType::get(Type::getVoidTy(Ctx), Types, false);
        auto *CI = CallInst::Create(InlineAsm::get(Ty, Asm, Constraints, true), Args, "", Insert);
        CI->setDebugLoc(At->getDebugLoc()); Groups += AnyActive;
        if (Outline) AnchoredCalls.emplace_back(CI, std::move(Anchors));
      }
    }
    // Conditional helper gates split BBs after target collection. Explicit
    // numbering also works for functions originally built without a symtab.
    if (Outline) {
      unsigned Label = 0;
      for (BasicBlock &B : *F) B.setName("");
      for (BasicBlock &B : *F) B.setName("__prefetchit_bb_" + std::to_string(Label++));
    }
  }
  // Follow the original application instruction after helper-gate splits,
  // including callee BBs processed later. Only rewrite our hint operands;
  // never change application blockaddress/indirectbr semantics.
  for (auto &[Call, Anchors] : AnchoredCalls)
    for (unsigned J = 0; J < Anchors.size(); ++J)
      if (Instruction *Head = OriginalHeads.lookup(Anchors[J]))
        Call->setArgOperand(J, BlockAddress::get(Head->getFunction(), Head->getParent()));
  errs() << "prefetchit-dominator: functions=" << Functions.size() << " edges=" << Edges
         << " calls=" << Calls << " indirect=" << Indirect << " continuations=" << Continuations
         << " caller_targets=" << Lifted << " short_lead=" << Short << " skipped_eh=" << SkippedEH
         << " groups=" << Groups << " hints=" << Hints << " gate=" << Gate << "\n";
  if (Lean) errs() << "prefetchit-dominator-lean: budget_skipped=" << BudgetSkipped
                   << " duplicate_targets=" << Duplicates << " window=" << Window << "\n";
  if (Metadata || !Drops.empty()) errs() << "prefetchit-dominator-profile: placement=" << Placement
      << " module=" << utohexstr(ModuleID) << " removed=" << ProfileRemoved << " metadata=" << Metadata << "\n";
  if (CalleeOnly || CalleeProfile) errs() << "prefetchit-dominator-callees: only=" << CalleeOnly
      << " profiled=" << ProfileCallees.size() << " skipped=" << CalleeSkipped << "\n";
  if (IndirectProfile) errs() << "prefetchit-dominator-indirect-targets: candidates="
      << PredictedIndirect << " callers=" << IndirectTargets.size() << "\n";
  Ctx.setDiscardValueNames(DiscardNames);
  return true; // Globals, labels or metadata can change even when hints are zero.
}
