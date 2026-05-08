cmake_minimum_required(VERSION 3.16)

project(PrefetchITPass LANGUAGES C CXX)

find_package(LLVM REQUIRED CONFIG)

message(STATUS "Found LLVM ${LLVM_PACKAGE_VERSION}")
message(STATUS "Using LLVMConfig.cmake in: ${LLVM_DIR}")

if(NOT LLVM_VERSION_MAJOR EQUAL 19)
  message(FATAL_ERROR "PrefetchITPass expects LLVM 19, found ${LLVM_PACKAGE_VERSION}")
endif()

list(APPEND CMAKE_MODULE_PATH "${LLVM_CMAKE_DIR}")
include(AddLLVM)

set(CMAKE_CXX_STANDARD 17 CACHE STRING "C++ standard")
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_llvm_pass_plugin(PrefetchITPass
  lib/PrefetchITPass.cpp
)

target_include_directories(PrefetchITPass PRIVATE ${LLVM_INCLUDE_DIRS})
target_compile_definitions(PrefetchITPass PRIVATE ${LLVM_DEFINITIONS})
