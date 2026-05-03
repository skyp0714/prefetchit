# Makefile for latency benchmark with multiple configurations
# Builds four versions with different flag combinations

CC = clang
ARCH ?= graniterapids
CFLAGS ?= -O2 -march=$(ARCH) -m64 -no-pie -fno-plt -mprefetchi
SOURCES = latency.c utils.c

# Target names for the four binary variants
TARGET_BASE = lat_bench
TARGET_PREFETCH = lat_bench_prefetch
TARGET_PERF = lat_bench_perf  
TARGET_BOTH = lat_bench_prefetch_perf

.PHONY: all clean help

# Default target builds all versions
all: $(TARGET_BASE) $(TARGET_PREFETCH) $(TARGET_PERF) $(TARGET_BOTH)

# Basic version - no flags
$(TARGET_BASE): $(SOURCES)
	$(CC) $(CFLAGS) $^ -o $@

# Prefetch only version
$(TARGET_PREFETCH): $(SOURCES)
	$(CC) $(CFLAGS) -DENABLE_PREFETCHI $^ -o $@

# Performance monitoring only version  
$(TARGET_PERF): $(SOURCES)
	$(CC) $(CFLAGS) -DPERF_COLLECT $^ -o $@

# Both prefetch and performance monitoring version
$(TARGET_BOTH): $(SOURCES)
	$(CC) $(CFLAGS) -DENABLE_PREFETCHI -DPERF_COLLECT $^ -o $@

clean:
	rm -f $(TARGET_BASE) $(TARGET_PREFETCH) $(TARGET_PERF) $(TARGET_BOTH)

help:
	@echo "Available targets:"
	@echo "  all                    - Build all four versions (default)"
	@echo "  $(TARGET_BASE)         - Basic version (no flags)"
	@echo "  $(TARGET_PREFETCH)     - With prefetching enabled"
	@echo "  $(TARGET_PERF)         - With performance monitoring"
	@echo "  $(TARGET_BOTH)         - With both prefetching and perf monitoring"
	@echo "  clean                  - Remove all built binaries"
	@echo "  help                   - Show this help message"
	@echo ""
	@echo "Usage examples:"
	@echo "  make                   # Build all versions"
	@echo "  make $(TARGET_PREFETCH)  # Build only prefetch version"
	@echo "  ./$(TARGET_BASE) 1 4096        # Run basic version"
	@echo "  ./$(TARGET_BOTH) 1 4096        # Run full-featured version"
