#include <pthread.h>
#include <sched.h>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {

std::vector<int> ParseCores(const std::string& value) {
  std::vector<int> cores;
  std::size_t begin = 0;
  while (begin < value.size()) {
    const std::size_t comma = value.find(',', begin);
    const std::string token = value.substr(begin, comma - begin);
    const std::size_t dash = token.find('-');
    if (dash == std::string::npos) {
      cores.push_back(std::stoi(token));
    } else {
      const int first = std::stoi(token.substr(0, dash));
      const int last = std::stoi(token.substr(dash + 1));
      if (last < first) throw std::runtime_error("descending CPU range");
      for (int cpu = first; cpu <= last; ++cpu) cores.push_back(cpu);
    }
    if (comma == std::string::npos) break;
    begin = comma + 1;
  }
  if (cores.empty()) throw std::runtime_error("empty CPU list");
  return cores;
}

void PinToCpu(int cpu) {
  cpu_set_t set;
  CPU_ZERO(&set);
  CPU_SET(cpu, &set);
  const int error = pthread_setaffinity_np(pthread_self(), sizeof(set), &set);
  if (error != 0) {
    throw std::runtime_error("pthread_setaffinity_np: " +
                             std::string(std::strerror(error)));
  }
}

}  // namespace

int main(int argc, char** argv) {
  std::string core_spec = "1-70";
  std::size_t bytes_per_core = 8ULL << 20;
  int passes = 4;
  for (int index = 1; index < argc; ++index) {
    const std::string option = argv[index];
    if (option == "--cores" && index + 1 < argc) {
      core_spec = argv[++index];
    } else if (option == "--bytes-per-core" && index + 1 < argc) {
      bytes_per_core = std::stoull(argv[++index]);
    } else if (option == "--passes" && index + 1 < argc) {
      passes = std::stoi(argv[++index]);
    } else {
      std::cerr << "usage: " << argv[0]
                << " [--cores LIST] [--bytes-per-core N] [--passes N]\n";
      return 2;
    }
  }
  if (bytes_per_core < 64 || bytes_per_core % 64 != 0 || passes < 1) {
    std::cerr << "invalid cache eviction dimensions\n";
    return 2;
  }

  try {
    const std::vector<int> cores = ParseCores(core_spec);
    std::atomic<int> ready{0};
    std::atomic<bool> start{false};
    std::atomic<bool> failed{false};
    std::atomic<std::uint64_t> checksum{0};
    std::mutex error_mutex;
    std::string error_message;
    std::vector<std::thread> workers;
    workers.reserve(cores.size());
    const auto started = std::chrono::steady_clock::now();

    for (const int cpu : cores) {
      workers.emplace_back([&, cpu] {
        void* allocation = nullptr;
        try {
          PinToCpu(cpu);
          if (posix_memalign(&allocation, 4096, bytes_per_core) != 0) {
            throw std::bad_alloc();
          }
        } catch (const std::exception& error) {
          {
            std::lock_guard<std::mutex> lock(error_mutex);
            if (error_message.empty()) error_message = error.what();
          }
          failed.store(true, std::memory_order_release);
          ready.fetch_add(1, std::memory_order_release);
          return;
        }
        auto* buffer = static_cast<volatile std::uint8_t*>(allocation);
        for (std::size_t offset = 0; offset < bytes_per_core; offset += 4096) {
          buffer[offset] = static_cast<std::uint8_t>(cpu);
        }
        ready.fetch_add(1, std::memory_order_release);
        while (!start.load(std::memory_order_acquire)) std::this_thread::yield();

        std::uint64_t local = 0;
        for (int pass = 0; pass < passes; ++pass) {
          for (std::size_t offset = 0; offset < bytes_per_core; offset += 64) {
            const std::uint8_t value = static_cast<std::uint8_t>(
                buffer[offset] + cpu + pass + static_cast<int>(offset >> 6));
            buffer[offset] = value;
            local += value;
          }
        }
        checksum.fetch_add(local, std::memory_order_relaxed);
        std::free(allocation);
      });
    }
    while (ready.load(std::memory_order_acquire) !=
           static_cast<int>(cores.size())) {
      std::this_thread::yield();
    }
    start.store(true, std::memory_order_release);
    for (auto& worker : workers) worker.join();
    if (failed.load(std::memory_order_acquire)) {
      throw std::runtime_error(error_message.empty() ? "cache eviction failed"
                                                     : error_message);
    }

    const auto elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                                std::chrono::steady_clock::now() - started)
                                .count();
    std::cout << "cores=" << cores.size()
              << " bytes_per_core=" << bytes_per_core
              << " total_bytes=" << bytes_per_core * cores.size()
              << " passes=" << passes << " checksum=" << checksum.load()
              << " elapsed_ms=" << elapsed_ms << '\n';
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
