#include "llvm/ADT/StringRef.h"
#include "llvm/IR/Module.h"
#include "llvm/IR/PassManager.h"
#include "llvm/Passes/PassBuilder.h"
#include "llvm/Passes/PassPlugin.h"
#include "llvm/Support/CommandLine.h"
#include "llvm/Support/Error.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/MemoryBuffer.h"
#include "llvm/Support/raw_ostream.h"

#include <cstdint>
#include <optional>
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
    return PreservedAnalyses::all();
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
