/* Map the existing read-only scheduler clock into an ELF-reserved BSS range.
 * No executable bytes, application data, or mappings outside that reservation
 * are changed. Compile as a small LD_PRELOAD DSO for the selected MongoDB ELF.
 */
#define _GNU_SOURCE
#include <cpuid.h>
#include <elf.h>
#include <fcntl.h>
#include <stdint.h>
#include <string.h>
#include <sys/auxv.h>
#include <sys/mman.h>
#include <unistd.h>

#define ARRAY_BYTES 262144UL
static void note(const char *text,size_t length) {
    while(length) {
        ssize_t sent=write(2,text,length);
        if(sent<=0)return;
        text+=sent;length-=(size_t)sent;
    }
}
static void fail(void) {
    static const char message[]="prefetchit hybrid clock mapping rejected\n";
    note(message,sizeof(message)-1);
    _exit(126);
}
static void exact(int fd,void *to,size_t n,off_t offset) {
    if (pread(fd,to,n,offset)!=(ssize_t)n) fail();
}
__attribute__((constructor)) static void install(void) {
    Elf64_Ehdr eh;Elf64_Shdr sections[256];Elf64_Phdr programs[128];
    char names[65536];Elf64_Shdr *clock=0,*state=0,*sites=0;uintptr_t bias=0;
    unsigned a,b,c,d;
    int fd=open("/proc/self/exe",O_RDONLY|O_CLOEXEC);if (fd<0) fail();
    exact(fd,&eh,sizeof(eh),0);
    if (memcmp(eh.e_ident,"\177ELF\2\1",6) || eh.e_machine!=EM_X86_64 ||
        (eh.e_type!=ET_EXEC && eh.e_type!=ET_DYN) ||
        !eh.e_shnum || eh.e_shnum>256 || eh.e_shstrndx>=eh.e_shnum ||
        eh.e_shentsize!=sizeof(*sections) || !eh.e_phnum || eh.e_phnum>128 ||
        eh.e_phentsize!=sizeof(*programs)) fail();
    exact(fd,sections,eh.e_shnum*sizeof(*sections),eh.e_shoff);
    exact(fd,programs,eh.e_phnum*sizeof(*programs),eh.e_phoff);
    size_t bytes=sections[eh.e_shstrndx].sh_size;
    if (!bytes || bytes>sizeof(names)) fail();
    exact(fd,names,bytes,sections[eh.e_shstrndx].sh_offset);close(fd);
    if (names[bytes-1]) fail();
    for (unsigned i=0;i<eh.e_shnum;i++) {
        if (sections[i].sh_name>=bytes) fail();
        const char *name=names+sections[i].sh_name;
        if (!strcmp(name,".prefetch_clock")) { if(clock)fail();clock=&sections[i]; }
        if (!strcmp(name,".prefetch_state")) { if(state)fail();state=&sections[i]; }
        if (!strcmp(name,".prefetch_sites")) { if(sites)fail();sites=&sections[i]; }
    }
    /* Container entrypoint, privilege-drop helper and Mongo shell inherit
     * LD_PRELOAD too. They have no reserved sections and need no clock. */
    if (!clock && !state && !sites)return;
    if (!__get_cpuid_count(7,0,&a,&b,&c,&d) || !(c&(1U<<22))) fail(); /* RDPID */
    if (!__get_cpuid_count(7,1,&a,&b,&c,&d) || !(d&(1U<<14))) fail(); /* PREFETCHI */
    if (!__get_cpuid(0x80000001,&a,&b,&c,&d) || !(d&(1U<<27))) fail(); /* RDTSCP */
    if (!clock || !state || clock->sh_type!=SHT_NOBITS || state->sh_type!=SHT_NOBITS ||
        clock->sh_flags!=(SHF_ALLOC|SHF_WRITE) || state->sh_flags!=(SHF_ALLOC|SHF_WRITE) ||
        clock->sh_size!=ARRAY_BYTES || state->sh_size!=ARRAY_BYTES ||
        clock->sh_addr%4096 || state->sh_addr!=clock->sh_addr+ARRAY_BYTES) fail();
    if (!sites || sites->sh_type!=SHT_NOBITS || sites->sh_flags!=(SHF_ALLOC|SHF_WRITE) ||
        sites->sh_addr!=clock->sh_addr+2*ARRAY_BYTES || !sites->sh_size ||
        sites->sh_size%4096 || sites->sh_size>1048576)fail();
    unsigned phdrs=0,reservations=0;
    for (unsigned i=0;i<eh.e_phnum;i++) {
        Elf64_Phdr *p=&programs[i];
        if (p->p_type==PT_PHDR) {bias=getauxval(AT_PHDR)-p->p_vaddr;phdrs++;}
        if (p->p_type==PT_LOAD && p->p_vaddr==clock->sh_addr &&
            p->p_memsz==2*ARRAY_BYTES+sites->sh_size && p->p_filesz==0 && p->p_flags==(PF_R|PF_W)) reservations++;
    }
    if(phdrs!=1 || reservations!=1 || getauxval(AT_PHNUM)!=eh.e_phnum)fail();
    void *wanted=(void *)(bias+clock->sh_addr);
    fd=open("/dev/prefetchit_sched_clock",O_RDONLY|O_CLOEXEC);if(fd<0)fail();
    void *mapped=mmap(wanted,ARRAY_BYTES,PROT_READ,MAP_SHARED|MAP_FIXED,fd,0);close(fd);
    if(mapped!=wanted)fail();
    volatile uint64_t *slots=mapped;
    for(unsigned i=0;i<4096;i++)if(slots[8*i+7]!=2)fail();
    static const char success[]="prefetchit hybrid clock mapped: ABI 2, read-only\n";
    note(success,sizeof(success)-1);
}
