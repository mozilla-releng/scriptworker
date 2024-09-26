# Flow of Control

The way a scriptworker runs can be a bit confusing. It involves `scriptworker` itself and its configuration file, a `script` with its own configuration file, multiple processes, and a surprising amount of indirection. The diagram below attempts to show the flow of control. A few things are of special note:

* The initial entrypoint is the `scriptworker` CLI tool.
* When a Task has been verified, the `script` CLI entry point is run in a subprocess, but that will simply provide `scriptworker.client.sync_main` with a few pieces of data (most notably the `async_main` that actually acts on a Task payload) to continue execution from there. This means that there are two processes that have independently imported `scriptworker` code.
* Task success or failure is communicated back to the `scriptworker` CLI tool through the return code of the subprocess.

![scriptworker flow of control](flow_of_control.svg)
