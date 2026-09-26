"""Direct callee reached before any other control transfer from function entry.

Calls and unconditional tail jumps qualify. Conditional/indirect branches and
returns terminate the search, so error-path calls are not mistaken for ordinary
wrapper forwarding. This is a bounded static fact, not a branch probability.
"""
import re,subprocess

def bounded_entry_callee(binary,entry,size,bounds,max_bytes=256):
    """Same conservative rule for an exact, possibly stripped, unwind entry."""
    if not 0<size<=max_bytes:return None
    text=subprocess.check_output(['objdump','-d','--insn-width=16',
        '--start-address='+hex(entry),'--stop-address='+hex(entry+size),str(binary)],text=True)
    first=True
    for line in text.splitlines():
        m=re.match(r'^\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*(.*)$',line)
        if not m:continue
        address=int(m[1],16)
        if first:
            assert address==entry,'decoder did not begin at the inspected entry'
            first=False
        words=m[3].strip().split()
        while words and words[0] in {'bnd','rep','repz','repnz','data16','addr32','notrack'}:words.pop(0)
        if not words:continue
        if not re.fullmatch(r'(?:callq?|j[a-z]+|loop[a-z]*|retq?|iretq?|ud2|hlt|int3?|syscall|sysenter)',words[0]):continue
        direct=re.match(r'^(?:callq?|jmpq?)\s+(?:0x)?([0-9a-f]+)\b',' '.join(words))
        if direct:
            target=int(direct[1],16)
            if target in bounds and target!=entry:return target
        return None
    return None

def entry_callees(binary,bounds,max_bytes=256):
    result={};current=None
    proc=subprocess.Popen(['objdump','-d','--insn-width=16',str(binary)],stdout=subprocess.PIPE,text=True)
    for line in proc.stdout:
        head=re.match(r'^([0-9a-f]+) <',line)
        if head:
            address=int(head[1],16);size=bounds.get(address,0)
            current=address if 0<size<=max_bytes else None
            continue
        if current is None:continue
        m=re.match(r'^\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*(.*)$',line)
        if not m:continue
        if int(m[1],16)>=current+bounds[current]:current=None;continue
        op=m[3].strip();words=op.split()
        while words and words[0] in {'bnd','rep','repz','repnz','data16','addr32','notrack'}:words.pop(0)
        if not words:continue
        if not re.fullmatch(r'(?:callq?|j[a-z]+|loop[a-z]*|retq?|iretq?|ud2|hlt|int3?|syscall|sysenter)',words[0]):continue
        direct=re.match(r'^(?:callq?|jmpq?)\s+(?:0x)?([0-9a-f]+)\b',' '.join(words))
        if direct:
            target=int(direct[1],16)
            if target in bounds and target!=current:result[current]=target
        current=None
    assert proc.wait()==0
    return result
