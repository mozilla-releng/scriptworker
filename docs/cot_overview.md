# Chain of Trust: Overview

Taskcluster is versatile and self-serve, and enables developers to make
automation changes without being blocked on other teams. However, this
freedom presents security concerns around release tasks.

Taskcluster uses scopes as its auth model. These are not leak-proof. To
trigger a valid task graph, you need to have the required scopes. These
same scopes also allow you to trigger an arbitrary task. In the case of
developer testing and debugging, this is helpful. In the case of release
automation, arbitrary tasks can present a problem.

The chain of trust is a second factor that isn't automatically
compromised if scopes are compromised. This chain allows us to trace a
task's request back to the tree.
