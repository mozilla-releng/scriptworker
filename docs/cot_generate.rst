Chain of Trust Artifact Generation
----------------------------------

Each chain-of-trust-enabled taskcluster worker generates and uploads a chain of trust artifact after each task.  This artifact contains details about the task, worker, and artifacts, and is signed by the embedded GPG key.

Embedded GPG keys
~~~~~~~~~~~~~~~~~

Each supported taskcluster ``workerType`` has an embedded gpg keypair.
These are the second factor.

``docker-worker`` has the gpg privkey embedded in the AMI, inaccessible
to tasks run inside the docker container. The gpg keypair is unique per
AMI.

``generic-worker`` can embed the gpg privkey into the AMI for EC2
instances, or into the system directories for hardware. This are
permissioned so the task user doesn't have access to it.

``taskcluster-worker`` will need the ability to embed a privkey when we
start using them for tier1 tasks in production.

Chain-of-Trust-enabled ``scriptworker`` workers each have a unique gpg
keypair.

For ``docker-worker``, ``generic-worker``, and ``taskcluster-worker``,
we have a set of pubkeys that are valid per worker implementation. For
``scriptworker``, we have a set of trusted gpg keys; each
``scriptworker`` gpg pubkey is signed by a trusted gpg key.

Chain of Trust artifacts
~~~~~~~~~~~~~~~~~~~~~~~~

After the task finishes, the worker creates a chain of trust json blob,
gpg signs it, then uploads it as ``public/chainOfTrust.json.asc``. It
looks like

.. code:: python

        {
          "artifacts": {
            "path/to/artifact": {
              "sha256": "abcd1234"
            },
            ...
          },
          "chainOfTrustVersion": 1,
          "environment": {
            # worker-impl specific stuff, like ec2 instance id, ip
          },
          "runId": 0,
          "task": {
            # task defn
          },
          "taskId": "...",
          "workerGroup": "...",
          "workerId": "..."
        }

-  The v1 chain-of-trust json artifact schema is viewable `here
   <https://github.com/mozilla-releng/scriptworker/blob/master/scriptworker/data/cot_v1_schema.json>`__.
-  This is a real :download:`example artifact <_static/chainOfTrust.json.asc>`.
