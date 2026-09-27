// SPDX-License-Identifier: GPL-2.0
/* Experimental x86-64 switch-in code prefetch. No user dereferences in hook. */
#include <linux/capability.h>
#include <linux/kprobes.h>
#include <linux/percpu.h>
#include <asm/msr.h>
#include <linux/fs.h>
#include <linux/highmem.h>
#include <linux/hrtimer.h>
#include <linux/miscdevice.h>
#include <linux/mm.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/pid.h>
#include <linux/rcupdate.h>
#include <linux/sched/mm.h>
#include <linux/sched/signal.h>
#include <linux/slab.h>
#include <linux/tracepoint.h>
#include <linux/uaccess.h>
#include <asm/ptrace.h>
#include "wake_prefetch.h"

#ifndef CONFIG_X86_64
#error "wake_prefetch requires x86-64"
#endif

struct profile {
	s32 syscall_nr;
	u32 count;
	u64 ip_start, ip_end;
	void *aliases[WPF_MAX_LINES];
};

struct plan {
	struct pid *tgid;
	struct mm_struct *mm;
	u32 mode, count, pinned;
	u8 gap, group, split, hint, diagnostic;
	u32 interval_ns;
	u8 batch, max_age_us;
	u64 generation;
	struct profile profiles[WPF_MAX_PROFILES];
	struct page *pages[WPF_MAX_PROFILES * WPF_MAX_LINES];
};

static struct plan __rcu *active;
static DEFINE_MUTEX(config_lock);
static DEFINE_MUTEX(registration_lock);
static atomic_t opened = ATOMIC_INIT(0);
/* No shared counter cache line on the scheduler path. */
struct local_state {
	u64 matched, issued;
	struct wpf_detail detail;
	/* No pointer escapes an RCU critical section. */
	u64 pending_generation, last_issue;
	pid_t pending_tid;
	u32 pending_profile, sample_line;
	bool sample_post;
	struct hrtimer timer;
	struct wpf_waves waves;
	u64 wave_generation, wave_start;
	pid_t wave_tid;
	u32 wave_profile, cursor;
	int cpu;
};
static DEFINE_PER_CPU(struct local_state, local);
static u64 generation;
static bool finish_registered;
static struct kprobe finish_probe;
static struct tracepoint *switch_tp;

static void free_plan(struct plan *p)
{
	u32 i;
	if (!p)
		return;
	for (i = 0; i < p->pinned; ++i)
		unpin_user_page(p->pages[i]);
	if (p->mm)
		mmdrop(p->mm);
	put_pid(p->tgid);
	kfree(p);
}

static void replace_plan(struct plan *new)
{
	struct plan *old;
	mutex_lock(&config_lock);
	old = rcu_dereference_protected(active, lockdep_is_held(&config_lock));
	rcu_assign_pointer(active, new);
	synchronize_rcu();
	free_plan(old);
	mutex_unlock(&config_lock);
}

static void histogram(u64 *bins, u64 ticks)
{
	static const u32 limits[WPF_HIST_BINS - 1] = {
		64, 96, 128, 192, 256, 384, 512, 768,
		1024, 1536, 2048, 4096, 8192, 16384, 32768
	};
	u32 i;
	for (i = 0; i < WPF_HIST_BINS - 1 && ticks >= limits[i]; ++i)
		;
	bins[i]++;
}

/* Diagnostic data load, not an instruction fetch or cache-level oracle.
 * No diagnostic is enabled in performance comparisons. */
static u64 sample_latency(void *addr)
{
	u64 before, after;
	asm volatile("lfence" ::: "memory");
	before = rdtsc_ordered();
	asm volatile("movb (%0), %%al\n\tlfence" : : "r" (addr) : "rax", "memory");
	after = rdtsc_ordered();
	return after - before;
}

static void emit(struct plan *p, struct profile *q, u32 start, u32 end)
{
	u32 j;
	for (j = start; j < end; ++j) {
		void *addr = READ_ONCE(q->aliases[j]);
		/* Select the hint in both modes, preserving the same control path.
		 * Distinct asm comments prevent merging NOP cases ahead of hint choice. */
		if (p->hint == 1) {
			if (p->mode == WPF_MODE_NOP)
				asm volatile("nopl (%0) # nop_t0" : : "r" (addr));
			else
				asm volatile("prefetcht0 (%0)" : : "r" (addr));
		} else if (p->hint == 2) {
			if (p->mode == WPF_MODE_NOP)
				asm volatile("nopl (%0) # nop_nta" : : "r" (addr));
			else
				asm volatile("prefetchnta (%0)" : : "r" (addr));
		} else {
			if (p->mode == WPF_MODE_NOP)
				asm volatile("nopl (%0) # nop_t1" : : "r" (addr));
			else
				asm volatile("prefetcht1 (%0)" : : "r" (addr));
		}
		if (p->gap && ((j + 1) & (p->group - 1)) == 0 && j + 1 < end) {
			if (p->gap == 4)
				asm volatile(".rept 4; nop; .endr" ::: "memory");
			else
				asm volatile(".rept 16; nop; .endr" ::: "memory");
		}
	}
}

/* Pinned hard timer: bounded work, no allocation or user address access.
 * Every callback revalidates registration AND the currently running thread.
 * on_switch invalidates it even when the next task is in the same process. */
static enum hrtimer_restart wave_tick(struct hrtimer *timer)
{
	struct local_state *s = container_of(timer, struct local_state, timer);
	struct plan *p;
	struct profile *q;
	u64 age;
	u32 end;
	enum hrtimer_restart restart = HRTIMER_NORESTART;
	rcu_read_lock();
	p = rcu_dereference(active);
	if (!p || !s->wave_generation || p->generation != s->wave_generation)
		goto stop;
	s->waves.callbacks++;
	if (s->cpu != raw_smp_processor_id() || task_pid_nr(current) != s->wave_tid ||
	    task_tgid(current) != p->tgid || READ_ONCE(current->mm) != p->mm) {
		s->waves.wrong_task++;
		goto stop;
	}
	age = ktime_get_ns() - s->wave_start;
	if (age >= (u64)p->max_age_us * 1000) {
		s->waves.expired++;
		goto stop;
	}
	q = &p->profiles[s->wave_profile];
	end = min_t(u32, s->cursor + p->batch, q->count);
	emit(p, q, s->cursor, end);
	s->issued += end - s->cursor;
	s->waves.lines += end - s->cursor;
	s->waves.emitted++;
	s->waves.age[min_t(u64, age / 2000, 15)]++;
	s->cursor = end;
	if (end < q->count) {
		/* Schedule from now: a delayed interrupt must not cause a burst
		 * of catch-up callbacks or unbounded IRQ work. */
		hrtimer_set_expires(timer, ktime_add_ns(ktime_get(), p->interval_ns));
		restart = HRTIMER_RESTART;
		goto out;
	}
stop:
	s->wave_generation = 0;
out:
	rcu_read_unlock();
	return restart;
}

static void cancel_waves(void)
{
	int cpu;
	/* Called only after active=NULL and its RCU grace period. No new
	 * timer can be started; wait out callbacks before unload/reopen. */
	for_each_possible_cpu(cpu)
		hrtimer_cancel(&per_cpu_ptr(&local, cpu)->timer);
}

/* Entry here has a valid current and stack, after the architectural switch.
 * __switch_to itself explicitly forbids kprobes and is never probed. */
static int finish_switch(struct kprobe *probe, struct pt_regs *regs)
{
	struct local_state *s = this_cpu_ptr(&local);
	struct plan *p;
	struct profile *q;
	u64 expected = s->pending_generation, arrived;
	if (!expected)
		return 0;
	s->pending_generation = 0;
	arrived = s->sample_post ? rdtsc_ordered() : 0;
	rcu_read_lock();
	p = rcu_dereference(active);
	if (!p || p->generation != expected || task_pid_nr(current) != s->pending_tid ||
	    task_tgid(current) != p->tgid || READ_ONCE(current->mm) != p->mm) {
		s->detail.cancelled++;
		goto out;
	}
	q = &p->profiles[s->pending_profile];
	if (s->sample_post) {
		histogram(s->detail.lead, arrived - s->last_issue);
		s->detail.lead_samples++;
		histogram(s->detail.post, sample_latency(q->aliases[s->sample_line]));
		s->detail.post_samples++;
	}
	if (p->split && q->count > p->split) {
		emit(p, q, p->split, q->count);
		s->issued += q->count - p->split;
		s->detail.second_switches++;
		s->detail.second_lines += q->count - p->split;
	}
out:
	rcu_read_unlock();
	return 0;
}
NOKPROBE_SYMBOL(finish_switch);

static void on_switch(void *unused, bool preempt, struct task_struct *prev,
		      struct task_struct *next, unsigned int prev_state)
{
	struct plan *p;
	struct pt_regs *regs;
	struct local_state *s = this_cpu_ptr(&local);
	u32 i;
	rcu_read_lock();
	p = rcu_dereference(active);
	if (s->wave_generation) {
		if (p && s->wave_generation == p->generation)
			s->waves.cancelled++;
		s->wave_generation = 0;
		/* Scheduler tracepoint and this CPU's hard timer cannot execute
		 * concurrently. Cancellation here never waits for a callback. */
		hrtimer_try_to_cancel(&s->timer);
	}
	if (s->pending_generation) {
		if (p && s->pending_generation == p->generation)
			s->detail.cancelled++;
		s->pending_generation = 0;
	}
	/* Holding pid/mm references prevents reuse, including across exec(). */
	if (!p || task_tgid(next) != p->tgid || READ_ONCE(next->mm) != p->mm)
		goto out;
	regs = task_pt_regs(next);
	if (!user_mode(regs))
		goto out;
	for (i = 0; i < p->count; ++i) {
		struct profile *q = &p->profiles[i];
		u32 end;
		bool sample;
		if (q->syscall_nr != -1 && regs->orig_ax != q->syscall_nr)
			continue;
		if (q->ip_end && (regs->ip < q->ip_start || regs->ip >= q->ip_end))
			continue;
		s->matched++;
		end = p->batch ? min_t(u32, p->batch, q->count) :
			(p->split ? min_t(u32, p->split, q->count) : q->count);
		if (p->batch)
			s->wave_start = ktime_get_ns();
		sample = p->diagnostic && (s->matched & 63) == 0;
		s->sample_line = (s->matched >> 6) % end;
		if (sample && p->diagnostic == 1) {
			histogram(s->detail.pre, sample_latency(q->aliases[s->sample_line]));
			s->detail.pre_samples++;
		}
		emit(p, q, 0, end);
		s->issued += end;
		s->sample_post = sample && p->diagnostic == 2;
		if (s->sample_post)
			s->last_issue = rdtsc_ordered();
		if ((p->split && end < q->count) || s->sample_post) {
			s->pending_tid = task_pid_nr(next);
			s->pending_profile = i;
			s->pending_generation = p->generation;
		}
		if (p->batch && end < q->count) {
			s->wave_tid = task_pid_nr(next);
			s->wave_profile = i;
			s->cursor = end;
			s->wave_generation = p->generation;
			hrtimer_start(&s->timer, ns_to_ktime(p->interval_ns),
				      HRTIMER_MODE_REL_PINNED_HARD);
		}
		break; /* first matching profile; both phases combined <= 64 lines */
	}
out:
	rcu_read_unlock();
}

static int make_plan(const struct wpf_config *c, struct plan **result)
{
	struct task_struct *task;
	struct pid *pid;
	struct mm_struct *mm;
	struct plan *p;
	int err = -EINVAL;
	u32 i, j;

	if ((c->version != WPF_VERSION && c->version != WPF_VERSION_EMISSION &&
	     c->version != WPF_VERSION_WAVES) ||
	    c->mode > WPF_MODE_T1 || c->pid <= 0 ||
	    !c->profile_count || c->profile_count > WPF_MAX_PROFILES ||
	    (c->version == WPF_VERSION && c->reserved[0]) ||
	    (c->version != WPF_VERSION_WAVES && c->reserved[1]) ||
	    c->reserved[1] >> 48 ||
	    c->reserved[0] >> 40)
		return -EINVAL;
	pid = find_get_pid(c->pid);
	task = get_pid_task(pid, PIDTYPE_PID);
	put_pid(pid);
	if (!task)
		return -ESRCH;
	mm = get_task_mm(task);
	if (!mm) {
		put_task_struct(task);
		return -EINVAL;
	}
	p = kzalloc(sizeof(*p), GFP_KERNEL);
	if (!p) {
		mmput(mm);
		put_task_struct(task);
		return -ENOMEM;
	}
	p->tgid = get_pid(task_tgid(task));
	p->mm = mm;
	mmgrab(mm); /* mm identity, not a permanent mm_users reference */
	put_task_struct(task);
	p->mode = c->mode;
	p->count = c->profile_count;
	p->gap = c->reserved[0];
	p->group = c->reserved[0] >> 8;
	p->split = c->reserved[0] >> 16;
	p->hint = c->reserved[0] >> 24;
	p->diagnostic = c->reserved[0] >> 32;
	p->interval_ns = c->reserved[1];
	p->batch = c->reserved[1] >> 32;
	p->max_age_us = c->reserved[1] >> 40;
	if (c->version == WPF_VERSION)
		p->group = 1;
	if ((p->gap != 0 && p->gap != 4 && p->gap != 16) ||
	    !p->group || p->group > 16 || !is_power_of_2(p->group) ||
	    p->split >= WPF_MAX_LINES || p->hint > 2 || p->diagnostic > 2)
		goto fail;
	if (c->version == WPF_VERSION_WAVES &&
	    (p->interval_ns < 1000 || p->interval_ns > 16000 ||
	     !p->batch || p->batch > 16 || p->max_age_us < 4 || p->max_age_us > 64 ||
	     p->split || p->gap || p->diagnostic))
		goto fail;
	p->generation = ++generation;
	for (i = 0; i < c->profile_count; ++i) {
		const struct wpf_profile *in = &c->profiles[i];
		struct profile *out = &p->profiles[i];
		if (!in->count || in->count > WPF_MAX_LINES || in->syscall_nr < -1 ||
		    ((in->ip_start || in->ip_end) && in->ip_start >= in->ip_end))
			goto fail;
		out->count = in->count;
		out->syscall_nr = in->syscall_nr;
		out->ip_start = in->ip_start;
		out->ip_end = in->ip_end;
		for (j = 0; j < in->count; ++j) {
			unsigned long addr = in->lines[j];
			struct vm_area_struct *vma;
			struct page *page = NULL;
			long n;
			int locked = 1;
			err = -EINVAL;
			if (!addr || (addr & 63) || addr >= TASK_SIZE_MAX)
				goto fail;
			mmap_read_lock(mm);
			vma = find_vma(mm, addr);
			/* Only fixed, read-only, executable file mappings are supported. */
			if (!vma || addr < vma->vm_start || !vma->vm_file ||
			    !(vma->vm_flags & VM_EXEC) ||
			    (vma->vm_flags & (VM_WRITE | VM_IO | VM_PFNMAP))) {
				mmap_read_unlock(mm);
				goto fail;
			}
			n = pin_user_pages_remote(mm, addr & PAGE_MASK, 1,
						 FOLL_LONGTERM, &page, &locked);
			if (locked)
				mmap_read_unlock(mm);
			if (n != 1) {
				err = n < 0 ? n : -EFAULT;
				goto fail;
			}
			p->pages[p->pinned++] = page;
			if (!page_address(page)) {
				err = -EFAULT;
				goto fail;
			}
			out->aliases[j] = (char *)page_address(page) + offset_in_page(addr);
		}
	}
	mmput(mm);
	*result = p;
	return 0;
fail:
	mmput(mm);
	free_plan(p);
	return err;
}

static long control(struct file *file, unsigned int cmd, unsigned long arg)
{
	struct wpf_config *c;
	struct plan *p;
	struct wpf_stats s = {0};
	struct wpf_detail detail = {0};
	struct wpf_waves waves = {0};
	int err, cpu;
	u32 i;
	if (!capable(CAP_SYS_ADMIN))
		return -EPERM;
	if (cmd == WPF_STATS) {
		for_each_possible_cpu(cpu) {
			struct local_state *state = per_cpu_ptr(&local, cpu);
			s.matched_switches += READ_ONCE(state->matched);
			s.issued_lines += READ_ONCE(state->issued);
		}
		return copy_to_user((void __user *)arg, &s, sizeof(s)) ? -EFAULT : 0;
	}
	if (cmd == WPF_DETAIL) {
		for_each_possible_cpu(cpu) {
			struct wpf_detail *d = &per_cpu_ptr(&local, cpu)->detail;
			detail.second_switches += READ_ONCE(d->second_switches);
			detail.second_lines += READ_ONCE(d->second_lines);
			detail.cancelled += READ_ONCE(d->cancelled);
			detail.pre_samples += READ_ONCE(d->pre_samples);
			detail.post_samples += READ_ONCE(d->post_samples);
			detail.lead_samples += READ_ONCE(d->lead_samples);
			for (i = 0; i < WPF_HIST_BINS; ++i) {
				detail.pre[i] += READ_ONCE(d->pre[i]);
				detail.post[i] += READ_ONCE(d->post[i]);
				detail.lead[i] += READ_ONCE(d->lead[i]);
			}
		}
		return copy_to_user((void __user *)arg, &detail, sizeof(detail)) ? -EFAULT : 0;
	}
	if (cmd == WPF_WAVES) {
		for_each_possible_cpu(cpu) {
			struct wpf_waves *w = &per_cpu_ptr(&local, cpu)->waves;
			waves.callbacks += READ_ONCE(w->callbacks);
			waves.emitted += READ_ONCE(w->emitted);
			waves.lines += READ_ONCE(w->lines);
			waves.cancelled += READ_ONCE(w->cancelled);
			waves.expired += READ_ONCE(w->expired);
			waves.wrong_task += READ_ONCE(w->wrong_task);
			for (i = 0; i < 16; ++i)
				waves.age[i] += READ_ONCE(w->age[i]);
		}
		return copy_to_user((void __user *)arg, &waves, sizeof(waves)) ? -EFAULT : 0;
	}
	if (cmd != WPF_CONFIG)
		return -ENOTTY;
	/* One immutable registration per open, making counter deltas unambiguous. */
	mutex_lock(&registration_lock);
	if (file->private_data) {
		err = -EBUSY;
		goto unlock;
	}
	c = memdup_user((void __user *)arg, sizeof(*c));
	if (IS_ERR(c)) {
		err = PTR_ERR(c);
		goto unlock;
	}
	err = make_plan(c, &p);
	kfree(c);
	if (err)
		goto unlock;
	/* No active registration; clear only counters here. Pending state is
	 * invalidated by generation, avoiding a cross-CPU write race. */
	for_each_possible_cpu(cpu) {
		struct local_state *state = per_cpu_ptr(&local, cpu);
		WRITE_ONCE(state->matched, 0);
		WRITE_ONCE(state->issued, 0);
		/* Old completion probes have been unregistered on close. */
		memset(&state->detail, 0, sizeof(state->detail));
		memset(&state->waves, 0, sizeof(state->waves));
	}
	if (p->split || p->diagnostic == 2) {
		memset(&finish_probe, 0, sizeof(finish_probe));
		finish_probe.symbol_name = "finish_task_switch.isra.0";
		finish_probe.pre_handler = finish_switch;
		err = register_kprobe(&finish_probe);
		if (err) {
			free_plan(p);
			goto unlock;
		}
		finish_registered = true;
	}
	replace_plan(p);
	file->private_data = p;
unlock:
	mutex_unlock(&registration_lock);
	return err;
}

static int device_open(struct inode *inode, struct file *file)
{
	if (!capable(CAP_SYS_ADMIN))
		return -EPERM;
	if (atomic_cmpxchg(&opened, 0, 1))
		return -EBUSY;
	file->private_data = NULL;
	return 0;
}

static int device_release(struct inode *inode, struct file *file)
{
	replace_plan(NULL);
	cancel_waves();
	if (finish_registered) {
		unregister_kprobe(&finish_probe);
		finish_registered = false;
	}
	atomic_set(&opened, 0);
	return 0;
}

static const struct file_operations operations = {
	.owner = THIS_MODULE,
	.open = device_open,
	.release = device_release,
	.unlocked_ioctl = control,
	.llseek = no_llseek,
};

static struct miscdevice device = {
	.minor = MISC_DYNAMIC_MINOR,
	.name = "wake_prefetch",
	.fops = &operations,
	.mode = 0600,
};

static void find_switch(struct tracepoint *tp, void *unused)
{
	if (!strcmp(tp->name, "sched_switch"))
		switch_tp = tp;
}

static int __init wpf_init(void)
{
	int err, cpu;
	for_each_possible_cpu(cpu) {
		struct local_state *s = per_cpu_ptr(&local, cpu);
		s->cpu = cpu;
		hrtimer_init(&s->timer, CLOCK_MONOTONIC, HRTIMER_MODE_REL_PINNED_HARD);
		s->timer.function = wave_tick;
	}
	for_each_kernel_tracepoint(find_switch, NULL);
	if (!switch_tp)
		return -ENOENT;
	err = tracepoint_probe_register(switch_tp, on_switch, NULL);
	if (err)
		return err;
	err = misc_register(&device);
	if (err) {
		tracepoint_probe_unregister(switch_tp, on_switch, NULL);
		tracepoint_synchronize_unregister();
	}
	return err;
}

static void __exit wpf_exit(void)
{
	misc_deregister(&device);
	tracepoint_probe_unregister(switch_tp, on_switch, NULL);
	tracepoint_synchronize_unregister();
	replace_plan(NULL);
	cancel_waves();
}

module_init(wpf_init);
module_exit(wpf_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Experimental opt-in bounded switch-in code prefetch");
