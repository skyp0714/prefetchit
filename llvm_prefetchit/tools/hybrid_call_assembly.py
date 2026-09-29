"""Register-preserving scheduler-epoch gate for experimental call stubs.

The common path uses RDPID and two per-CPU words. RDTSCP is used only on a
newly observed epoch. Optional hints tolerate preemption/migration races;
this is not an atomic once-per-switch guarantee or a fetch-queue probe.
"""


def saved_state(extra=False):
    lines=['.cfi_def_cfa_offset '+str(56 if extra else 40),
           '.cfi_offset %r10,-24','.cfi_offset %r11,-32','.cfi_offset %rax,-40']
    if extra:lines+=['.cfi_offset %rdx,-48','.cfi_offset %rcx,-56']
    return lines


def push(register,offset):
    return [f'push %{register}', '.cfi_adjust_cfa_offset 8',f'.cfi_offset %{register},{offset}']


def pop(register):
    return [f'pop %{register}', '.cfi_adjust_cfa_offset -8',f'.cfi_restore %{register}']


def restore():
    return pop('rax')+pop('r11')+pop('r10')+['popfq','.cfi_adjust_cfa_offset -8']


def emit(index,row,diagnostic=False):
    prefix=f'pf_call_{index}';defs=[];hints=[];jumps=[]
    def label(suffix):return f'{prefix}_{suffix}'
    def hints_for(kind,targets):
        lines=[]
        for j,target in enumerate(targets):
            name=label(f'{kind}_{j}');dest=name+'_target'
            defs.append(f'{dest} = 0x{target:x};')
            lines += [f'.global {name}',name+':',f'prefetch{kind} {dest}(%rip)']
            hints.append(dict(symbol=name,target=target,kind=kind))
        return lines
    def tail(name):
        name=label(name);jumps.append(name)
        return [f'.global {name}',name+':',f'jmp pf_callee_{index}']
    lines=['pushfq','.cfi_adjust_cfa_offset 8']+push('r10',-24)+push('r11',-32)+push('rax',-40)
    lines += ['rdpid %r10','and $4095,%r10d','shl $6,%r10',
              'lea pf_clock_base(%rip),%r11','mov 24(%r11,%r10),%rax']
    # Both arrays have one 64-byte line for each of 4096 logical CPUs.
    def word(n):return f'{262144+n*8}(%r11,%r10)'
    if diagnostic:lines += [f'incq {word(1)}']
    lines += [f'cmp %rax,{word(0)}',f'je {label("normal")}',
              # Mark this observed epoch before the expensive clock sample.
              # A later switch changes start and causes another check.
              f'mov %rax,{word(0)}']
    lines += push('rdx',-48)+push('rcx',-56)
    lines += ['rdtscp','and $4095,%ecx','shl $6,%rcx','cmp %rcx,%r10',f'jne {label("race")}',
              'shl $32,%rdx','or %rdx,%rax','mov 24(%r11,%r10),%rdx',
              f'cmp %rdx,{word(0)}',f'jne {label("race")}',
              'cmp %rdx,%rax',f'jb {label("race")}',
              'cmp (%r11,%r10),%rax',f'jae {label("late")}']
    if diagnostic:
        # Only qualifying burst ages contribute; all units are TSC ticks.
        lines += [f'incq {word(2)}','sub %rdx,%rax',f'add %rax,{word(5)}',
                  f'cmp %rax,{word(6)}',f'jae {label("max_done")}',f'mov %rax,{word(6)}',label('max_done')+':',
                  'mov (%r11,%r10),%rcx','sub %rdx,%rcx','shr $1,%rcx','cmp %rcx,%rax',
                  f'jae {label("half_done")}',f'incq {word(7)}',label('half_done')+':']
    lines += pop('rcx')+pop('rdx')+restore()+hints_for('it0',row['burst_targets'])+tail('burst_tail')
    lines += [label('race')+':']+saved_state(extra=True)
    if diagnostic:lines += [f'incq {word(4)}']
    lines += [f'jmp {label("epoch_normal")}',label('late')+':']
    if diagnostic:lines += [f'incq {word(3)}']
    lines += [label('epoch_normal')+':']+pop('rcx')+pop('rdx')
    lines += [label('normal')+':']+saved_state()+restore()+hints_for('t1',row['targets'])+tail('normal_tail')
    return lines,defs,hints,jumps
