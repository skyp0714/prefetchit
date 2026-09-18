#include "llvm/ADT/SmallVector.h"
#include "llvm/ADT/StringRef.h"
#include "llvm/ADT/StringExtras.h"
#include "llvm/IR/BasicBlock.h"
#include "llvm/IR/Dominators.h"
#include "llvm/Analysis/LoopInfo.h"
#include "llvm/IR/Constants.h"
#include "llvm/IR/DebugInfoMetadata.h"
#include "llvm/IR/InlineAsm.h"
#include "llvm/IR/InstIterator.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/IntrinsicInst.h"
#include "llvm/IR/GlobalAlias.h"
#include "llvm/Transforms/Utils/ModuleUtils.h"
#include "llvm/IR/Module.h"
#include "llvm/IR/PassManager.h"
#include "llvm/Passes/PassBuilder.h"
#include "llvm/Passes/PassPlugin.h"
#include "llvm/Support/CommandLine.h"
#include "llvm/Support/Error.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/MemoryBuffer.h"
#include "llvm/Support/Path.h"
#include "llvm/Support/FileSystem.h"
#include "llvm/Support/raw_ostream.h"

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <cstdint>
#include <charconv>
#include <map>
#include <optional>
#include <set>
#include "llvm/Support/Regex.h"

#include <string>
#include <vector>

using namespace llvm;

#ifndef PREFETCHIT_DEFAULT_PLAN
#define PREFETCHIT_DEFAULT_PLAN ""
#endif

static cl::opt<std::string> PrefetchITPlanPath(
    "prefetchit-plan",
    cl::desc("Path to a prefetchit.plan.v1 JSON file"),
    cl::value_desc("path"), cl::init(""));

static cl::opt<bool>
    PrefetchITVerbose("prefetchit-verbose",
                      cl::desc("Print detailed PrefetchIT pass diagnostics"),
                      cl::init(false));

// Exact symbol+offset targets are baseline-binary offsets; every prefetch
// injected earlier in the same function pushes the target's code forward by
// the injected bytes. Compensate so the operand still lands on the planned
// cacheline (the plan's site offsets tell us what precedes each target).
static cl::opt<bool> PrefetchITLayoutCompensation(
    "prefetchit-layout-compensation",
    cl::desc("Shift symbol+offset targets by the bytes of prefetches injected "
             "before them in the same function"),
    cl::init(true));

static cl::opt<std::string> PrefetchITMnemonicOverride(
    "prefetchit-mnemonic",
    cl::desc("Override plan prefetch mnemonic: prefetcht0, prefetcht1, "
             "prefetcht2, prefetchnta, prefetchit0, or prefetchit1"),
    cl::value_desc("mnemonic"), cl::init(""));

// Plan-free "sequential lookahead" mode (static, profile-free): in every
// function whose mangled name matches -prefetchit-seq-functions (and not
// -prefetchit-seq-exclude), insert `prefetcht1 D(%rip)` before every K-th IR
// instruction, D = -prefetchit-seq-distance bytes, optionally for L consecutive
// cachelines (D, D+64, ...). The operand is a constant rip-relative
// displacement, so the target is always "D bytes ahead of here" in the final
// layout: no symbol+offset drift, no layout compensation, no re-anchoring.
// This is the software equivalent of a next-N-line instruction prefetcher for
// straight-line generated code (Verilator/arcilator), where the L2I miss stream
// is sequential and the last taken branch merely labels each miss.
static cl::opt<unsigned> PrefetchITSeqDistance(
    "prefetchit-seq-distance",
    cl::desc("Sequential lookahead distance in bytes (0 = off); env "
             "PREFETCHIT_SEQ_DISTANCE"),
    cl::init(0));
static cl::opt<unsigned> PrefetchITSeqStrideInsns(
    "prefetchit-seq-stride-insns",
    cl::desc("Insert one lookahead prefetch every K IR instructions; env "
             "PREFETCHIT_SEQ_STRIDE_INSNS"),
    cl::init(0));
static cl::opt<unsigned> PrefetchITSeqLines(
    "prefetchit-seq-lines",
    cl::desc("Consecutive 64 B lines per site (D, D+64, ...); env "
             "PREFETCHIT_SEQ_LINES"),
    cl::init(0));
static cl::opt<std::string> PrefetchITSeqFunctions(
    "prefetchit-seq-functions",
    cl::desc("Regex over mangled names selecting functions for sequential "
             "lookahead (default: all); env PREFETCHIT_SEQ_FUNCTIONS"),
    cl::init(""));
static cl::opt<std::string> PrefetchITSeqExclude(
    "prefetchit-seq-exclude",
    cl::desc("Regex over mangled names excluded from sequential lookahead; "
             "env PREFETCHIT_SEQ_EXCLUDE"),
    cl::init(""));
// Callee-entry burst (plan-free companion of the sequential mode): before each
// direct call to a defined function matching the seq include/exclude regexes,
// insert `prefetcht1 callee+64*l(%rip)` for l in [0, burst-lines), placed
// -prefetchit-callee-burst-lead IR instructions before the call so the
// callee's first lines are in flight when the call executes. Straight-line
// generated callees (Verilator nba_sequent) are entered in program order, so
// this is the cross-function half of the software instruction prefetcher: the
// sequential mode covers bytes >= D into any function, the burst covers the
// first lines that the caller's rip-relative stream cannot reach.
static cl::opt<unsigned> PrefetchITCalleeBurstLines(
    "prefetchit-callee-burst-lines",
    cl::desc("Lines of each direct callee's entry to prefetch before the call "
             "(0 = off); env PREFETCHIT_CALLEE_BURST_LINES"),
    cl::init(0));
static cl::opt<unsigned> PrefetchITCalleeBurstLead(
    "prefetchit-callee-burst-lead",
    cl::desc("IR instructions before the call at which the burst is issued "
             "(within the block; env PREFETCHIT_CALLEE_BURST_LEAD)"),
    cl::init(0));
static cl::opt<unsigned> PrefetchITCalleeBurstMinCalleeInsns(
    "prefetchit-callee-burst-min-callee-insns",
    cl::desc("Only burst callees with at least this many IR instructions; env "
             "PREFETCHIT_CALLEE_BURST_MIN_CALLEE_INSNS"),
    cl::init(0));
static cl::opt<std::string> PrefetchITSeqFunctionsFile(
    "prefetchit-seq-functions-file",
    cl::desc("File with one mangled function name per line; when given, only "
             "listed functions get sequential lookahead / callee bursts (the "
             "regexes still apply on top); env PREFETCHIT_SEQ_FUNCTIONS_FILE"),
    cl::init(""));
// Shared-library modules (PIC level 2 without a PIE level) cannot carry
// rip-relative references to executable-only symbols; skip them so a plan for
// the main binary does not break the link of DSOs built with the same flags.
static cl::opt<bool> PrefetchITSkipPICModules(
    "prefetchit-skip-pic-modules",
    cl::desc("Do not inject into -fPIC (non-PIE) modules; env PREFETCHIT_SKIP_PIC=1"),
    cl::init(false));
static cl::opt<unsigned> PrefetchITSeqMinInsns(
    "prefetchit-seq-min-insns",
    cl::desc("Skip functions with fewer IR instructions than this; env "
             "PREFETCHIT_SEQ_MIN_INSNS"),
    cl::init(0));

namespace {

constexpr StringRef DefaultPrefetchMnemonic = "prefetcht1";

struct SourceLocSpec {
  std::string Mangled;
  std::string Demangled;
  std::string Function;
  std::string File;
  unsigned Line = 0;
  unsigned Column = 0;
  unsigned Discriminator = 0;
  std::string Addr;
  std::string SymbolOffset;
  std::string SymbolType;
  std::string OperandMode;
};

struct InjectionSpec {
  unsigned Index = 0; // position in the plan's injections array
  std::string Mnemonic;
  std::vector<int64_t> ByteOffsets;
  unsigned TargetRank = 0;
  unsigned SiteRank = 0;
  uint64_t Samples = 0;
  uint64_t NewCoveredSamples = 0;
  double CumulativeCoveragePct = 0.0;
  std::string BranchType;
  unsigned LBRDepth = 0;
  SourceLocSpec Target;
  SourceLocSpec Site;
};

struct Plan {
  std::string DefaultMnemonic = DefaultPrefetchMnemonic.str();
  std::string OperandMode = "pc-relative-symbol-offset";
  std::vector<int64_t> ByteOffsets = {0};
  unsigned LeadInstructions = 0;
  std::vector<InjectionSpec> Injections;
};

struct InjectionStats {
  unsigned Injected = 0;
  unsigned LayoutShiftApplied = 0;
  unsigned RankedSites = 0;
  uint64_t LayoutShiftMaxBytes = 0;
  unsigned Duplicate = 0;
  unsigned UnsupportedMnemonic = 0;
  unsigned SymbolOffsetTarget = 0;
  unsigned CrossModuleSymbolOffsetTarget = 0;
  unsigned GotSymbolOffsetTarget = 0;
  unsigned BlockAddressTarget = 0;
  unsigned TargetBlockEntry = 0;
  unsigned TargetBlockSplit = 0;
  unsigned LeadAdjustedSites = 0;
  unsigned MissingTargetFunction = 0;
  unsigned MissingTargetLocation = 0;
  unsigned MissingTargetSymbolOffset = 0;
  unsigned MissingSiteFunction = 0;
  unsigned MissingSiteLocation = 0;
};

static std::string getPlanPath() {
  if (!PrefetchITPlanPath.empty())
    return PrefetchITPlanPath;
  const char *EnvPath = std::getenv("PREFETCHIT_PLAN");
  if (EnvPath && *EnvPath)
    return std::string(EnvPath);
  return PREFETCHIT_DEFAULT_PLAN;
}

static std::string lowerTrim(StringRef Raw) {
  std::string Out = Raw.trim().str();
  std::transform(Out.begin(), Out.end(), Out.begin(),
                 [](unsigned char C) { return static_cast<char>(std::tolower(C)); });
  return Out;
}

static std::optional<std::string> normalizePrefetchMnemonic(StringRef Raw) {
  std::string M = lowerTrim(Raw);
  if (M.empty())
    return DefaultPrefetchMnemonic.str();

  if (M == "t0")
    M = "prefetcht0";
  else if (M == "t1")
    M = "prefetcht1";
  else if (M == "t2")
    M = "prefetcht2";
  else if (M == "nta")
    M = "prefetchnta";
  else if (M == "it0" || M == "prefetchit")
    M = "prefetchit0";
  else if (M == "it1")
    M = "prefetchit1";

  if (M == "prefetcht0" || M == "prefetcht1" || M == "prefetcht2" ||
      M == "prefetchnta" || M == "prefetchit0" || M == "prefetchit1")
    return M;
  return std::nullopt;
}

static std::string getString(const json::Object &Obj, StringRef Key) {
  if (std::optional<StringRef> Value = Obj.getString(Key))
    return Value->str();
  return "";
}

static unsigned getUnsigned(const json::Object &Obj, StringRef Key) {
  if (std::optional<int64_t> Value = Obj.getInteger(Key))
    return *Value > 0 ? static_cast<unsigned>(*Value) : 0;
  return 0;
}

static std::optional<uint64_t> parseUnsignedInteger(StringRef Raw) {
  std::string Text = Raw.trim().str();
  if (Text.empty())
    return std::nullopt;

  unsigned Base = 10;
  StringRef Digits(Text);
  if (Digits.consume_front("0x") || Digits.consume_front("0X"))
    Base = 16;
  uint64_t Value = 0;
  auto Result = std::from_chars(Digits.begin(), Digits.end(), Value, Base);
  if (Result.ec != std::errc() || Result.ptr != Digits.end())
    return std::nullopt;
  return Value;
}

static uint64_t getUInt64(const json::Object &Obj, StringRef Key) {
  if (std::optional<int64_t> Value = Obj.getInteger(Key))
    return *Value > 0 ? static_cast<uint64_t>(*Value) : 0;
  return 0;
}

static double getDouble(const json::Object &Obj, StringRef Key) {
  if (std::optional<double> Value = Obj.getNumber(Key))
    return *Value;
  if (std::optional<int64_t> Value = Obj.getInteger(Key))
    return static_cast<double>(*Value);
  return 0.0;
}

static std::vector<int64_t> getIntegerArray(const json::Object &Obj,
                                            StringRef Key,
                                            ArrayRef<int64_t> DefaultValues) {
  const json::Array *Array = Obj.getArray(Key);
  if (!Array)
    return std::vector<int64_t>(DefaultValues.begin(), DefaultValues.end());

  std::vector<int64_t> Values;
  std::set<int64_t> Seen;
  for (const json::Value &Value : *Array) {
    std::optional<int64_t> MaybeInt = Value.getAsInteger();
    if (!MaybeInt || *MaybeInt < 0)
      continue;
    if (Seen.insert(*MaybeInt).second)
      Values.push_back(*MaybeInt);
  }
  if (Values.empty())
    return std::vector<int64_t>(DefaultValues.begin(), DefaultValues.end());
  return Values;
}

static std::string getNestedString(const json::Object &Obj, StringRef ObjKey,
                                   StringRef ValueKey) {
  if (const json::Object *Nested = Obj.getObject(ObjKey))
    return getString(*Nested, ValueKey);
  return "";
}

static SourceLocSpec parseSourceLoc(const json::Object &Obj) {
  SourceLocSpec Loc;
  Loc.Mangled = getString(Obj, "mangled");
  Loc.Demangled = getString(Obj, "demangled");
  Loc.Function = getString(Obj, "function");
  Loc.File = getString(Obj, "file");
  Loc.Line = getUnsigned(Obj, "line");
  Loc.Column = getUnsigned(Obj, "column");
  Loc.Discriminator = getUnsigned(Obj, "discriminator");
  Loc.Addr = getString(Obj, "addr");
  Loc.SymbolOffset = getString(Obj, "symbol_offset");
  Loc.SymbolType = getString(Obj, "symbol_type");
  Loc.OperandMode = getString(Obj, "operand");
  return Loc;
}

static std::optional<Plan> loadPlan(StringRef Path) {
  ErrorOr<std::unique_ptr<MemoryBuffer>> BufferOrErr =
      MemoryBuffer::getFile(Path);
  if (!BufferOrErr) {
    errs() << "prefetchit-inject: failed to read plan " << Path << ": "
           << BufferOrErr.getError().message() << "\n";
    return std::nullopt;
  }

  Expected<json::Value> Parsed =
      json::parse(BufferOrErr.get()->getBuffer());
  if (!Parsed) {
    errs() << "prefetchit-inject: failed to parse plan " << Path << ": "
           << toString(Parsed.takeError()) << "\n";
    return std::nullopt;
  }

  json::Object *Root = Parsed->getAsObject();
  if (!Root) {
    errs() << "prefetchit-inject: plan root must be a JSON object\n";
    return std::nullopt;
  }

  std::string Schema = getString(*Root, "schema");
  if (Schema != "prefetchit.plan.v1") {
    errs() << "prefetchit-inject: unsupported plan schema '" << Schema
           << "'\n";
    return std::nullopt;
  }

  json::Array *Injections = Root->getArray("injections");
  if (!Injections) {
    errs() << "prefetchit-inject: plan is missing injections array\n";
    return std::nullopt;
  }

  Plan Loaded;
  std::string RootMnemonic = getString(*Root, "prefetch_mnemonic");
  if (RootMnemonic.empty())
    RootMnemonic = getNestedString(*Root, "prefetch", "mnemonic");
  std::optional<std::string> NormalizedRootMnemonic =
      normalizePrefetchMnemonic(RootMnemonic);
  if (!NormalizedRootMnemonic) {
    errs() << "prefetchit-inject: unsupported plan prefetch mnemonic '"
           << RootMnemonic << "'\n";
    return std::nullopt;
  }
  Loaded.DefaultMnemonic = *NormalizedRootMnemonic;
  if (const json::Object *PrefetchObj = Root->getObject("prefetch")) {
    Loaded.ByteOffsets = getIntegerArray(*PrefetchObj, "byte_offsets", {0});
    Loaded.LeadInstructions = getUnsigned(*PrefetchObj, "lead_instructions");
    std::string Operand = getString(*PrefetchObj, "operand");
    if (!Operand.empty())
      Loaded.OperandMode = Operand;
  }

  for (const json::Value &Value : *Injections) {
    const json::Object *Obj = Value.getAsObject();
    if (!Obj)
      continue;
    const json::Object *Target = Obj->getObject("target");
    const json::Object *Site = Obj->getObject("site");
    if (!Target || !Site)
      continue;

    InjectionSpec Spec;
    Spec.Index = static_cast<unsigned>(Loaded.Injections.size());
    std::string SpecMnemonic = getString(*Obj, "prefetch_mnemonic");
    if (SpecMnemonic.empty())
      SpecMnemonic = getNestedString(*Obj, "prefetch", "mnemonic");
    if (!SpecMnemonic.empty()) {
      std::optional<std::string> NormalizedSpecMnemonic =
          normalizePrefetchMnemonic(SpecMnemonic);
      if (!NormalizedSpecMnemonic) {
        errs() << "prefetchit-inject: unsupported injection prefetch mnemonic '"
               << SpecMnemonic << "'\n";
        return std::nullopt;
      }
      Spec.Mnemonic = *NormalizedSpecMnemonic;
    }
    if (const json::Object *PrefetchObj = Obj->getObject("prefetch"))
      Spec.ByteOffsets = getIntegerArray(*PrefetchObj, "byte_offsets", {});
    Spec.TargetRank = getUnsigned(*Obj, "target_rank");
    Spec.SiteRank = getUnsigned(*Obj, "site_rank");
    Spec.Samples = getUInt64(*Obj, "samples");
    Spec.NewCoveredSamples = getUInt64(*Obj, "new_covered_samples");
    Spec.CumulativeCoveragePct = getDouble(*Obj, "cumulative_coverage_pct");
    Spec.BranchType = getString(*Site, "branch_type");
    Spec.LBRDepth = getUnsigned(*Site, "lbr_depth");
    Spec.Target = parseSourceLoc(*Target);
    Spec.Site = parseSourceLoc(*Site);
    Loaded.Injections.push_back(std::move(Spec));
  }

  return Loaded;
}

static std::string stripArgs(StringRef Name) {
  StringRef Base = Name.split('(').first;
  return Base.trim().str();
}

static std::string normalizePath(StringRef Path) {
  std::string Out = Path.str();
  std::replace(Out.begin(), Out.end(), '\\', '/');
  std::string Needle = "/./";
  size_t Pos = 0;
  while ((Pos = Out.find(Needle, Pos)) != std::string::npos)
    Out.replace(Pos, Needle.size(), "/");
  return Out;
}

static bool pathMatches(StringRef ActualRaw, StringRef WantedRaw) {
  if (WantedRaw.empty() || WantedRaw.starts_with("<"))
    return true;

  std::string Actual = normalizePath(ActualRaw);
  std::string Wanted = normalizePath(WantedRaw);
  if (Actual == Wanted)
    return true;

  StringRef GeneratedNeedle = "/generated-src/";
  StringRef ActualRef(Actual);
  StringRef WantedRef(Wanted);
  if (ActualRef.contains(GeneratedNeedle) && WantedRef.contains(GeneratedNeedle)) {
    StringRef ActualGenerated = ActualRef.split(GeneratedNeedle).second;
    StringRef WantedGenerated = WantedRef.split(GeneratedNeedle).second;
    if (ActualGenerated == WantedGenerated)
      return true;
  }

  std::string ActualSuffix = "/" + Actual;
  std::string WantedSuffix = "/" + Wanted;
  if (StringRef(ActualSuffix).ends_with(WantedSuffix) ||
      StringRef(WantedSuffix).ends_with(ActualSuffix))
    return true;

  return sys::path::filename(Actual) == sys::path::filename(Wanted);
}

static std::string debugPath(const DILocation &Loc) {
  StringRef File = Loc.getFilename();
  StringRef Dir = Loc.getDirectory();
  if (File.empty())
    return "";
  if (sys::path::is_absolute(File) || Dir.empty())
    return File.str();
  SmallString<256> Path(Dir);
  sys::path::append(Path, File);
  return std::string(Path);
}

static bool debugLocMatches(const DebugLoc &DL, const SourceLocSpec &Spec) {
  if (!DL || Spec.Line == 0)
    return false;

  for (const DILocation *Loc = DL.get(); Loc; Loc = Loc->getInlinedAt()) {
    if (Loc->getLine() != Spec.Line)
      continue;
    if (Spec.Column != 0 && Loc->getColumn() != Spec.Column)
      continue;
    if (Spec.Discriminator != 0 &&
        Loc->getDiscriminator() != Spec.Discriminator)
      continue;
    if (pathMatches(debugPath(*Loc), Spec.File))
      return true;
  }
  return false;
}

static Function *findFunction(Module &M, const SourceLocSpec &Spec) {
  if (!Spec.Mangled.empty()) {
    if (Function *F = M.getFunction(Spec.Mangled))
      return F;
  }

  std::vector<std::string> Candidates;
  if (!Spec.Function.empty())
    Candidates.push_back(Spec.Function);
  if (!Spec.Demangled.empty())
    Candidates.push_back(Spec.Demangled);
  if (!Spec.Mangled.empty())
    Candidates.push_back(Spec.Mangled);

  for (std::string &Candidate : Candidates)
    Candidate = stripArgs(Candidate);

  for (Function &F : M) {
    if (F.isDeclaration())
      continue;
    StringRef Name = F.getName();
    for (const std::string &Candidate : Candidates) {
      if (!Candidate.empty() && Name == Candidate)
        return &F;
    }
  }
  return nullptr;
}

static bool isIgnorableInstruction(const Instruction &I) {
  return isa<PHINode>(I) || isa<LandingPadInst>(I) ||
         isa<CatchPadInst>(I) || isa<CleanupPadInst>(I) ||
         isa<DbgInfoIntrinsic>(I);
}

static bool isPreferredSiteInstruction(const Instruction &I,
                                       StringRef BranchType) {
  if (BranchType.contains("CALL"))
    return isa<CallBase>(I) && !isa<DbgInfoIntrinsic>(I);
  if (BranchType == "RET")
    return isa<ReturnInst>(I);
  if (BranchType == "COND") {
    if (const auto *BI = dyn_cast<BranchInst>(&I))
      return BI->isConditional();
    return isa<SwitchInst>(I);
  }
  if (BranchType == "UNCOND") {
    if (const auto *BI = dyn_cast<BranchInst>(&I))
      return BI->isUnconditional();
    return false;
  }
  if (BranchType == "IND")
    return isa<IndirectBrInst>(I) || isa<CallBase>(I);
  return I.isTerminator() || isa<CallBase>(I);
}

struct FunctionDebugIndex {
  std::map<unsigned, std::vector<Instruction *>> ByLine;
};

static FunctionDebugIndex &
getFunctionDebugIndex(Function &F,
                      std::map<Function *, FunctionDebugIndex> &Cache) {
  auto It = Cache.find(&F);
  if (It != Cache.end())
    return It->second;

  FunctionDebugIndex Index;
  for (Instruction &I : instructions(F)) {
    if (isIgnorableInstruction(I))
      continue;
    DebugLoc DL = I.getDebugLoc();
    if (!DL)
      continue;
    std::set<unsigned> SeenLinesForInstruction;
    for (const DILocation *Loc = DL.get(); Loc; Loc = Loc->getInlinedAt()) {
      unsigned Line = Loc->getLine();
      if (Line == 0 || !SeenLinesForInstruction.insert(Line).second)
        continue;
      Index.ByLine[Line].push_back(&I);
    }
  }

  return Cache.emplace(&F, std::move(Index)).first->second;
}

static Instruction *findInstructionAtLocation(Function &F,
                                              const SourceLocSpec &Spec,
                                              std::map<Function *, FunctionDebugIndex>
                                                  &DebugIndexCache) {
  if (Spec.Line == 0)
    return nullptr;
  FunctionDebugIndex &Index = getFunctionDebugIndex(F, DebugIndexCache);
  auto It = Index.ByLine.find(Spec.Line);
  if (It == Index.ByLine.end())
    return nullptr;
  for (Instruction *I : It->second)
    if (debugLocMatches(I->getDebugLoc(), Spec))
      return I;
  return nullptr;
}

static Instruction *findSiteInstruction(Function &F, const InjectionSpec &Spec) {
  std::vector<Instruction *> Matches;
  std::vector<Instruction *> Fallbacks;
  for (Instruction &I : instructions(F)) {
    if (isIgnorableInstruction(I))
      continue;
    if (!debugLocMatches(I.getDebugLoc(), Spec.Site))
      continue;
    Fallbacks.push_back(&I);
    if (isPreferredSiteInstruction(I, Spec.BranchType))
      Matches.push_back(&I);
  }
  if (!Matches.empty())
    return Matches.front();
  if (!Fallbacks.empty())
    return Fallbacks.front();
  return nullptr;
}

static std::vector<Instruction *>
findSiteInstructions(Function &F, const InjectionSpec &Spec,
                     std::map<Function *, FunctionDebugIndex>
                         &DebugIndexCache) {
  std::vector<Instruction *> Preferred;
  std::vector<Instruction *> Fallbacks;
  if (Spec.Site.Line == 0)
    return Fallbacks;
  FunctionDebugIndex &Index = getFunctionDebugIndex(F, DebugIndexCache);
  auto It = Index.ByLine.find(Spec.Site.Line);
  if (It == Index.ByLine.end())
    return Fallbacks;
  for (Instruction *I : It->second) {
    if (!debugLocMatches(I->getDebugLoc(), Spec.Site))
      continue;
    Fallbacks.push_back(I);
    if (isPreferredSiteInstruction(*I, Spec.BranchType))
      Preferred.push_back(I);
  }
  return Preferred.empty() ? Fallbacks : Preferred;
}

static Instruction *firstAnchorableInstruction(BasicBlock &BB) {
  for (Instruction &I : BB) {
    if (!isIgnorableInstruction(I))
      return &I;
  }
  return BB.getTerminator();
}

struct TargetBlockResult {
  BasicBlock *BB = nullptr;
  bool Split = false;
};

static TargetBlockResult ensureTargetBlock(Instruction &TargetI) {
  BasicBlock *BB = TargetI.getParent();
  if (firstAnchorableInstruction(*BB) == &TargetI) {
    if (!BB->hasName())
      BB->setName("prefetchit.target");
    return {BB, false};
  }
  BasicBlock *TargetBB =
      BB->splitBasicBlock(TargetI.getIterator(), "prefetchit.target");
  if (!TargetBB->hasName())
    TargetBB->setName("prefetchit.target");
  return {TargetBB, true};
}

static std::string targetKey(const SourceLocSpec &Spec) {
  return Spec.Mangled + "\n" + Spec.Function + "\n" + normalizePath(Spec.File) +
         "\n" + std::to_string(Spec.Line) + "\n" + Spec.Addr + "\n" +
         Spec.OperandMode;
}

// All plan sites that resolve to the same debug location; the pass maps them
// onto the IR candidates in baseline-address order (IR order follows layout in
// generated code), instead of piling every site of a line onto candidate 0.
static std::string siteLocationKey(const InjectionSpec &Spec) {
  return Spec.Site.Mangled + "\n" + normalizePath(Spec.Site.File) + "\n" +
         std::to_string(Spec.Site.Line) + "\n" + Spec.BranchType;
}

static std::string siteKey(const InjectionSpec &Spec) {
  return Spec.Site.Mangled + "\n" + Spec.Site.Function + "\n" +
         normalizePath(Spec.Site.File) + "\n" + std::to_string(Spec.Site.Line) +
         "\n" + Spec.Site.Addr + "\n" + Spec.BranchType;
}

static std::string escapeInlineAsmSymbol(StringRef Symbol) {
  std::string Out;
  Out.reserve(Symbol.size());
  for (char C : Symbol) {
    if (C == '$')
      Out += "$$";
    else
      Out += C;
  }
  return Out;
}

static Instruction *moveInsertionEarlier(Instruction &SiteI,
                                         unsigned LeadInstructions) {
  if (LeadInstructions == 0)
    return &SiteI;

  BasicBlock &BB = *SiteI.getParent();
  BasicBlock::iterator First = BB.getFirstInsertionPt();
  BasicBlock::iterator It = SiteI.getIterator();
  if (First == BB.end() || It == First)
    return &SiteI;

  unsigned Moved = 0;
  while (It != First && Moved < LeadInstructions) {
    --It;
    if (!isa<DbgInfoIntrinsic>(&*It))
      ++Moved;
  }
  return &*It;
}

static void insertPrefetchBeforeBlockAddress(Module &M, Instruction &SiteI,
                                             Function &TargetF,
                                             BasicBlock &TargetBB,
                                             StringRef Mnemonic,
                                             int64_t ByteOffset) {
  LLVMContext &Ctx = M.getContext();
  PointerType *PtrTy = PointerType::getUnqual(Ctx);
  FunctionType *AsmTy =
      FunctionType::get(Type::getVoidTy(Ctx), {PtrTy}, false);
  std::string AsmString = Mnemonic.str() + " ${0:c}";
  if (ByteOffset > 0)
    AsmString += "+" + std::to_string(ByteOffset);
  AsmString += "(%rip)";
  // Keep the prefetch as volatile inline asm so it is not deleted, but do not
  // claim a memory clobber. A prefetch has no architectural memory side effect;
  // marking it as a full memory barrier can add scheduling/optimization cost
  // that easily hides any frontend-cache benefit we are trying to measure.
  InlineAsm *Asm = InlineAsm::get(AsmTy, AsmString, "i", true);
  BlockAddress *TargetAddr = BlockAddress::get(&TargetF, &TargetBB);
  CallInst *CI = CallInst::Create(Asm, {TargetAddr}, "", &SiteI);
  CI->setDebugLoc(SiteI.getDebugLoc());
}

// Encoded size of one injected rip-relative prefetch: 0F 18 /r disp32.
static constexpr uint64_t RipRelativePrefetchBytes = 7;

// One planned prefetch whose emission is deferred until every site in the
// module is resolved, so that same-function layout shifts can be computed.
struct PendingPrefetch {
  unsigned Index = 0;
  Instruction *InsertionI = nullptr;
  Function *TargetF = nullptr;
  BasicBlock *TargetBB = nullptr;
  SourceLocSpec Target;
  SourceLocSpec Site;
  std::string Mnemonic;
  int64_t ByteOffset = 0;
  enum Mode { SymbolOffset, GotSymbolOffset, BlockAddress } Mode = SymbolOffset;
};

static bool insertPrefetchBeforeSymbolOffset(Module &M, Instruction &SiteI,
                                             const SourceLocSpec &Target,
                                             StringRef Mnemonic,
                                             int64_t ByteOffset,
                                             uint64_t LayoutShift = 0) {
  if (Target.Mangled.empty())
    return false;
  std::optional<uint64_t> BaseOffset = parseUnsignedInteger(Target.SymbolOffset);
  if (!BaseOffset)
    return false;

  LLVMContext &Ctx = M.getContext();
  FunctionType *AsmTy = FunctionType::get(Type::getVoidTy(Ctx), {}, false);
  uint64_t TotalOffset =
      *BaseOffset + static_cast<uint64_t>(ByteOffset) + LayoutShift;
  std::string Symbol = escapeInlineAsmSymbol(Target.Mangled);
  std::string AsmString = Mnemonic.str() + " " + Symbol + "+0x" +
                          utohexstr(TotalOffset) + "(%rip)";
  InlineAsm *Asm = InlineAsm::get(AsmTy, AsmString, "", true);
  CallInst *CI = CallInst::Create(Asm, {}, "", &SiteI);
  CI->setDebugLoc(SiteI.getDebugLoc());
  return true;
}

static bool insertPrefetchBeforeGotSymbolOffset(Module &M, Instruction &SiteI,
                                                const SourceLocSpec &Target,
                                                StringRef Mnemonic,
                                                int64_t ByteOffset) {
  if (Target.Mangled.empty())
    return false;
  std::optional<uint64_t> BaseOffset = parseUnsignedInteger(Target.SymbolOffset);
  if (!BaseOffset)
    return false;

  LLVMContext &Ctx = M.getContext();
  FunctionType *AsmTy = FunctionType::get(Type::getVoidTy(Ctx), {}, false);
  uint64_t TotalOffset = *BaseOffset + static_cast<uint64_t>(ByteOffset);

  std::string Symbol = escapeInlineAsmSymbol(Target.Mangled);
  std::string AsmString = "movq " + Symbol + "@GOTPCREL(%rip), %r11\n\t";
  AsmString += Mnemonic.str() + " ";
  if (TotalOffset > 0)
    AsmString += "0x" + utohexstr(TotalOffset);
  AsmString += "(%r11)";

  InlineAsm *Asm = InlineAsm::get(AsmTy, AsmString, "~{r11}", true);
  CallInst *CI = CallInst::Create(Asm, {}, "", &SiteI);
  CI->setDebugLoc(SiteI.getDebugLoc());
  return true;
}

static std::string envOr(const char *Name, const std::string &Flag) {
  if (!Flag.empty())
    return Flag;
  const char *V = std::getenv(Name);
  return (V && *V) ? std::string(V) : std::string();
}

static unsigned envOrU(const char *Name, unsigned Flag, unsigned Default) {
  if (Flag)
    return Flag;
  const char *V = std::getenv(Name);
  if (V && *V) {
    if (std::optional<uint64_t> Parsed = parseUnsignedInteger(V))
      return static_cast<unsigned>(*Parsed);
  }
  return Default;
}


// Plan-free "cold-path" mode for short-run (wake-bound) services: at every
// selected function's entry, prefetch (a) the function's own later cache lines,
// (b) the entry line(s) of direct callees reached outside loops, (c) the entry
// line of external (declared) callees through their GOT slot. One site per
// function invocation, never inside a loop.
static cl::opt<unsigned> PrefetchITColdOwnLines(
    "prefetchit-cold-own-lines",
    cl::desc("cold-path: max own-function lines prefetched at entry (0 = mode off); env PREFETCHIT_COLD_OWN_LINES"),
    cl::init(0));
static cl::opt<unsigned> PrefetchITColdCalleeLines(
    "prefetchit-cold-callee-lines",
    cl::desc("cold-path: entry lines per callee (env PREFETCHIT_COLD_CALLEE_LINES)"), cl::init(0));
static cl::opt<unsigned> PrefetchITColdMaxCallees(
    "prefetchit-cold-max-callees",
    cl::desc("cold-path: max direct callees per function (env PREFETCHIT_COLD_MAX_CALLEES)"), cl::init(0));
static cl::opt<unsigned> PrefetchITColdMaxExternal(
    "prefetchit-cold-max-external",
    cl::desc("cold-path: max external (GOT) callees per function (env PREFETCHIT_COLD_MAX_EXTERNAL)"), cl::init(0));
static cl::opt<unsigned> PrefetchITColdMinInsns(
    "prefetchit-cold-min-insns",
    cl::desc("cold-path: skip functions with fewer IR instructions (env PREFETCHIT_COLD_MIN_INSNS)"), cl::init(0));
static cl::opt<unsigned> PrefetchITColdMinCalleeInsns(
    "prefetchit-cold-min-callee-insns",
    cl::desc("cold-path: skip defined callees smaller than this (env PREFETCHIT_COLD_MIN_CALLEE_INSNS)"), cl::init(0));
static cl::opt<unsigned> PrefetchITColdBytesPerInsn(
    "prefetchit-cold-bytes-per-insn",
    cl::desc("cold-path: estimated machine bytes per IR instruction (env PREFETCHIT_COLD_BYTES_PER_INSN)"), cl::init(0));

struct SeqConfig {
  unsigned Distance = 0;   // bytes ahead
  unsigned Stride = 14;    // IR instructions between sites
  unsigned Lines = 1;      // consecutive cachelines per site
  unsigned MinInsns = 0;
  unsigned BurstLines = 0;   // callee-entry burst lines (0 = off)
  unsigned BurstLead = 0;    // IR instructions before the call
  unsigned BurstMinCalleeInsns = 0;
  std::string Include;
  std::string Exclude;
  std::string FunctionsFile;
  std::set<std::string> Listed;   // from FunctionsFile (empty = no list)
  std::string Mnemonic = DefaultPrefetchMnemonic.str();
  unsigned ColdOwnLines = 0, ColdCalleeLines = 1, ColdMaxCallees = 8, ColdMaxExternal = 8;
  unsigned ColdMinInsns = 24, ColdMinCalleeInsns = 8, ColdBytesPerInsn = 5;
  std::set<std::string> ColdDirectSyms;   // declared callees that the final link resolves in-image (pc-relative)
  bool ColdExternalGot = true;            // unlisted declared callees: GOT-indirect prefetch (false = skip)
  bool ColdDirectInPIC = false;           // allow pc-relative references to declared callees in shared-object modules
  bool coldEnabled() const { return ColdOwnLines > 0 || ColdCalleeLines > 0 && std::getenv("PREFETCHIT_COLD"); }
  bool enabled() const { return Distance > 0 || BurstLines > 0 || coldEnabled(); }
  bool selects(StringRef Name, const std::optional<Regex> &Inc,
               const std::optional<Regex> &Exc) const {
    if (!FunctionsFile.empty() && !Listed.count(Name.str()))
      return false;
    if (Inc && !Inc->match(Name))
      return false;
    if (Exc && Exc->match(Name))
      return false;
    return true;
  }
};

static SeqConfig getSeqConfig() {
  SeqConfig C;
  C.Distance = envOrU("PREFETCHIT_SEQ_DISTANCE", PrefetchITSeqDistance, 0);
  C.Stride = std::max(1u, envOrU("PREFETCHIT_SEQ_STRIDE_INSNS",
                                 PrefetchITSeqStrideInsns, 14));
  C.Lines = std::max(1u, envOrU("PREFETCHIT_SEQ_LINES", PrefetchITSeqLines, 1));
  C.MinInsns = envOrU("PREFETCHIT_SEQ_MIN_INSNS", PrefetchITSeqMinInsns, 0);
  C.BurstLines = envOrU("PREFETCHIT_CALLEE_BURST_LINES", PrefetchITCalleeBurstLines, 0);
  C.BurstLead = envOrU("PREFETCHIT_CALLEE_BURST_LEAD", PrefetchITCalleeBurstLead, 0);
  C.BurstMinCalleeInsns = envOrU("PREFETCHIT_CALLEE_BURST_MIN_CALLEE_INSNS",
                                 PrefetchITCalleeBurstMinCalleeInsns, 0);
  C.ColdOwnLines = envOrU("PREFETCHIT_COLD_OWN_LINES", PrefetchITColdOwnLines, 0);
  C.ColdCalleeLines = envOrU("PREFETCHIT_COLD_CALLEE_LINES", PrefetchITColdCalleeLines, 1);
  C.ColdMaxCallees = envOrU("PREFETCHIT_COLD_MAX_CALLEES", PrefetchITColdMaxCallees, 8);
  C.ColdMaxExternal = envOrU("PREFETCHIT_COLD_MAX_EXTERNAL", PrefetchITColdMaxExternal, 8);
  C.ColdMinInsns = envOrU("PREFETCHIT_COLD_MIN_INSNS", PrefetchITColdMinInsns, 24);
  C.ColdMinCalleeInsns = envOrU("PREFETCHIT_COLD_MIN_CALLEE_INSNS", PrefetchITColdMinCalleeInsns, 8);
  C.ColdBytesPerInsn = std::max(1u, envOrU("PREFETCHIT_COLD_BYTES_PER_INSN", PrefetchITColdBytesPerInsn, 5));
  if (const char *DS = std::getenv("PREFETCHIT_COLD_DIRECT_SYMS"); DS && *DS) {
    if (auto Buf = MemoryBuffer::getFile(DS)) {
      SmallVector<StringRef, 64> Lines;
      (*Buf)->getBuffer().split(Lines, '\n', -1, false);
      for (StringRef L : Lines)
        if (!L.trim().empty())
          C.ColdDirectSyms.insert(L.trim().str());
    } else {
      errs() << "prefetchit-cold: cannot read PREFETCHIT_COLD_DIRECT_SYMS " << DS << "\n";
    }
  }
  if (const char *EM = std::getenv("PREFETCHIT_COLD_EXTERNAL"); EM && StringRef(EM) == "skip")
    C.ColdExternalGot = false;
  if (const char *DP = std::getenv("PREFETCHIT_COLD_DIRECT_IN_PIC"); DP && *DP && StringRef(DP) != "0")
    C.ColdDirectInPIC = true;
  C.Include = envOr("PREFETCHIT_SEQ_FUNCTIONS", PrefetchITSeqFunctions);
  C.Exclude = envOr("PREFETCHIT_SEQ_EXCLUDE", PrefetchITSeqExclude);
  C.FunctionsFile = envOr("PREFETCHIT_SEQ_FUNCTIONS_FILE", PrefetchITSeqFunctionsFile);
  if (!C.FunctionsFile.empty()) {
    auto Buf = MemoryBuffer::getFile(C.FunctionsFile);
    if (!Buf) {
      errs() << "prefetchit-seq: cannot read functions file " << C.FunctionsFile
             << "\n";
    } else {
      SmallVector<StringRef, 64> Lines;
      (*Buf)->getBuffer().split(Lines, '\n');
      for (StringRef L : Lines) {
        L = L.trim();
        if (!L.empty() && L[0] != '#')
          C.Listed.insert(L.str());
      }
    }
  }
  if (!PrefetchITMnemonicOverride.empty()) {
    if (std::optional<std::string> M =
            normalizePrefetchMnemonic(PrefetchITMnemonicOverride))
      C.Mnemonic = *M;
  } else if (const char *EnvM = std::getenv("PREFETCHIT_SEQ_MNEMONIC")) {
    if (std::optional<std::string> M = normalizePrefetchMnemonic(EnvM))
      C.Mnemonic = *M;
  }
  return C;
}

static bool isSeqInsertionCandidate(const Instruction &I) {
  if (isIgnorableInstruction(I))
    return false;
  if (isa<CatchSwitchInst>(I) || isa<CatchReturnInst>(I) ||
      isa<CleanupReturnInst>(I))
    return false;
  return true;
}

static unsigned countIRInsns(Function &F) {
  unsigned N = 0;
  for (BasicBlock &BB : F)
    for (Instruction &I : BB)
      if (isSeqInsertionCandidate(I))
        ++N;
  return N;
}

// Callee-entry bursts: `prefetcht1 callee+64*l(%rip)` before direct calls.

// Cold-path mode (see the option block above).
// Trace-guided cold-path plan: {"sites": {"<function>": {"k": <burst bytes>, "t": [["sym", off, got], ...]}}}.
// At the entry of every listed function: direct targets → "prefetcht1 sym+off(%rip)" (7 B); GOT targets grouped by anchor →
// "movq anchor@GOTPCREL(%rip),%r11" (7 B) + "prefetcht1 off(%r11)" (4/5/8 B); the burst is padded with .nops to "k" (a multiple of 16)
// so that body offsets shift by exactly k and the plan's offsets (measured on the pass-free layout) stay valid.
static uint64_t runColdPlan(Module &M, const SeqConfig &C, StringRef PlanPath) {
  auto Buf = MemoryBuffer::getFile(PlanPath);
  if (!Buf) {
    errs() << "prefetchit-cold-plan: cannot read " << PlanPath << "\n";
    return 0;
  }
  Expected<json::Value> Parsed = json::parse((*Buf)->getBuffer());
  if (!Parsed) {
    errs() << "prefetchit-cold-plan: bad JSON in " << PlanPath << "\n";
    consumeError(Parsed.takeError());
    return 0;
  }
  const json::Object *Root = Parsed->getAsObject();
  const json::Object *Sites = Root ? Root->getObject("sites") : nullptr;
  if (!Sites) {
    errs() << "prefetchit-cold-plan: no \"sites\" object\n";
    return 0;
  }
  LLVMContext &Ctx = M.getContext();
  FunctionType *AsmTy = FunctionType::get(Type::getVoidTy(Ctx), {}, false);
  bool PICModule = false;
  if (auto *MD = mdconst::extract_or_null<ConstantInt>(M.getModuleFlag("PIC Level")))
    PICModule = MD->getZExtValue() != 0;
  const bool ExeModule = !PICModule || M.getPIELevel() != PIELevel::Default;
  const bool AllowDirect = ExeModule || C.ColdDirectInPIC;
  // Epoch gating: a burst fires only when the global epoch changed since this thread last passed the site (once per request/wake).
  const char *EG = std::getenv("PREFETCHIT_COLD_EPOCH");
  const bool EpochGate = EG && *EG && StringRef(EG) != "0";
  const char *EF = std::getenv("PREFETCHIT_COLD_EPOCH_FN");
  const std::string EpochFn = (EF && *EF) ? std::string(EF) : std::string();
  GlobalVariable *Epoch = nullptr;
  auto epochVar = [&]() {
    if (!Epoch) {
      Epoch = M.getGlobalVariable("__prefetchit_epoch", true);
      if (!Epoch) {
        Epoch = new GlobalVariable(M, Type::getInt32Ty(Ctx), false, GlobalValue::WeakAnyLinkage,
                                   ConstantInt::get(Type::getInt32Ty(Ctx), 0), "__prefetchit_epoch");
        Epoch->setVisibility(GlobalValue::HiddenVisibility);
        Epoch->setDSOLocal(true);
        Epoch->setAlignment(Align(4));
        appendToUsed(M, {Epoch});
      }
    }
    return Epoch;
  };
  uint64_t Funcs = 0, Direct = 0, Got = 0, Pad = 0, SkippedDirect = 0, Gated = 0;
  for (Function &F : M) {
    if (F.isDeclaration())
      continue;
    const json::Object *S = Sites->getObject(F.getName());
    if (!S)
      continue;
    const json::Array *T = S->getArray("t");
    if ((!T || T->empty()) && !(!EpochFn.empty() && F.getName() == EpochFn))
      continue;
    std::vector<std::pair<std::string, int64_t>> DirectT;
    std::map<std::string, std::vector<int64_t>> GotByAnchor;
    for (const json::Value &V : (T ? *T : json::Array())) {
      const json::Array *E = V.getAsArray();
      if (!E || E->size() < 3)
        continue;
      std::optional<StringRef> Sym = (*E)[0].getAsString();
      std::optional<int64_t> Off = (*E)[1].getAsInteger();
      std::optional<int64_t> G = (*E)[2].getAsInteger();
      if (!Sym || !Off || !G)
        continue;
      if (*G || !AllowDirect) {
        // shared-object modules cannot reference other objects pc-relative: use the GOT form for every target
        GotByAnchor[Sym->str()].push_back(*Off);
        if (!*G) ++SkippedDirect;   // counted as "direct target emitted through the GOT"
      } else {
        DirectT.emplace_back(Sym->str(), *Off);
      }
    }
    const bool IsEpochFn = !EpochFn.empty() && F.getName() == EpochFn;
    if (DirectT.empty() && GotByAnchor.empty() && !IsEpochFn)
      continue;
    std::string Asm;
    unsigned Bytes = 0;
    bool UsesR11 = false, UsesR10 = false, Gate = false;
    if (IsEpochFn) {
      epochVar();
      Asm += "incl __prefetchit_epoch(%rip)\n\t";   // ff 05 disp32
      Bytes += 6;
    }
    if (EpochGate && !(DirectT.empty() && GotByAnchor.empty())) {
      epochVar();
      auto *Last = new GlobalVariable(M, Type::getInt32Ty(Ctx), false, GlobalValue::InternalLinkage,
                                      ConstantInt::get(Type::getInt32Ty(Ctx), 0), "prefetchit.last." + F.getName(), nullptr,
                                      AllowDirect ? GlobalValue::LocalExecTLSModel : GlobalValue::InitialExecTLSModel);
      Last->setAlignment(Align(4));
      appendToUsed(M, {Last});   // referenced only from inline asm
      std::string L = escapeInlineAsmSymbol(Last->getName());
      Asm += "movl __prefetchit_epoch(%rip), %r11d\n\t";                       // 44 8b 1d disp32 (7)
      if (AllowDirect) {
        Asm += "cmpl %r11d, %fs:" + L + "@tpoff\n\t";                            // 64 44 39 1c 25 disp32 (9)
        Asm += ".byte 0x0f, 0x84\n\t.long 1f - . - 4\n\t";                    // je rel32 (6)
        Asm += "movl %r11d, %fs:" + L + "@tpoff\n\t";                            // 64 44 89 1c 25 disp32 (9)
        Bytes += 7 + 9 + 6 + 9;
      } else {
        Asm += "movq " + L + "@gottpoff(%rip), %r10\n\t";                        // 4c 8b 15 disp32 (7)
        Asm += "cmpl %r11d, %fs:(%r10)\n\t";                                     // 64 45 39 1a (4)
        Asm += ".byte 0x0f, 0x84\n\t.long 1f - . - 4\n\t";                    // je rel32 (6)
        Asm += "movl %r11d, %fs:(%r10)\n\t";                                     // 64 45 89 1a (4)
        Bytes += 7 + 7 + 4 + 6 + 4;
        UsesR10 = true;
      }
      UsesR11 = true;
      Gate = true;
      ++Gated;
    }
    for (auto &[Sym, Off] : DirectT) {
      Asm += C.Mnemonic + " " + escapeInlineAsmSymbol(Sym) + (Off >= 0 ? "+" : "") + std::to_string(Off) + "(%rip)\n\t";
      Bytes += 7;
      ++Direct;
    }
    for (auto &[Anchor, Offs] : GotByAnchor) {
      Asm += "movq " + escapeInlineAsmSymbol(Anchor) + "@GOTPCREL(%rip), %r11\n\t";
      Bytes += 7;
      UsesR11 = true;
      for (int64_t O : Offs) {
        Asm += C.Mnemonic + " " + std::to_string(O) + "(%r11)\n\t";
        Bytes += (O == 0) ? 4 : (O >= -128 && O < 128) ? 5 : 8;
        ++Got;
      }
    }
    if (Gate)
      Asm += "1:\n\t";
    unsigned K = (Bytes + 15) / 16 * 16;
    if (std::optional<int64_t> PK = S->getInteger("k")) {
      if (*PK >= Bytes)
        K = static_cast<unsigned>(*PK);
      else
        errs() << "prefetchit-cold-plan: " << F.getName() << ": plan k=" << *PK << " < burst bytes " << Bytes << " (offsets drift)\n";
    }
    if (K > Bytes) {
      Asm += ".nops " + std::to_string(K - Bytes) + "\n\t";
      Pad += K - Bytes;
    }
    Asm.erase(Asm.size() - 2);
    Instruction *At = &*F.getEntryBlock().getFirstInsertionPt();
    std::string Constraints = UsesR11 ? "~{r11}" : "";
    if (UsesR10)
      Constraints += ",~{r10}";
    if (Gate || IsEpochFn)
      Constraints += std::string(Constraints.empty() ? "" : ",") + "~{dirflag},~{fpsr},~{flags}";
    CallInst *CI = CallInst::Create(InlineAsm::get(AsmTy, Asm, Constraints, true), {}, "", At);
    CI->setDebugLoc(At->getDebugLoc());
    ++Funcs;
  }
  errs() << "prefetchit-cold-plan: sites=" << Funcs << " gated=" << Gated << " direct=" << Direct << " got=" << Got << " pad_bytes=" << Pad
         << " direct_via_got=" << SkippedDirect << (ExeModule ? " (exe module)" : " (shared-object module)") << "\n";
  return Direct + Got;
}

static uint64_t runColdPath(Module &M, const SeqConfig &C) {
  LLVMContext &Ctx = M.getContext();
  FunctionType *AsmTy = FunctionType::get(Type::getVoidTy(Ctx), {}, false);
  std::optional<Regex> Include, Exclude;
  if (!C.Include.empty())
    Include.emplace(C.Include);
  if (!C.Exclude.empty())
    Exclude.emplace(C.Exclude);
  auto selected = [&](StringRef Name) { return C.selects(Name, Include, Exclude); };
  bool PICModule = false;
  if (auto *MD = mdconst::extract_or_null<ConstantInt>(M.getModuleFlag("PIC Level")))
    PICModule = MD->getZExtValue() != 0;
  std::map<Function *, unsigned> InsnCount;
  auto insnsOf = [&](Function &F) {
    auto It = InsnCount.find(&F);
    if (It == InsnCount.end())
      It = InsnCount.emplace(&F, countIRInsns(F)).first;
    return It->second;
  };
  DenseMap<Function *, std::string> AliasName;
  // symbol usable in a PC-relative operand from inside this module, or "" if none
  // executables (PIE or not) cannot be interposed: every symbol they define, and every symbol the
  // link resolves from a static archive, is addressable pc-relative without an alias or the GOT
  const bool ExeModule = !PICModule || M.getPIELevel() != PIELevel::Default;
  auto ripSymbol = [&](Function *G, bool Own) -> std::string {
    if (G->isDeclaration())   // listed direct symbol resolved by the final link
      return (ExeModule || C.ColdDirectInPIC) ? escapeInlineAsmSymbol(G->getName()) : "";
    if (G->hasLocalLinkage() || !PICModule || ExeModule || C.ColdDirectInPIC)
      return escapeInlineAsmSymbol(G->getName());   // static-only archive objects: the final link is an executable
    if (G->isWeakForLinker() && !Own)
      return "";   // an alias would point into a possibly discarded COMDAT section
    auto It = AliasName.find(G);
    if (It == AliasName.end()) {
      auto *GA = GlobalAlias::create(G->getValueType(), 0, GlobalValue::InternalLinkage,
                                     "prefetchit.cold." + G->getName(), G, &M);
      appendToUsed(M, {GA});
      It = AliasName.try_emplace(G, GA->getName().str()).first;
    }
    return escapeInlineAsmSymbol(It->second);
  };
  uint64_t Funcs = 0, OwnInj = 0, DirectInj = 0, ExtDirectInj = 0, ExtInj = 0;
  std::vector<Function *> Work;
  for (Function &F : M)
    if (!F.isDeclaration() && selected(F.getName()))
      Work.push_back(&F);
  for (Function *FP : Work) {
    Function &F = *FP;
    unsigned Insns = insnsOf(F);
    if (Insns < C.ColdMinInsns)
      continue;
    DominatorTree DT(F);
    LoopInfo LI(DT);
    // callees reached outside loops, in block order (≈ execution order), deduplicated
    std::vector<Function *> Direct, External;
    std::set<Function *> Seen;
    for (BasicBlock &BB : F) {
      if (LI.getLoopFor(&BB))
        continue;
      for (Instruction &I : BB) {
        auto *CB = dyn_cast<CallBase>(&I);
        if (!CB || isa<IntrinsicInst>(CB) || CB->isInlineAsm())
          continue;
        Function *Callee = CB->getCalledFunction();
        if (!Callee || Callee == &F || Callee->isIntrinsic() || !Seen.insert(Callee).second)
          continue;
        if (Callee->isDeclaration()) {
          if (C.ColdDirectSyms.count(Callee->getName().str())) {
            if (Direct.size() < C.ColdMaxCallees)
              Direct.push_back(Callee);
          } else if (C.ColdExternalGot && External.size() < C.ColdMaxExternal) {
            External.push_back(Callee);
          }
        } else if (Direct.size() < C.ColdMaxCallees && insnsOf(*Callee) >= C.ColdMinCalleeInsns) {
          Direct.push_back(Callee);
        }
      }
    }
    unsigned EstLines = (Insns * C.ColdBytesPerInsn) / 64;
    unsigned Own = std::min(C.ColdOwnLines, EstLines);
    Instruction *At = &*F.getEntryBlock().getFirstInsertionPt();
    auto emit = [&](const std::string &AsmString, const std::string &Constraints) {
      CallInst *CI = CallInst::Create(InlineAsm::get(AsmTy, AsmString, Constraints, true), {}, "", At);
      CI->setDebugLoc(At->getDebugLoc());
    };
    std::string OwnSym = Own ? ripSymbol(&F, true) : "";
    for (unsigned L = 1; L <= Own && !OwnSym.empty(); ++L) {
      emit(C.Mnemonic + " " + OwnSym + "+" + std::to_string(64u * L) + "(%rip)", "");
      ++OwnInj;
    }
    for (Function *G : Direct) {
      std::string Sym = ripSymbol(G, false);
      if (Sym.empty())
        continue;
      for (unsigned L = 0; L < C.ColdCalleeLines; ++L) {
        emit(C.Mnemonic + " " + Sym + "+" + std::to_string(64u * L) + "(%rip)", "");
        if (G->isDeclaration()) ++ExtDirectInj; else ++DirectInj;
      }
    }
    for (Function *G : External) {
      // r11 is a caller-saved scratch register; at function entry nothing lives in it
      std::string Sym = escapeInlineAsmSymbol(G->getName());
      std::string Asm = "movq " + Sym + "@GOTPCREL(%rip), %r11";
      for (unsigned L = 0; L < C.ColdCalleeLines; ++L)
        Asm += "\n\t" + C.Mnemonic + " " + std::to_string(64u * L) + "(%r11)";
      emit(Asm, "~{r11}");
      ExtInj += C.ColdCalleeLines;
    }
    ++Funcs;
  }
  errs() << "prefetchit-cold: own_lines<=" << C.ColdOwnLines << " callee_lines=" << C.ColdCalleeLines
         << " max_callees=" << C.ColdMaxCallees << " max_external=" << C.ColdMaxExternal
         << " min_insns=" << C.ColdMinInsns << " functions=" << Funcs << " own=" << OwnInj
         << " direct=" << DirectInj << " listed_direct=" << ExtDirectInj << " external_got=" << ExtInj
         << (ExeModule ? " (exe module)" : " (shared-object module)") << "\n";
  return OwnInj + DirectInj + ExtDirectInj + ExtInj;
}

static uint64_t runCalleeEntryBurst(Module &M, const SeqConfig &C) {
  LLVMContext &Ctx = M.getContext();
  FunctionType *AsmTy = FunctionType::get(Type::getVoidTy(Ctx), {}, false);
  std::optional<Regex> Include, Exclude;
  if (!C.Include.empty())
    Include.emplace(C.Include);
  if (!C.Exclude.empty())
    Exclude.emplace(C.Exclude);
  auto selected = [&](StringRef Name) { return C.selects(Name, Include, Exclude); };
  std::map<Function *, unsigned> InsnCount;
  uint64_t Calls = 0, Injected = 0;
  for (Function &F : M) {
    if (F.isDeclaration() || !selected(F.getName()))
      continue;
    // collect first, then insert (do not mutate while iterating instructions)
    std::vector<std::pair<CallBase *, Function *>> Sites;
    for (BasicBlock &BB : F)
      for (Instruction &I : BB) {
        auto *CB = dyn_cast<CallBase>(&I);
        if (!CB || isa<IntrinsicInst>(CB) || CB->isInlineAsm())
          continue;
        Function *Callee = CB->getCalledFunction();
        if (!Callee || Callee->isDeclaration() || !selected(Callee->getName()))
          continue;
        if (C.BurstMinCalleeInsns) {
          auto It = InsnCount.find(Callee);
          if (It == InsnCount.end())
            It = InsnCount.emplace(Callee, countIRInsns(*Callee)).first;
          if (It->second < C.BurstMinCalleeInsns)
            continue;
        }
        Sites.emplace_back(CB, Callee);
      }
    // Reference non-local callees through a private alias so the emitted
    // PC-relative operand binds to this module's definition at assembly time.
    // A direct reference to a preemptible (default-visibility) symbol would
    // need an R_X86_64_PC32 dynamic relocation, which the linker rejects when
    // building a shared object.
    DenseMap<Function *, std::string> AliasName;
    bool PICModule = false;
    if (auto *MD = mdconst::extract_or_null<ConstantInt>(M.getModuleFlag("PIC Level")))
      PICModule = MD->getZExtValue() != 0;
    for (auto &[CB, Callee] : Sites) {
      Instruction *At = moveInsertionEarlier(*CB, C.BurstLead);
      std::string Symbol;
      if (Callee->hasLocalLinkage() || !PICModule) {
        // local symbol, or non-PIC code: a direct PC-relative reference links fine
        // (COMDAT callees resolve to the linker-kept copy).
        Symbol = escapeInlineAsmSymbol(Callee->getName());
      } else if (Callee->isWeakForLinker()) {
        // PIC + COMDAT/weak callee: an alias would point into a section the linker may
        // discard, and a direct reference needs a dynamic PC32 reloc -> skip this site.
        continue;
      } else {
        auto It = AliasName.find(Callee);
        if (It == AliasName.end()) {
          auto *GA = GlobalAlias::create(Callee->getValueType(), 0,
                                         GlobalValue::InternalLinkage,
                                         "prefetchit.burst." + Callee->getName(),
                                         Callee, &M);
          appendToUsed(M, {GA});  // referenced only from inline asm text
          It = AliasName.try_emplace(Callee, GA->getName().str()).first;
        }
        Symbol = escapeInlineAsmSymbol(It->second);
      }
      for (unsigned L = 0; L < C.BurstLines; ++L) {
        std::string AsmString = C.Mnemonic + " " + Symbol + "+" +
                                std::to_string(64u * L) + "(%rip)";
        CallInst *CI = CallInst::Create(InlineAsm::get(AsmTy, AsmString, "", true),
                                        {}, "", At);
        CI->setDebugLoc(At->getDebugLoc());
        ++Injected;
      }
      ++Calls;
    }
  }
  errs() << "prefetchit-callee-burst: lines=" << C.BurstLines << " lead_insns="
         << C.BurstLead << " min_callee_insns=" << C.BurstMinCalleeInsns
         << " calls=" << Calls << " injected=" << Injected << "\n";
  return Injected;
}

// Insert `prefetcht1 D(%rip)` (and D+64, ...) before every K-th instruction of
// the selected functions. Returns the number of prefetches injected.
static uint64_t runSequentialLookahead(Module &M, const SeqConfig &C) {
  LLVMContext &Ctx = M.getContext();
  FunctionType *AsmTy = FunctionType::get(Type::getVoidTy(Ctx), {}, false);
  std::vector<InlineAsm *> Asms;
  for (unsigned L = 0; L < C.Lines; ++L) {
    std::string AsmString = C.Mnemonic + " " +
                            std::to_string(static_cast<uint64_t>(C.Distance) +
                                           64ull * L) +
                            "(%rip)";
    Asms.push_back(InlineAsm::get(AsmTy, AsmString, "", true));
  }
  std::optional<Regex> Include, Exclude;
  if (!C.Include.empty())
    Include.emplace(C.Include);
  if (!C.Exclude.empty())
    Exclude.emplace(C.Exclude);

  uint64_t Functions = 0, Insns = 0, Injected = 0, Sites = 0;
  for (Function &F : M) {
    if (F.isDeclaration())
      continue;
    if (!C.selects(F.getName(), Include, Exclude))
      continue;
    unsigned Count = 0;
    std::vector<Instruction *> Sites_;
    for (BasicBlock &BB : F) {
      for (Instruction &I : BB) {
        if (!isSeqInsertionCandidate(I))
          continue;
        ++Count;
        if (Count % C.Stride == 0)
          Sites_.push_back(&I);
      }
    }
    if (Count < C.MinInsns)
      continue;
    ++Functions;
    Insns += Count;
    for (Instruction *I : Sites_) {
      for (InlineAsm *A : Asms) {
        CallInst *CI = CallInst::Create(A, {}, "", I);
        CI->setDebugLoc(I->getDebugLoc());
        ++Injected;
      }
      ++Sites;
    }
  }
  errs() << "prefetchit-seq: distance=" << C.Distance << " stride_insns="
         << C.Stride << " lines=" << C.Lines << " mnemonic=" << C.Mnemonic
         << " include='" << C.Include << "' exclude='" << C.Exclude
         << "' functions_file='" << C.FunctionsFile << "' listed=" << C.Listed.size()
         << " functions=" << Functions << " ir_insns=" << Insns
         << " sites=" << Sites << " injected=" << Injected << "\n";
  return Injected;
}

class PrefetchITPass : public PassInfoMixin<PrefetchITPass> {
public:
  PreservedAnalyses run(Module &M, ModuleAnalysisManager &) {
    bool SkipPIC = PrefetchITSkipPICModules;
    if (const char *E = std::getenv("PREFETCHIT_SKIP_PIC"))
      SkipPIC = SkipPIC || (E[0] == '1');
    if (SkipPIC) {
      auto flagVal = [&](const char *Name) -> uint64_t {
        if (auto *V = mdconst::extract_or_null<ConstantInt>(M.getModuleFlag(Name)))
          return V->getZExtValue();
        return 0;
      };
      if (flagVal("PIC Level") == 2 && flagVal("PIE Level") == 0) {
        errs() << "prefetchit-inject: skipping PIC (shared-library) module "
               << M.getName() << "\n";
        return PreservedAnalyses::all();
      }
    }
    SeqConfig Seq = getSeqConfig();
    std::string PlanPath = getPlanPath();
    bool Changed = false;
    if (!PlanPath.empty())
      Changed |= runPlan(M, PlanPath);
    else if (!Seq.enabled())
      errs() << "prefetchit-inject: missing -prefetchit-plan or PREFETCHIT_PLAN "
                "(and no -prefetchit-seq-distance)\n";
    if (const char *CP = std::getenv("PREFETCHIT_COLD_PLAN"); CP && *CP)
      Changed |= runColdPlan(M, Seq, CP) > 0;
    else if (Seq.ColdOwnLines > 0 || std::getenv("PREFETCHIT_COLD"))
      Changed |= runColdPath(M, Seq) > 0;
    if (Seq.BurstLines > 0)
      Changed |= runCalleeEntryBurst(M, Seq) > 0;
    if (Seq.Distance > 0)
      Changed |= runSequentialLookahead(M, Seq) > 0;
    return Changed ? PreservedAnalyses::none() : PreservedAnalyses::all();
  }

  // Plan-driven injection (prefetchit.plan.v1). Returns true when anything
  // was injected.
  bool runPlan(Module &M, const std::string &PlanPath) {

    std::optional<Plan> Loaded = loadPlan(PlanPath);
    if (!Loaded)
      return false;

    std::optional<std::string> OverrideMnemonic;
    if (!PrefetchITMnemonicOverride.empty()) {
      OverrideMnemonic = normalizePrefetchMnemonic(PrefetchITMnemonicOverride);
      if (!OverrideMnemonic) {
        errs() << "prefetchit-inject: unsupported -prefetchit-mnemonic '"
               << PrefetchITMnemonicOverride << "'\n";
        return false;
      }
    }

    errs() << "prefetchit-inject: loaded " << Loaded->Injections.size()
           << " planned injections for module " << M.getName()
           << " default_mnemonic=" << Loaded->DefaultMnemonic
           << " operand_mode=" << Loaded->OperandMode
           << " byte_offsets=";
    for (size_t I = 0; I < Loaded->ByteOffsets.size(); ++I) {
      if (I)
        errs() << ",";
      errs() << Loaded->ByteOffsets[I];
    }
    errs() << " lead_instructions=" << Loaded->LeadInstructions;
    if (OverrideMnemonic)
      errs() << " override_mnemonic=" << *OverrideMnemonic;
    errs() << "\n";
    if (PrefetchITVerbose) {
      for (const InjectionSpec &Spec : Loaded->Injections) {
        StringRef Mnemonic =
            OverrideMnemonic ? StringRef(*OverrideMnemonic)
                             : StringRef(Spec.Mnemonic.empty()
                                             ? Loaded->DefaultMnemonic
                                             : Spec.Mnemonic);
        errs() << "  target#" << Spec.TargetRank << " site#" << Spec.SiteRank
               << " " << Mnemonic << " " << Spec.Site.Mangled << ":"
               << Spec.Site.Line << " -> "
               << Spec.Target.Mangled << ":" << Spec.Target.Line << " samples="
               << Spec.Samples << " coverage="
               << Spec.CumulativeCoveragePct << "% byte_offsets=";
        ArrayRef<int64_t> ByteOffsets = Spec.ByteOffsets.empty()
                                            ? ArrayRef<int64_t>(Loaded->ByteOffsets)
                                            : ArrayRef<int64_t>(Spec.ByteOffsets);
        for (size_t I = 0; I < ByteOffsets.size(); ++I) {
          if (I)
            errs() << ",";
          errs() << ByteOffsets[I];
        }
        errs() << "\n";
      }
    }

    InjectionStats Stats;
    std::map<std::string, BasicBlock *> TargetBlocks;
    std::map<std::string, unsigned> SiteUseCounts;
    std::map<Function *, FunctionDebugIndex> DebugIndexCache;
    std::set<std::string> Inserted;
    std::vector<PendingPrefetch> Pending;
    std::map<std::string, std::vector<uint64_t>> SiteOffsetsByLocation;
    for (const InjectionSpec &Spec : Loaded->Injections) {
      std::optional<uint64_t> Off = parseUnsignedInteger(Spec.Site.SymbolOffset);
      if (Off)
        SiteOffsetsByLocation[siteLocationKey(Spec)].push_back(*Off);
    }
    for (auto &Entry : SiteOffsetsByLocation) {
      std::sort(Entry.second.begin(), Entry.second.end());
      Entry.second.erase(std::unique(Entry.second.begin(), Entry.second.end()),
                         Entry.second.end());
    }

    for (const InjectionSpec &Spec : Loaded->Injections) {
      std::string Mnemonic =
          OverrideMnemonic ? *OverrideMnemonic
                           : (Spec.Mnemonic.empty() ? Loaded->DefaultMnemonic
                                                    : Spec.Mnemonic);
      if (!normalizePrefetchMnemonic(Mnemonic)) {
        ++Stats.UnsupportedMnemonic;
        continue;
      }

      std::string TKey = targetKey(Spec.Target);
      std::string OperandMode = Spec.Target.OperandMode.empty()
                                    ? Loaded->OperandMode
                                    : Spec.Target.OperandMode;
      bool PreferSymbolOffset = OperandMode == "pc-relative-symbol-offset";
      bool PreferGotSymbolOffset = OperandMode == "got-symbol-offset";
      bool HasLocalSymbolBinding =
          !Spec.Target.SymbolType.empty() &&
          std::islower(static_cast<unsigned char>(Spec.Target.SymbolType[0]));
      auto TargetIt = TargetBlocks.find(TKey);
      BasicBlock *TargetBB =
          TargetIt == TargetBlocks.end() ? nullptr : TargetIt->second;
      Function *TargetF = nullptr;
      if (PreferSymbolOffset && HasLocalSymbolBinding) {
        TargetF = findFunction(M, Spec.Target);
        if (!TargetF) {
          ++Stats.MissingTargetFunction;
          continue;
        }
        PreferSymbolOffset = false;
      }
      if (!PreferSymbolOffset && !PreferGotSymbolOffset) {
        if (!TargetF)
          TargetF = findFunction(M, Spec.Target);
        if (!TargetF) {
          ++Stats.MissingTargetFunction;
          if (PrefetchITVerbose)
            errs() << "prefetchit-inject: missing target function "
                   << Spec.Target.Mangled << "\n";
          continue;
        }
      }

      if (!PreferSymbolOffset && !PreferGotSymbolOffset && !TargetBB) {
        Instruction *TargetI =
            findInstructionAtLocation(*TargetF, Spec.Target, DebugIndexCache);
        if (!TargetI) {
          ++Stats.MissingTargetLocation;
          if (PrefetchITVerbose)
            errs() << "prefetchit-inject: missing target location "
                   << Spec.Target.Mangled << ":" << Spec.Target.Line << "\n";
          continue;
        }
        TargetBlockResult Target = ensureTargetBlock(*TargetI);
        TargetBB = Target.BB;
        if (Target.Split)
          ++Stats.TargetBlockSplit;
        else
          ++Stats.TargetBlockEntry;
        TargetBlocks[TKey] = TargetBB;
      }

      Function *SiteF = findFunction(M, Spec.Site);
      if (!SiteF) {
        ++Stats.MissingSiteFunction;
        if (PrefetchITVerbose)
          errs() << "prefetchit-inject: missing site function "
                 << Spec.Site.Mangled << "\n";
        continue;
      }

      std::vector<Instruction *> SiteCandidates =
          findSiteInstructions(*SiteF, Spec, DebugIndexCache);
      if (SiteCandidates.empty()) {
        ++Stats.MissingSiteLocation;
        if (PrefetchITVerbose)
          errs() << "prefetchit-inject: missing site location "
                 << Spec.Site.Mangled << ":" << Spec.Site.Line << "\n";
        continue;
      }
      std::string SKey = siteKey(Spec);
      unsigned &UseCount = SiteUseCounts[SKey];
      Instruction *SiteI = nullptr;
      std::optional<uint64_t> SiteOff = parseUnsignedInteger(Spec.Site.SymbolOffset);
      auto LocIt = SiteOffsetsByLocation.find(siteLocationKey(Spec));
      if (SiteOff && LocIt != SiteOffsetsByLocation.end() &&
          LocIt->second.size() > 1) {
        // rank of this site among the plan's sites at this location
        size_t Rank = std::lower_bound(LocIt->second.begin(),
                                       LocIt->second.end(), *SiteOff) -
                      LocIt->second.begin();
        if (LocIt->second.size() == SiteCandidates.size())
          SiteI = SiteCandidates[Rank];
        else
          SiteI = SiteCandidates[Rank % SiteCandidates.size()];
        ++Stats.RankedSites;
      } else {
        SiteI = SiteCandidates[UseCount % SiteCandidates.size()];
      }
      ++UseCount;
      Instruction *InsertionI =
          moveInsertionEarlier(*SiteI, Loaded->LeadInstructions);
      if (InsertionI != SiteI)
        ++Stats.LeadAdjustedSites;

      ArrayRef<int64_t> ByteOffsets = Spec.ByteOffsets.empty()
                                          ? ArrayRef<int64_t>(Loaded->ByteOffsets)
                                          : ArrayRef<int64_t>(Spec.ByteOffsets);
      for (int64_t ByteOffset : ByteOffsets) {
        std::string InsertKey =
            std::to_string(reinterpret_cast<uintptr_t>(InsertionI)) + "->" +
            TKey + ":" + Mnemonic + ":" + std::to_string(ByteOffset);
        if (!Inserted.insert(InsertKey).second) {
          ++Stats.Duplicate;
          continue;
        }

        PendingPrefetch P;
        P.Index = Spec.Index;
        P.InsertionI = InsertionI;
        P.Target = Spec.Target;
        P.Site = Spec.Site;
        P.Mnemonic = Mnemonic;
        P.ByteOffset = ByteOffset;
        if (PreferSymbolOffset && !Spec.Target.Mangled.empty() &&
            parseUnsignedInteger(Spec.Target.SymbolOffset)) {
          P.Mode = PendingPrefetch::SymbolOffset;
        } else if (PreferGotSymbolOffset && !Spec.Target.Mangled.empty() &&
                   parseUnsignedInteger(Spec.Target.SymbolOffset)) {
          P.Mode = PendingPrefetch::GotSymbolOffset;
        } else {
          if (PreferSymbolOffset || PreferGotSymbolOffset)
            ++Stats.MissingTargetSymbolOffset;
          if (!TargetF) {
            TargetF = findFunction(M, Spec.Target);
            if (!TargetF) {
              ++Stats.MissingTargetFunction;
              if (PrefetchITVerbose)
                errs() << "prefetchit-inject: missing target function "
                       << Spec.Target.Mangled << "\n";
              continue;
            }
          }
          if (!TargetBB) {
            Instruction *TargetI =
                findInstructionAtLocation(*TargetF, Spec.Target,
                                          DebugIndexCache);
            if (!TargetI) {
              ++Stats.MissingTargetLocation;
              if (PrefetchITVerbose)
                errs() << "prefetchit-inject: missing target location "
                       << Spec.Target.Mangled << ":" << Spec.Target.Line
                       << "\n";
              continue;
            }
            TargetBlockResult Target = ensureTargetBlock(*TargetI);
            TargetBB = Target.BB;
            if (Target.Split)
              ++Stats.TargetBlockSplit;
            else
              ++Stats.TargetBlockEntry;
            TargetBlocks[TKey] = TargetBB;
          }
          P.Mode = PendingPrefetch::BlockAddress;
          P.TargetF = TargetF;
          P.TargetBB = TargetBB;
        }
        Pending.push_back(std::move(P));
      }
    }

    // Layout compensation: bytes of rip-relative prefetches injected at plan
    // sites that precede each symbol+offset target inside the same function.
    std::map<std::string, std::vector<std::pair<uint64_t, uint64_t>>>
        SiteBytesByFunction;
    if (PrefetchITLayoutCompensation) {
      for (const PendingPrefetch &P : Pending) {
        if (P.Mode != PendingPrefetch::SymbolOffset || P.Site.Mangled.empty())
          continue;
        std::optional<uint64_t> SiteOff = parseUnsignedInteger(P.Site.SymbolOffset);
        if (!SiteOff)
          continue;
        SiteBytesByFunction[P.Site.Mangled].emplace_back(*SiteOff,
                                                         RipRelativePrefetchBytes);
      }
      for (auto &Entry : SiteBytesByFunction)
        std::sort(Entry.second.begin(), Entry.second.end());
    }
    auto layoutShiftFor = [&](const SourceLocSpec &Target) -> uint64_t {
      if (!PrefetchITLayoutCompensation)
        return 0;
      auto It = SiteBytesByFunction.find(Target.Mangled);
      if (It == SiteBytesByFunction.end())
        return 0;
      std::optional<uint64_t> TargetOff = parseUnsignedInteger(Target.SymbolOffset);
      if (!TargetOff)
        return 0;
      uint64_t Shift = 0;
      for (const auto &SiteBytes : It->second) {
        if (SiteBytes.first >= *TargetOff)
          break;
        Shift += SiteBytes.second;
      }
      return Shift;
    };

    std::string ShiftSidecar;
    raw_string_ostream ShiftJson(ShiftSidecar);
    ShiftJson << "[";
    bool FirstShift = true;
    for (const PendingPrefetch &P : Pending) {
      switch (P.Mode) {
      case PendingPrefetch::SymbolOffset: {
        uint64_t Shift = layoutShiftFor(P.Target);
        if (!insertPrefetchBeforeSymbolOffset(M, *P.InsertionI, P.Target,
                                              P.Mnemonic, P.ByteOffset, Shift))
          continue;
        ShiftJson << (FirstShift ? "\n" : ",\n") << "  {\"index\": " << P.Index
                  << ", \"byte_offset\": " << P.ByteOffset
                  << ", \"layout_shift\": " << Shift << "}";
        FirstShift = false;
        ++Stats.SymbolOffsetTarget;
        if (Shift) {
          ++Stats.LayoutShiftApplied;
          Stats.LayoutShiftMaxBytes = std::max(Stats.LayoutShiftMaxBytes, Shift);
        }
        if (!findFunction(M, P.Target))
          ++Stats.CrossModuleSymbolOffsetTarget;
        break;
      }
      case PendingPrefetch::GotSymbolOffset:
        if (!insertPrefetchBeforeGotSymbolOffset(M, *P.InsertionI, P.Target,
                                                 P.Mnemonic, P.ByteOffset))
          continue;
        ++Stats.GotSymbolOffsetTarget;
        break;
      case PendingPrefetch::BlockAddress:
        insertPrefetchBeforeBlockAddress(M, *P.InsertionI, *P.TargetF,
                                         *P.TargetBB, P.Mnemonic, P.ByteOffset);
        ++Stats.BlockAddressTarget;
        break;
      }
      ++Stats.Injected;
    }

    ShiftJson << "\n]\n";
    ShiftJson.flush();
    if (PrefetchITLayoutCompensation && !Pending.empty()) {
      // Sidecar consumed by tools/resolve_plan_layout_shift.py so that
      // assembly validation compares against the compensated targets.
      std::error_code EC;
      raw_fd_ostream Out(PlanPath + ".shifts.json", EC, sys::fs::OF_Text);
      if (EC)
        errs() << "prefetchit-inject: cannot write " << PlanPath
               << ".shifts.json: " << EC.message() << "\n";
      else
        Out << ShiftSidecar;
    }

    errs() << "prefetchit-inject: injected=" << Stats.Injected
           << " duplicate=" << Stats.Duplicate
           << " unsupported_mnemonic=" << Stats.UnsupportedMnemonic
           << " symbol_offset_target=" << Stats.SymbolOffsetTarget
           << " cross_module_symbol_offset_target="
           << Stats.CrossModuleSymbolOffsetTarget
           << " got_symbol_offset_target=" << Stats.GotSymbolOffsetTarget
           << " blockaddress_target=" << Stats.BlockAddressTarget
           << " target_block_entry=" << Stats.TargetBlockEntry
           << " target_block_split=" << Stats.TargetBlockSplit
           << " lead_adjusted_sites=" << Stats.LeadAdjustedSites
           << " ranked_sites=" << Stats.RankedSites
           << " layout_shift_applied=" << Stats.LayoutShiftApplied
           << " layout_shift_max_bytes=" << Stats.LayoutShiftMaxBytes
           << " missing_target_fn=" << Stats.MissingTargetFunction
           << " missing_target_loc=" << Stats.MissingTargetLocation
           << " missing_target_symbol_offset="
           << Stats.MissingTargetSymbolOffset
           << " missing_site_fn=" << Stats.MissingSiteFunction
           << " missing_site_loc=" << Stats.MissingSiteLocation << "\n";

    return Stats.Injected > 0;
  }
};

static void addPrefetchITPass(ModulePassManager &MPM) {
  MPM.addPass(PrefetchITPass());
}

} // namespace

extern "C" LLVM_ATTRIBUTE_WEAK PassPluginLibraryInfo llvmGetPassPluginInfo() {
  return {LLVM_PLUGIN_API_VERSION, "PrefetchITPass", LLVM_VERSION_STRING,
          [](PassBuilder &PB) {
            PB.registerPipelineStartEPCallback(
                [](ModulePassManager &MPM, OptimizationLevel Level) {
                  if (Level == OptimizationLevel::O0)
                    addPrefetchITPass(MPM);
                });
            PB.registerOptimizerLastEPCallback(
                [](ModulePassManager &MPM, OptimizationLevel Level) {
                  if (Level != OptimizationLevel::O0)
                    addPrefetchITPass(MPM);
                });
            PB.registerPipelineParsingCallback(
                [](StringRef Name, ModulePassManager &MPM,
                   ArrayRef<PassBuilder::PipelineElement>) {
                  if (Name == "prefetchit-inject") {
                    addPrefetchITPass(MPM);
                    return true;
                  }
                  return false;
                });
          }};
}
