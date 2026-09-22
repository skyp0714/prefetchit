#include <grpcpp/impl/grpc_library.h>

namespace {
__attribute__((init_priority(101))) grpc::internal::GrpcLibraryInitializer
    grpc_runtime_initializer;
}
