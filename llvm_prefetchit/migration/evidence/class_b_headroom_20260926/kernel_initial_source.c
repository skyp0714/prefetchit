// SPDX-License-Identifier: GPL-2.0
/* Experimental x86-64 switch-in code prefetch. No user dereferences in hook. */
#include <linux/capability.h>
#include <linux/fs.h>
#include <linux/highmem.h>
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
	struct profile profiles[WPF_MAX_PROFILES];
	struct page *pages[WPF_MAX_PROFILES * WPF_MAX_LINES];
};

static struct plan __rcu *active;
static DEFINE_MUTEX(config_lock);
static atomic_t opened = ATOMIC_INIT(0);
static atomic64_t matched = ATOMIC64_INIT(0);
static atomic64_t issued = ATOMIC64_INIT(0);
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

static void on_switch(void *unused, bool preempt, struct task_struct *prev,
		      struct task_struct *next, unsigned int prev_state)
{
	struct plan *p;
	struct pt_regs *regs;
	u32 i, j;

	rcu_read_lock();
	p = rcu_dereference(active);
	/* Holding pid/mm references prevents reuse, including across exec(). */
	if (!p || task_tgid(next) != p->tgid || READ_ONCE(next->mm) != p->mm)
		goto out;
	regs = task_pt_regs(next);
	if (!user_mode(regs))
		goto out;
	for (i = 0; i < p->count; ++i) {
		struct profile *q = &p->profiles[i];
		if (q->syscall_nr != -1 && regs->orig_ax != q->syscall_nr)
			continue;
		if (q->ip_end && (regs->ip < q->ip_start || regs->ip >= q->ip_end))
			continue;
		atomic64_inc(&matched);
		for (j = 0; j < q->count; ++j) {
			void *addr = READ_ONCE(q->aliases[j]);
			if (p->mode == WPF_MODE_T1)
				asm volatile("prefetcht1 (%0)" : : "r" (addr));
			else
				/* Address load/loop retained; no memory access or fill. */
				asm volatile("nopl (%0)" : : "r" (addr));
		}
		atomic64_add(q->count, &issued);
		break; /* first matching profile wins; total burst never exceeds 64 */
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

	if (c->version != WPF_VERSION || c->mode > WPF_MODE_T1 || c->pid <= 0 ||
	    !c->profile_count || c->profile_count > WPF_MAX_PROFILES ||
	    c->reserved[0] || c->reserved[1])
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
	struct wpf_stats s;
	int err;
	if (!capable(CAP_SYS_ADMIN))
		return -EPERM;
	if (cmd == WPF_STATS) {
		s.matched_switches = atomic64_read(&matched);
		s.issued_lines = atomic64_read(&issued);
		return copy_to_user((void __user *)arg, &s, sizeof(s)) ? -EFAULT : 0;
	}
	if (cmd != WPF_CONFIG)
		return -ENOTTY;
	/* One immutable registration per open, making counter deltas unambiguous. */
	if (file->private_data)
		return -EBUSY;
	c = memdup_user((void __user *)arg, sizeof(*c));
	if (IS_ERR(c))
		return PTR_ERR(c);
	err = make_plan(c, &p);
	kfree(c);
	if (err)
		return err;
	atomic64_set(&matched, 0);
	atomic64_set(&issued, 0);
	replace_plan(p);
	file->private_data = p;
	return 0;
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
	int err;
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
}

module_init(wpf_init);
module_exit(wpf_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Experimental opt-in bounded switch-in code prefetch");
