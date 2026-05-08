#include "llvm/ADT/StringRef.h"
#include "llvm/IR/Module.h"
#include "llvm/IR/PassManager.h"
#include "llvm/Passes/PassBuilder.h"
#include "llvm/Passes/PassPlugin.h"
#include "llvm/Support/CommandLine.h"
#include "llvm/Support/raw_ostream.h"

using namespace llvm;

static cl::opt<std::string> PrefetchITPlanPath(
    "prefetchit-plan",
    cl::desc("Path to a prefetchit.plan.v1 JSON file"),
    cl::value_desc("path"), cl::init(""));

namespace {

class PrefetchITPass : public PassInfoMixin<PrefetchITPass> {
public:
  PreservedAnalyses run(Module &M, ModuleAnalysisManager &) {
    if (PrefetchITPlanPath.empty()) {
      errs() << "prefetchit-inject: missing -prefetchit-plan\n";
      return PreservedAnalyses::all();
    }

    errs() << "prefetchit-inject: plan parsing/injection is not implemented yet: "
           << PrefetchITPlanPath << "\n";
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
