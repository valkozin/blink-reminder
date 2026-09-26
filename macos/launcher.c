/* The executable inside "Blink Reminder.app".
 *
 * macOS grants the camera to the responsible process. Started by launchd, a bare Python
 * interpreter is its own responsible process, so the permission landed on python3.12 - and
 * any script run the same way by that shared interpreter inherited the camera, unprompted.
 * Starting Python as a child of this bundle makes the bundle responsible instead: the
 * permission belongs to Blink Reminder alone.
 *
 * Built by install.sh, which passes the venv's interpreter as PYTHON. */

#include <errno.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <sys/wait.h>

extern char **environ;
static pid_t child;

static void forward(int sig) {
    if (child > 0) kill(child, sig);
}

int main(int argc, char **argv) {
    char *args[argc + 3];
    args[0] = PYTHON;
    args[1] = "-m";
    args[2] = "blinkreminder";
    for (int i = 1; i < argc; i++) args[i + 2] = argv[i];
    args[argc + 2] = NULL;

    signal(SIGTERM, forward);
    signal(SIGINT, forward);
    signal(SIGHUP, forward);

    int err = posix_spawn(&child, PYTHON, NULL, NULL, args, environ);
    if (err != 0) {
        errno = err;
        perror(PYTHON);
        return 1;
    }
    int status;
    while (waitpid(child, &status, 0) < 0)
        if (errno != EINTR) return 1;
    /* A clean Quit must stay a clean exit: launchd's KeepAlive only restarts on failure. */
    return WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
}
