// SPDX-License-Identifier: GPL-2.0
/* Publish incoming-task scheduling time; no prefetches, timers or user pointers. */
#include <linux/module.h>
#include <linux/miscdevice.h>
#include <linux/fs.h>
#include <linux/mm.h>
#include <linux/tracepoint.h>
#include <linux/sched.h>
#include <linux/vmalloc.h>
#include <asm/msr.h>
#include <asm/tsc.h>

#define SLOTS 4096
#define BYTES (SLOTS * 64UL)
struct slot { u64 until[3], start; u64 padding[4]; };
static struct slot *slots;
static struct tracepoint *switch_tp;
static unsigned int dense_us = 10, medium_us = 20, sparse_us = 40;
static bool flat;
module_param(flat, bool, 0444);
module_param(dense_us, uint, 0444);
module_param(medium_us, uint, 0444);
module_param(sparse_us, uint, 0444);
static u64 offsets[3];

static void on_switch(void *ignored, bool preempt, struct task_struct *prev,
		      struct task_struct *next, unsigned int prev_state)
{
	u64 now = rdtsc_ordered();
	struct slot *s = &slots[raw_smp_processor_id()];
	/* Per-CPU cacheline, no counter shared between CPUs. The tracepoint runs
	 * after next is selected, before the context switch. User-visible age
	 * therefore includes the remaining scheduler path and syscall return. */
	WRITE_ONCE(s->start, now);
	WRITE_ONCE(s->until[0], flat ? U64_MAX : now + offsets[0]);
	WRITE_ONCE(s->until[1], flat ? U64_MAX : now + offsets[1]);
	WRITE_ONCE(s->until[2], flat ? U64_MAX : now + offsets[2]);
}

static int clock_mmap(struct file *file, struct vm_area_struct *vma)
{
	if (vma->vm_pgoff || vma->vm_end - vma->vm_start != BYTES ||
	    vma->vm_flags & (VM_WRITE | VM_EXEC)) return -EINVAL;
	/* Prevent mprotect from granting write/execute later. A VMA holds the
	 * file/module reference, including after close(fd), fork and partial unmap. */
	vm_flags_clear(vma, VM_MAYWRITE | VM_MAYEXEC);
	vm_flags_set(vma, VM_DONTDUMP | VM_DONTEXPAND);
	return remap_vmalloc_range(vma, slots, 0);
}

static const struct file_operations operations = {
	.owner = THIS_MODULE, .mmap = clock_mmap, .llseek = no_llseek,
};
static struct miscdevice device = {
	.minor = MISC_DYNAMIC_MINOR, .name = "prefetchit_sched_clock",
	.fops = &operations, .mode = 0600,
};
static void find_switch(struct tracepoint *tp, void *ignored)
{
	if (!strcmp(tp->name, "sched_switch")) switch_tp = tp;
}
static int __init clock_init(void)
{
	int err;
	if (nr_cpu_ids > SLOTS || !tsc_khz || !boot_cpu_has(X86_FEATURE_RDTSCP) ||
	    !boot_cpu_has(X86_FEATURE_CONSTANT_TSC) || !boot_cpu_has(X86_FEATURE_NONSTOP_TSC) ||
	    !dense_us || dense_us > medium_us || medium_us > sparse_us || sparse_us > 1000)
		return -EINVAL;
	offsets[0] = (u64)tsc_khz * dense_us / 1000;
	offsets[1] = (u64)tsc_khz * medium_us / 1000;
	offsets[2] = (u64)tsc_khz * sparse_us / 1000;
	slots = vmalloc_user(BYTES);
	if (!slots) return -ENOMEM;
	for_each_kernel_tracepoint(find_switch, NULL);
	if (!switch_tp) { err = -ENOENT; goto free; }
	err = tracepoint_probe_register(switch_tp, on_switch, NULL);
	if (err) goto free;
	err = misc_register(&device);
	if (!err) return 0;
	tracepoint_probe_unregister(switch_tp, on_switch, NULL);
	tracepoint_synchronize_unregister();
free:
	vfree(slots); return err;
}
static void __exit clock_exit(void)
{
	misc_deregister(&device);
	tracepoint_probe_unregister(switch_tp, on_switch, NULL);
	tracepoint_synchronize_unregister();
	vfree(slots);
}
module_init(clock_init);
module_exit(clock_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Read-only per-CPU schedule-in TSC for dominator prefetch experiments");
