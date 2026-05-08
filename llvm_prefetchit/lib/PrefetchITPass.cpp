#include "llvm/ADT/StringRef.h"
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
#include <cstdint>
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

namespace {

struct SourceLocSpec {
  std::string Mangled;
  std::string Demangled;
  std::string Function;
  std::string File;
  unsigned Line = 0;
  std::string Addr;
};

struct InjectionSpec {
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
  std::vector<InjectionSpec> Injections;
};

struct InjectionStats {
  unsigned Injected = 0;
  unsigned Duplicate = 0;
  unsigned MissingTargetFunction = 0;
  unsigned MissingTargetLocation = 0;
  unsigned MissingSiteFunction = 0;
  unsigned MissingSiteLocation = 0;
};

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

static SourceLocSpec parseSourceLoc(const json::Object &Obj) {
  SourceLocSpec Loc;
  Loc.Mangled = getString(Obj, "mangled");
  Loc.Demangled = getString(Obj, "demangled");
  Loc.Function = getString(Obj, "function");
  Loc.File = getString(Obj, "file");
  Loc.Line = getUnsigned(Obj, "line");
  Loc.Addr = getString(Obj, "addr");
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
  for (const json::Value &Value : *Injections) {
    const json::Object *Obj = Value.getAsObject();
    if (!Obj)
      continue;
    const json::Object *Target = Obj->getObject("target");
    const json::Object *Site = Obj->getObject("site");
    if (!Target || !Site)
      continue;

    InjectionSpec Spec;
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

  std::string ActualSuffix = "/" + Actual;
  std::string WantedSuffix = "/" + Wanted;
  return StringRef(ActualSuffix).ends_with(WantedSuffix) ||
         StringRef(WantedSuffix).ends_with(ActualSuffix);
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

static Instruction *findInstructionAtLocation(Function &F,
                                              const SourceLocSpec &Spec) {
  for (Instruction &I : instructions(F)) {
    if (isIgnorableInstruction(I))
      continue;
    if (debugLocMatches(I.getDebugLoc(), Spec))
      return &I;
  }
  return nullptr;
}

static Instruction *findSiteInstruction(Function &F, const InjectionSpec &Spec) {
  Instruction *Fallback = nullptr;
  for (Instruction &I : instructions(F)) {
    if (isIgnorableInstruction(I))
      continue;
    if (!debugLocMatches(I.getDebugLoc(), Spec.Site))
      continue;
    if (!Fallback)
      Fallback = &I;
    if (isPreferredSiteInstruction(I, Spec.BranchType))
      return &I;
  }
  return Fallback;
}

static Instruction *firstAnchorableInstruction(BasicBlock &BB) {
  for (Instruction &I : BB) {
    if (!isIgnorableInstruction(I))
      return &I;
  }
  return BB.getTerminator();
}

static BasicBlock *ensureTargetBlock(Instruction &TargetI) {
  BasicBlock *BB = TargetI.getParent();
  if (firstAnchorableInstruction(*BB) == &TargetI) {
    if (!BB->hasName())
      BB->setName("prefetchit.target");
    return BB;
  }
  BasicBlock *TargetBB =
      BB->splitBasicBlock(TargetI.getIterator(), "prefetchit.target");
  if (!TargetBB->hasName())
    TargetBB->setName("prefetchit.target");
  return TargetBB;
}

static std::string targetKey(const SourceLocSpec &Spec) {
  return Spec.Mangled + "\n" + Spec.Function + "\n" + normalizePath(Spec.File) +
         "\n" + std::to_string(Spec.Line);
}

static void insertPrefetchBefore(Module &M, Instruction &SiteI,
                                 Function &TargetF, BasicBlock &TargetBB) {
  LLVMContext &Ctx = M.getContext();
  PointerType *PtrTy = PointerType::getUnqual(Ctx);
  FunctionType *AsmTy =
      FunctionType::get(Type::getVoidTy(Ctx), {PtrTy}, false);
  InlineAsm *Asm = InlineAsm::get(AsmTy, "prefetchit0 ${0:c}(%rip)",
                                  "i,~{memory}", true);
  BlockAddress *TargetAddr = BlockAddress::get(&TargetF, &TargetBB);
  CallInst *CI = CallInst::Create(Asm, {TargetAddr}, "", &SiteI);
  CI->setDebugLoc(SiteI.getDebugLoc());
}

class PrefetchITPass : public PassInfoMixin<PrefetchITPass> {
public:
  PreservedAnalyses run(Module &M, ModuleAnalysisManager &) {
    if (PrefetchITPlanPath.empty()) {
      errs() << "prefetchit-inject: missing -prefetchit-plan\n";
      return PreservedAnalyses::all();
    }

    std::optional<Plan> Loaded = loadPlan(PrefetchITPlanPath);
    if (!Loaded)
      return PreservedAnalyses::all();

    errs() << "prefetchit-inject: loaded " << Loaded->Injections.size()
           << " planned injections for module " << M.getName() << "\n";
    if (PrefetchITVerbose) {
      for (const InjectionSpec &Spec : Loaded->Injections) {
        errs() << "  target#" << Spec.TargetRank << " site#" << Spec.SiteRank
               << " " << Spec.Site.Mangled << ":" << Spec.Site.Line << " -> "
               << Spec.Target.Mangled << ":" << Spec.Target.Line << " samples="
               << Spec.Samples << " coverage="
               << Spec.CumulativeCoveragePct << "%\n";
      }
    }

    InjectionStats Stats;
    std::map<std::string, BasicBlock *> TargetBlocks;
    std::set<std::string> Inserted;

    for (const InjectionSpec &Spec : Loaded->Injections) {
      std::string TKey = targetKey(Spec.Target);
      auto TargetIt = TargetBlocks.find(TKey);
      BasicBlock *TargetBB =
          TargetIt == TargetBlocks.end() ? nullptr : TargetIt->second;
      Function *TargetF = findFunction(M, Spec.Target);
      if (!TargetF) {
        ++Stats.MissingTargetFunction;
        if (PrefetchITVerbose)
          errs() << "prefetchit-inject: missing target function "
                 << Spec.Target.Mangled << "\n";
        continue;
      }

      if (!TargetBB) {
        Instruction *TargetI = findInstructionAtLocation(*TargetF, Spec.Target);
        if (!TargetI) {
          ++Stats.MissingTargetLocation;
          if (PrefetchITVerbose)
            errs() << "prefetchit-inject: missing target location "
                   << Spec.Target.Mangled << ":" << Spec.Target.Line << "\n";
          continue;
        }
        TargetBB = ensureTargetBlock(*TargetI);
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

      Instruction *SiteI = findSiteInstruction(*SiteF, Spec);
      if (!SiteI) {
        ++Stats.MissingSiteLocation;
        if (PrefetchITVerbose)
          errs() << "prefetchit-inject: missing site location "
                 << Spec.Site.Mangled << ":" << Spec.Site.Line << "\n";
        continue;
      }

      std::string InsertKey =
          std::to_string(reinterpret_cast<uintptr_t>(SiteI)) + "->" +
          std::to_string(reinterpret_cast<uintptr_t>(TargetBB));
      if (!Inserted.insert(InsertKey).second) {
        ++Stats.Duplicate;
        continue;
      }

      insertPrefetchBefore(M, *SiteI, *TargetF, *TargetBB);
      ++Stats.Injected;
    }

    errs() << "prefetchit-inject: injected=" << Stats.Injected
           << " duplicate=" << Stats.Duplicate
           << " missing_target_fn=" << Stats.MissingTargetFunction
           << " missing_target_loc=" << Stats.MissingTargetLocation
           << " missing_site_fn=" << Stats.MissingSiteFunction
           << " missing_site_loc=" << Stats.MissingSiteLocation << "\n";

    return Stats.Injected ? PreservedAnalyses::none()
                          : PreservedAnalyses::all();
  }
};

} // namespace

extern "C" LLVM_ATTRIBUTE_WEAK PassPluginLibraryInfo llvmGetPassPluginInfo() {
  return {LLVM_PLUGIN_API_VERSION, "PrefetchITPass", LLVM_VERSION_STRING,
          [](PassBuilder &PB) {
            PB.registerPipelineParsingCallback(
                [](StringRef Name, ModulePassManager &MPM,
                   ArrayRef<PassBuilder::PipelineElement>) {
                  if (Name == "prefetchit-inject") {
                    MPM.addPass(PrefetchITPass());
                    return true;
                  }
                  return false;
                });
          }};
}
