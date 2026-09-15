cmake_minimum_required(VERSION 3.16)
project(prefetchit_microsuite_static_grpc LANGUAGES C CXX)

get_filename_component(
  PREFETCHIT_DEFAULT_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../.." ABSOLUTE
)
set(PREFETCHIT_ROOT "${PREFETCHIT_DEFAULT_ROOT}" CACHE PATH "PrefetchIT workspace")
set(
  GRPC_SOURCE
  "${PREFETCHIT_ROOT}/llvm_prefetchit/work/pgo_goal_20260713/deb-src/grpc-1.30.2"
  CACHE PATH "gRPC source tree"
)
set(
  MICROSUITE_SOURCE
  "${PREFETCHIT_ROOT}/benchmarks/datacenter_sources/MicroSuite/src"
  CACHE PATH "MicroSuite source tree"
)
set(PREFETCHIT_BENCHMARK "setalgebra" CACHE STRING "MicroSuite benchmark")
set_property(CACHE PREFETCHIT_BENCHMARK PROPERTY STRINGS router setalgebra recommend)
set(PREFETCHIT_COMPONENT "mid" CACHE STRING "MicroSuite service component")
set_property(CACHE PREFETCHIT_COMPONENT PROPERTY STRINGS mid leaf)
set(PREFETCHIT_PASS_PLUGIN "" CACHE FILEPATH "Optional PrefetchIT pass plugin")
set(PREFETCHIT_GRPC_MAX_THREADS 4 CACHE STRING "gRPC callback thread quota")
set(PREFETCHIT_GRPC_CLIENT_MAX_THREADS 4 CACHE STRING "gRPC client executor thread quota")
set(BENCHMARK_COMPILER_INCLUDES /usr/lib/gcc/x86_64-linux-gnu/11/include)

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

if(PREFETCHIT_BENCHMARK STREQUAL "router")
  set(BENCHMARK_SOURCE "${MICROSUITE_SOURCE}/Router")
  set(BENCHMARK_SOURCES
    "${BENCHMARK_SOURCE}/protoc_files/lookup.pb.cc"
    "${BENCHMARK_SOURCE}/protoc_files/lookup.grpc.pb.cc"
    "${BENCHMARK_SOURCE}/protoc_files/router.pb.cc"
    "${BENCHMARK_SOURCE}/protoc_files/router.grpc.pb.cc"
    "${BENCHMARK_SOURCE}/mid_tier_service/src/spookyhash.cc"
    "${BENCHMARK_SOURCE}/lookup_service/service/helper_files/client_helper.cc"
    "${BENCHMARK_SOURCE}/mid_tier_service/service/helper_files/router_server_helper.cc"
    "${BENCHMARK_SOURCE}/mid_tier_service/service/helper_files/timing.cc"
    "${BENCHMARK_SOURCE}/mid_tier_service/service/helper_files/utils.cc"
    "${BENCHMARK_SOURCE}/mid_tier_service/service/mid_tier_server.cc"
  )
  set(BENCHMARK_DEFINITIONS
    PREFETCHIT_ROUTER_HANDOFF_STAGE=0
    PREFETCHIT_ROUTER_TAG_LINES=0
    PREFETCHIT_ROUTER_CODE_LINES=0
    PREFETCHIT_ROUTER_PREFETCH_LOCALITY=3
    PREFETCHIT_HD_LSH_DATA_LINES=0
    PREFETCHIT_HD_LSH_LOOKAHEAD=0
    PREFETCHIT_HD_LSH_PREFETCH_LOCALITY=3
  )
elseif(PREFETCHIT_BENCHMARK STREQUAL "setalgebra")
  set(BENCHMARK_SOURCE "${MICROSUITE_SOURCE}/SetAlgebra")
  set(BENCHMARK_SOURCES
    "${BENCHMARK_SOURCE}/protoc_files/intersection.pb.cc"
    "${BENCHMARK_SOURCE}/protoc_files/intersection.grpc.pb.cc"
    "${BENCHMARK_SOURCE}/protoc_files/union.pb.cc"
    "${BENCHMARK_SOURCE}/protoc_files/union.grpc.pb.cc"
    "${BENCHMARK_SOURCE}/intersection_service/service/helper_files/client_helper.cc"
    "${BENCHMARK_SOURCE}/union_service/service/helper_files/union_server_helper.cc"
    "${BENCHMARK_SOURCE}/union_service/service/helper_files/timing.cc"
    "${BENCHMARK_SOURCE}/union_service/service/helper_files/utils.cc"
    "${BENCHMARK_SOURCE}/union_service/service/mid_tier_server.cc"
  )
  set(BENCHMARK_DEFINITIONS
    PREFETCHIT_SET_HANDOFF_STAGE=0
    PREFETCHIT_SET_TAG_LINES=0
    PREFETCHIT_SET_CODE_LINES=0
    PREFETCHIT_SET_PREFETCH_LOCALITY=3
  )
elseif(PREFETCHIT_BENCHMARK STREQUAL "recommend")
  set(BENCHMARK_SOURCE "${MICROSUITE_SOURCE}/Recommend")
  if(PREFETCHIT_COMPONENT STREQUAL "mid")
    set(BENCHMARK_SOURCES
      "${BENCHMARK_SOURCE}/protoc_files/cf.pb.cc"
      "${BENCHMARK_SOURCE}/protoc_files/cf.grpc.pb.cc"
      "${BENCHMARK_SOURCE}/protoc_files/recommender.pb.cc"
      "${BENCHMARK_SOURCE}/protoc_files/recommender.grpc.pb.cc"
      "${BENCHMARK_SOURCE}/cf_service/service/helper_files/client_helper.cc"
      "${BENCHMARK_SOURCE}/recommender_service/service/helper_files/recommender_server_helper.cc"
      "${BENCHMARK_SOURCE}/recommender_service/service/helper_files/timing.cc"
      "${BENCHMARK_SOURCE}/recommender_service/service/helper_files/utils.cc"
      "${BENCHMARK_SOURCE}/recommender_service/service/mid_tier_server.cc"
    )
  elseif(PREFETCHIT_COMPONENT STREQUAL "leaf")
    set(MICROSUITE_DEB_ROOT
      "${PREFETCHIT_ROOT}/llvm_prefetchit/work/datacenter_goal_20260708/deb_deps/root"
    )
    set(MICROSUITE_OMP_ROOT
      "${PREFETCHIT_ROOT}/llvm_prefetchit/work/datacenter_goal_20260708/deb_deps/omp19/root"
    )
    set(BENCHMARK_SOURCES
      "${BENCHMARK_SOURCE}/protoc_files/cf.pb.cc"
      "${BENCHMARK_SOURCE}/protoc_files/cf.grpc.pb.cc"
      "${BENCHMARK_SOURCE}/cf_service/service/helper_files/timing.cc"
      "${BENCHMARK_SOURCE}/cf_service/service/helper_files/utils.cc"
      "${BENCHMARK_SOURCE}/cf_service/service/helper_files/server_helper.cc"
      "${BENCHMARK_SOURCE}/cf_service/service/cf_server.cc"
    )
    set(BENCHMARK_EXTRA_INCLUDES
      "${MICROSUITE_DEB_ROOT}/usr/include"
      "${MICROSUITE_OMP_ROOT}/usr/lib/llvm-19/lib/clang/19/include"
    )
    set(BENCHMARK_COMPILER_INCLUDES)
    set(BENCHMARK_EXTRA_LIBRARIES
      "${MICROSUITE_DEB_ROOT}/usr/lib/x86_64-linux-gnu/libmlpack.so.3.4"
      "${MICROSUITE_DEB_ROOT}/usr/lib/libarmadillo.so.10.8.2"
    )
    set(BENCHMARK_DEFINITIONS ARMA_DONT_USE_SUPERLU)
  else()
    message(FATAL_ERROR "Recommend component must be mid or leaf")
  endif()
  set(BENCHMARK_COMPILE_OPTIONS -mavx -mavx2)
  if(NOT PREFETCHIT_COMPONENT STREQUAL "leaf")
    set(BENCHMARK_DEFINITIONS)
  endif()
else()
  message(FATAL_ERROR "Unsupported PREFETCHIT_BENCHMARK=${PREFETCHIT_BENCHMARK}")
endif()

if(PREFETCHIT_COMPONENT STREQUAL "leaf")
  if(NOT PREFETCHIT_BENCHMARK STREQUAL "recommend")
    message(FATAL_ERROR "leaf component is currently supported only for recommend")
  endif()
  set(COMPONENT_TARGET microsuite_leaf)
  set(COMPONENT_OUTPUT_NAME cf_server)
else()
  set(COMPONENT_TARGET microsuite_mid_tier)
  set(COMPONENT_OUTPUT_NAME mid_tier_server)
endif()

add_executable(
  ${COMPONENT_TARGET}
  grpc_early_init.cc
  ${BENCHMARK_SOURCES}
)
set_target_properties(
  ${COMPONENT_TARGET}
  PROPERTIES
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED YES
    CXX_EXTENSIONS NO
    OUTPUT_NAME ${COMPONENT_OUTPUT_NAME}
)
target_compile_options(
  ${COMPONENT_TARGET} PRIVATE -fopenmp=libgomp -Wall ${BENCHMARK_COMPILE_OPTIONS}
)
target_compile_definitions(
  ${COMPONENT_TARGET}
  PRIVATE
    "PREFETCHIT_GRPC_MAX_THREADS=${PREFETCHIT_GRPC_MAX_THREADS}"
    "PREFETCHIT_GRPC_CLIENT_MAX_THREADS=${PREFETCHIT_GRPC_CLIENT_MAX_THREADS}"
    ${BENCHMARK_DEFINITIONS}
)
target_include_directories(
  ${COMPONENT_TARGET}
  PRIVATE
    "${BENCHMARK_SOURCE}"
    ${BENCHMARK_EXTRA_INCLUDES}
    ${BENCHMARK_COMPILER_INCLUDES}
)
target_link_libraries(
  ${COMPONENT_TARGET}
  PRIVATE
    grpc++
    /usr/lib/x86_64-linux-gnu/libprotobuf.so
    gomp
    ${BENCHMARK_EXTRA_LIBRARIES}
)
