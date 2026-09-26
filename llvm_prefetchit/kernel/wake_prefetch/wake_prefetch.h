/* SPDX-License-Identifier: GPL-2.0 */
#ifndef WAKE_PREFETCH_UAPI_H
#define WAKE_PREFETCH_UAPI_H
#include <linux/ioctl.h>
#include <linux/types.h>

#define WPF_VERSION 1
#define WPF_VERSION_EMISSION 2
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
	 * v1 and reserved[1] must be zero. Hints: T1/T0/NTA = 0/1/2. */
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

#define WPF_CONFIG _IOW('W', 1, struct wpf_config)
#define WPF_STATS _IOR('W', 2, struct wpf_stats)
#define WPF_DETAIL _IOR('W', 3, struct wpf_detail)
#endif
