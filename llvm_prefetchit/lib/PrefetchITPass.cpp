#include "llvm/ADT/StringRef.h"
#include "llvm/ADT/StringExtras.h"
#include "llvm/IR/BasicBlock.h"
#include "llvm/IR/Constants.h"
#include "llvm/IR/DebugInfoMetadata.h"
#include "llvm/IR/InlineAsm.h"
#include "llvm/IR/InstIterator.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/IntrinsicInst.h"
#include "llvm/IR/Module.h"
#include "llvm/IR/PassManager.h"
#include "llvm/Passes/PassBuilder.h"
#include "llvm/Passes/PassPlugin.h"
#include "llvm/Support/CommandLine.h"
#include "llvm/Support/Error.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/MemoryBuffer.h"
#include "llvm/Support/Path.h"
#include "llvm/Support/raw_ostream.h"

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <cstdint>
#include <charconv>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <vector>

using namespace llvm;

static cl::opt<std::string> PrefetchITPlanPath(
    "prefetchit-plan",
    cl::desc("Path to a prefetchit.plan.v1 JSON file"),
    cl::value_desc("path"), cl::init(""));

static cl::opt<bool>
    PrefetchITVerbose("prefetchit-verbose",
                      cl::desc("Print detailed PrefetchIT pass diagnostics"),
                      cl::init(false));

static cl::opt<std::string> PrefetchITMnemonicOverride(
    "prefetchit-mnemonic",
    cl::desc("Override plan prefetch mnemonic: prefetcht0, prefetcht1, "
             "prefetcht2, prefetchnta, prefetchit0, or prefetchit1"),
    cl::value_desc("mnemonic"), cl::init(""));

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
  std::string OperandMode;
};

struct InjectionSpec {
  std::string Mnemonic;
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
  std::vector<InjectionSpec> Injections;
};

struct InjectionStats {
  unsigned Injected = 0;
  unsigned Duplicate = 0;
  unsigned UnsupportedMnemonic = 0;
  unsigned SymbolOffsetTarget = 0;
  unsigned CrossModuleSymbolOffsetTarget = 0;
  unsigned GotSymbolOffsetTarget = 0;
  unsigned BlockAddressTarget = 0;
  unsigned TargetBlockEntry = 0;
  unsigned TargetBlockSplit = 0;
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
  return EnvPath ? std::string(EnvPath) : std::string();
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

static bool insertPrefetchBeforeSymbolOffset(Module &M, Instruction &SiteI,
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

class PrefetchITPass : public PassInfoMixin<PrefetchITPass> {
public:
  PreservedAnalyses run(Module &M, ModuleAnalysisManager &) {
    std::string PlanPath = getPlanPath();
    if (PlanPath.empty()) {
      errs() << "prefetchit-inject: missing -prefetchit-plan or PREFETCHIT_PLAN\n";
      return PreservedAnalyses::all();
    }

    std::optional<Plan> Loaded = loadPlan(PlanPath);
    if (!Loaded)
      return PreservedAnalyses::all();

    std::optional<std::string> OverrideMnemonic;
    if (!PrefetchITMnemonicOverride.empty()) {
      OverrideMnemonic = normalizePrefetchMnemonic(PrefetchITMnemonicOverride);
      if (!OverrideMnemonic) {
        errs() << "prefetchit-inject: unsupported -prefetchit-mnemonic '"
               << PrefetchITMnemonicOverride << "'\n";
        return PreservedAnalyses::all();
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
               << Spec.CumulativeCoveragePct << "%\n";
      }
    }

    InjectionStats Stats;
    std::map<std::string, BasicBlock *> TargetBlocks;
    std::map<std::string, unsigned> SiteUseCounts;
    std::map<Function *, FunctionDebugIndex> DebugIndexCache;
    std::set<std::string> Inserted;

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
      auto TargetIt = TargetBlocks.find(TKey);
      BasicBlock *TargetBB =
          TargetIt == TargetBlocks.end() ? nullptr : TargetIt->second;
      Function *TargetF = nullptr;
      if (!PreferSymbolOffset && !PreferGotSymbolOffset) {
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
      Instruction *SiteI = SiteCandidates[UseCount % SiteCandidates.size()];
      ++UseCount;

      for (int64_t ByteOffset : Loaded->ByteOffsets) {
        std::string InsertKey =
            std::to_string(reinterpret_cast<uintptr_t>(SiteI)) + "->" +
            TKey + ":" + Mnemonic + ":" + std::to_string(ByteOffset);
        if (!Inserted.insert(InsertKey).second) {
          ++Stats.Duplicate;
          continue;
        }

        if (PreferSymbolOffset &&
            insertPrefetchBeforeSymbolOffset(M, *SiteI, Spec.Target, Mnemonic,
                                             ByteOffset)) {
          ++Stats.SymbolOffsetTarget;
          if (!findFunction(M, Spec.Target))
            ++Stats.CrossModuleSymbolOffsetTarget;
        } else if (PreferGotSymbolOffset &&
                   insertPrefetchBeforeGotSymbolOffset(M, *SiteI, Spec.Target,
                                                       Mnemonic, ByteOffset)) {
          ++Stats.GotSymbolOffsetTarget;
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
          insertPrefetchBeforeBlockAddress(M, *SiteI, *TargetF, *TargetBB,
                                           Mnemonic, ByteOffset);
          ++Stats.BlockAddressTarget;
        }
        ++Stats.Injected;
      }
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
           << " missing_target_fn=" << Stats.MissingTargetFunction
           << " missing_target_loc=" << Stats.MissingTargetLocation
           << " missing_target_symbol_offset="
           << Stats.MissingTargetSymbolOffset
           << " missing_site_fn=" << Stats.MissingSiteFunction
           << " missing_site_loc=" << Stats.MissingSiteLocation << "\n";

    return Stats.Injected ? PreservedAnalyses::none()
                          : PreservedAnalyses::all();
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
