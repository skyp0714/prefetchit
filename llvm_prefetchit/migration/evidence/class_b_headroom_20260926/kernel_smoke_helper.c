
#include <signal.h>
#include <stdio.h>
#include <unistd.h>
static volatile sig_atomic_t change;
static void handler(int n) { change = 1; }
int main(void) {
    signal(SIGUSR1, handler);
    puts("ready"); fflush(stdout);
    for (;;) {
        if (change) { execl("/bin/sleep", "sleep", "10", NULL); return 2; }
        usleep(1000);
    }
}
