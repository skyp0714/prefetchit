cmake_minimum_required(VERSION 3.16)
project(prefetchit_router_static_grpc LANGUAGES C CXX)

set(PREFETCHIT_ROOT "/home/hnpark2/prefetchit" CACHE PATH "PrefetchIT workspace")
set(
  GRPC_SOURCE
  "${PREFETCHIT_ROOT}/llvm_prefetchit/work/pgo_goal_20260713/deb-src/grpc-1.30.2"
  CACHE PATH "gRPC source tree"
)
set(
  ROUTER_SOURCE
  "${PREFETCHIT_ROOT}/benchmarks/datacenter_sources/MicroSuite/src/Router"
  CACHE PATH "MicroSuite Router source tree"
)
set(PREFETCHIT_PASS_PLUGIN "" CACHE FILEPATH "Optional PrefetchIT pass plugin")
set(PREFETCHIT_GRPC_MAX_THREADS 4 CACHE STRING "gRPC callback thread quota")

set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(gRPC_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(gRPC_BUILD_CODEGEN OFF CACHE BOOL "" FORCE)
set(gRPC_BUILD_CSHARP_EXT OFF CACHE BOOL "" FORCE)
set(gRPC_INSTALL OFF CACHE BOOL "" FORCE)
set(gRPC_ABSL_PROVIDER package CACHE STRING "" FORCE)
set(gRPC_CARES_PROVIDER package CACHE STRING "" FORCE)
set(gRPC_PROTOBUF_PROVIDER package CACHE STRING "" FORCE)
set(gRPC_SSL_PROVIDER package CACHE STRING "" FORCE)
set(gRPC_ZLIB_PROVIDER package CACHE STRING "" FORCE)
set(
  Protobuf_PROTOC_LIBRARY
  "/usr/lib/x86_64-linux-gnu/libprotoc.so"
  CACHE FILEPATH "libprotoc for the Ubuntu protobuf package"
  FORCE
)

add_compile_options(-O3 -g -fno-omit-frame-pointer)
if(PREFETCHIT_PASS_PLUGIN)
  add_compile_options("-fpass-plugin=${PREFETCHIT_PASS_PLUGIN}")
endif()

add_subdirectory("${GRPC_SOURCE}" grpc EXCLUDE_FROM_ALL)

add_executable(
  router_mid_tier
  grpc_early_init.cc
  "${ROUTER_SOURCE}/protoc_files/lookup.pb.cc"
  "${ROUTER_SOURCE}/protoc_files/lookup.grpc.pb.cc"
  "${ROUTER_SOURCE}/protoc_files/router.pb.cc"
  "${ROUTER_SOURCE}/protoc_files/router.grpc.pb.cc"
  "${ROUTER_SOURCE}/mid_tier_service/src/spookyhash.cc"
  "${ROUTER_SOURCE}/lookup_service/service/helper_files/client_helper.cc"
  "${ROUTER_SOURCE}/mid_tier_service/service/helper_files/router_server_helper.cc"
  "${ROUTER_SOURCE}/mid_tier_service/service/helper_files/timing.cc"
  "${ROUTER_SOURCE}/mid_tier_service/service/helper_files/utils.cc"
  "${ROUTER_SOURCE}/mid_tier_service/service/mid_tier_server.cc"
)
set_target_properties(
  router_mid_tier
  PROPERTIES
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED YES
    CXX_EXTENSIONS NO
    OUTPUT_NAME mid_tier_server
)
target_compile_options(router_mid_tier PRIVATE -fopenmp=libgomp -Wall)
target_compile_definitions(
  router_mid_tier
  PRIVATE
    "PREFETCHIT_GRPC_MAX_THREADS=${PREFETCHIT_GRPC_MAX_THREADS}"
    PREFETCHIT_ROUTER_HANDOFF_STAGE=0
    PREFETCHIT_ROUTER_TAG_LINES=0
    PREFETCHIT_ROUTER_CODE_LINES=0
    PREFETCHIT_ROUTER_PREFETCH_LOCALITY=3
    PREFETCHIT_HD_LSH_DATA_LINES=0
    PREFETCHIT_HD_LSH_LOOKAHEAD=0
    PREFETCHIT_HD_LSH_PREFETCH_LOCALITY=3
)
target_include_directories(
  router_mid_tier
  PRIVATE
    "${ROUTER_SOURCE}"
    /usr/lib/gcc/x86_64-linux-gnu/11/include
)
target_link_libraries(
  router_mid_tier
  PRIVATE
    grpc++
    /usr/lib/x86_64-linux-gnu/libprotobuf.so
    gomp
)
