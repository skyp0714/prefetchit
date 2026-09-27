/* SPDX-License-Identifier: GPL-2.0 */
#ifndef WAKE_PREFETCH_UAPI_H
#define WAKE_PREFETCH_UAPI_H
#include <linux/ioctl.h>
#include <linux/types.h>

#define WPF_VERSION 1
#define WPF_VERSION_EMISSION 2
#define WPF_VERSION_WAVES 3
#define WPF_HIST_BINS 16
#define WPF_MAX_PROFILES 8
#define WPF_MAX_LINES 64
#define WPF_MODE_NOP 0
#define WPF_MODE_T1 1

struct wpf_profile {
	__s32 syscall_nr; /* -1: any; otherwise x86-64 orig_ax */
	__u32 count;
	__u64 ip_start;   /* both zero: any saved user return IP */
	__u64 ip_end;     /* exclusive */
	__u64 lines[WPF_MAX_LINES]; /* runtime user VAs, aligned to 64 bytes */
};

struct wpf_config {
	__u32 version;
	__u32 mode;
	__s32 pid; /* PID in the caller's namespace, identifies a thread group */
	__u32 profile_count;
	/* v2 reserved[0]: gap, group, split, hint, diagnostic in successive bytes.
	 * v1 options must be zero. Hints: T1/T0/NTA = 0/1/2.
	 * v3 reserved[1]: interval_ns (32 bits), batch (8), max_age_us (8).
	 * Waves cannot be combined with split, spacing, or diagnostic loads. */
	__u64 reserved[2];
	struct wpf_profile profiles[WPF_MAX_PROFILES];
};

struct wpf_stats {
	__u64 matched_switches;
	__u64 issued_lines; /* attempts, NOT successful fills */
};

struct wpf_detail {
	__u64 second_switches, second_lines, cancelled;
	__u64 pre_samples, post_samples, lead_samples;
	__u64 pre[WPF_HIST_BINS], post[WPF_HIST_BINS], lead[WPF_HIST_BINS];
};

struct wpf_waves {
	__u64 callbacks, emitted, lines, cancelled, expired, wrong_task;
	/* Delayed emissions by age since next-task selection; 2 us bins,
	 * last bin includes >= 30 us. Not a user instruction-fetch clock. */
	__u64 age[16];
};

#define WPF_CONFIG _IOW('W', 1, struct wpf_config)
#define WPF_STATS _IOR('W', 2, struct wpf_stats)
#define WPF_DETAIL _IOR('W', 3, struct wpf_detail)
#define WPF_WAVES _IOR('W', 4, struct wpf_waves)
#endif
