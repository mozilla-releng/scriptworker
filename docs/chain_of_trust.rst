Chain of Trust
==============

Overview
--------

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

Chain of Trust Generation
-------------------------

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

Chain of Trust Verification
---------------------------

Currently, only chain-of-trust-enabled scriptworker instances verify the chain of trust.  These are tasks like signing, publishing, and submitting updates to the update server.  If the chain of trust is not valid, scriptworker kills the task before it performs any further actions.

The below is how this happens.

.. _decision-task:

Decision Task
~~~~~~~~~~~~~

The decision task is a special task that generates a taskgraph, then submits it to the Taskcluster queue.  This graph contains task definitions and dependencies.  The decision task uploads its generated graph json as an artifact, which can be inspected during chain of trust verification.

Ideally, we would be able to verify the decision task's task definition matches the in-tree settings for its revision; that's `bug 1328719 <https://bugzilla.mozilla.org/show_bug.cgi?id=1328719>`__.  Currently we make do with task inspection and an allowlist of docker image shas that the decision task can run on.

GPG homedir management
~~~~~~~~~~~~~~~~~~~~~~

The chain of trust artifacts are signed, but without marking the gpg
public key as valid, we don't know if it's been signed by a valid worker key.

We have a `github repo of pubkeys <https://github.com/mozilla-releng/cot-gpg-keys>`__.
The latest valid commit is tagged and signed with a trusted gpg key.  More on this in :ref:`gpg-key-management`.

Each scriptworker instance

-  gets the set of trusted gpg pubkeys from puppet
-  imports them into ``~/.gnupg``
-  and signs them with their private gpg key, so we can validate the git commit signatures.
-  we update to the latest valid-signed tag, and regenerate the worker-implementation gpg homedirs if we're on a new git revision.

Then it builds a gpg homedir per worker implementation type (``generic-worker``, ``docker-worker``, ``taskcluster-worker``, ``scriptworker``).  Each has a corresponding directory in the git repo.

Each gpg homedir is separate from the others, so malicious or outdated keys can only affect the security of that single worker implementation.

The logic for gpg homedir creation is as follows:

``flat`` directories
^^^^^^^^^^^^^^^^^^^^

The Taskcluster-team-maintained worker implementations use the flat directory type, to reduce maintenance overhead.

For flat directories, scriptworker imports all pubkeys from the corresponding directory, and signs them to mark the pubkeys as valid.  This allows us to verify the signature on the signed chain of trust json artifacts.

``signed`` directories
^^^^^^^^^^^^^^^^^^^^^^

This is currently only for scriptworker.

- scriptworker imports all pubkeys in the ``trusted/`` subdirectory, signs them, and marks them as trusted.
- scriptworker imports all pubkeys in the ``valid/`` subdirectory.  They should already be signed by one of the keys in the ``trusted/`` subdirectory, so scriptworker doesn't otherwise sign or mark them as valid.

Building the chain
~~~~~~~~~~~~~~~~~~

First, scriptworker inspects the [signing/balrog/pushapk/beetmover] task that it claimed from the Taskcluster queue.  It adds itself and its :ref:`decision-task` to the chain.

Any task that generates artifacts for the scriptworker then needs to be inspected.  For scriptworker tasks, we have ``task.payload.upstreamArtifacts``, which looks like

.. code:: python

     [{
       "taskId": "upstream-task-id",
       "taskType": "build",  # for cot verification purposes
       "paths": ["path/to/artifact1", "path/to/artifact2"],
       "formats": ["gpg", "jar"]  # This is signing-specific for now; we could make formats optional, or use it for other task-specific info
     }, {
       ...
     }]

We add each upstream ``taskId`` to the chain, with corresponding ``taskType`` (we use this to know how to verify the task).

For each task added to the chain, we inspect the task definition, and add other upstream tasks:

- if the decision task doesn't match, add it to the chain
- docker-worker tasks have ``task.extra.chainOfTrust.inputs``, which is a dictionary like ``{"docker-image": "docker-image-taskid"}``.  Add the docker image ``taskId`` to the chain (this will likely have a different decision ``taskId``, so add that to the chain)

Verifying the chain
~~~~~~~~~~~~~~~~~~~

Scriptworker:

-  downloads the chain of trust artifacts for each upstream task in the chain, and verifies their signatures.  This requires detecting which worker implementation each task is run on, to know which gpg homedir to use.  At some point in the future, we may use ``workerType`` to worker implementation mappings.
-  downloads each of the ``upstreamArtifacts`` and verify their shas against the corresponding task's chain of trust's artifact shas.  the downloaded files live in ``cot/TASKID/PATH`` , so the script doesn't have to re-download and re-verify
-  downloads each decision task's ``task-graph.json``.  For every *other* task in the chain, we make sure that their task definition matches a task in their decision task's task graph.  There's some fuzzy matching going on here, to allow for datestring changes, as well as retriggering, which results in a new ``taskId``.
-  verifies each decision task command and ``workerType``, and makes sure its docker image sha is in the allowlist.
-  verifies each docker-image task command and docker image sha against the allowlist, until we resolve `bug 1328719 <https://bugzilla.mozilla.org/show_bug.cgi?id=1328719>`__.  Every other docker-worker task downloads its image from a previous docker-image task, so these two allowlists help us verify every docker image used by docker-worker.
-  verifies each docker-worker task's docker image sha
-  makes sure the ``interactive`` flag isn't on any docker-worker task.
-  determines which repo we're building off of
-  matches its task's scopes against the tree; restricted scopes require specific branches.

Once all verification passes, it launches the task script.  If chain of trust verification fails, it exits before launching the task script.

.. _gpg-key-management:

GPG Key management
------------------

GPG key management is a critical part of the chain of trust. There are
several types of gpg keys:

-  [taskcluster team] worker keys, which are unsigned pubkeys for
   docker- and generic- workers
-  [releng team] scriptworker keys, which are signed pubkeys for
   scriptworkers
-  [releng team] scriptworker trusted keys, which are the pubkeys of
   releng team members who are allowed to generate and sign scriptworker
   keys
-  [various] git commit signing keys. We keep the above pubkeys in a git
   repo, and we sign the commits. These are the pubkeys that are allowed
   to sign the git commits.

Adding new git commit signing gpg keys
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To update the other pubkeys, we need to be able to add them to the `git
repo <https://github.com/mozilla-releng/cot-gpg-keys>`__. We add the new
pubkeys in two places: `add the long keyid
in-repo <https://github.com/mozilla-releng/cot-gpg-keys/blob/master/check_commit_signatures.py#L13>`__,
and `add the pubkey itself in
puppet <http://hg.mozilla.org/build/puppet/file/tip/modules/scriptworker/files/git_pubkeys>`__

Adding new worker gpg keys
~~~~~~~~~~~~~~~~~~~~~~~~~~

New worker gpg keys should be committed to the
`repo <https://github.com/mozilla-releng/cot-gpg-keys>`__ with signed
commits. Only certain people can sign the commits, as per
`above <#adding-new-git-commit-signing-gpg-keys>`__.

new docker and generic worker gpg keys
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

When generating a new AMI or image, the docker and generic workers
generate a new gpg keypair. The Taskcluster team has the option of
recording the public key and adding it to the repo.

The pubkeys for build, decision, and docker-image workerTypes should be
added to the repo, with signed commits per the
`readme <https://github.com/mozilla-releng/cot-gpg-keys/blob/master/README.md>`__.

new scriptworker gpg keys
^^^^^^^^^^^^^^^^^^^^^^^^^

First, you will need access to a trusted key (The trusted keys are in
the `scriptworker/trusted
dir <https://github.com/mozilla-releng/cot-gpg-keys/tree/master/scriptworker/trusted>`__.
That may mean someone else needs to generate the keys, or you may
petition for access to create and sign these keys. (To do so, update the
trusted keys with a new pubkey, sign that commit with a trusted git
commit key, and merge. If you don't have a trusted git key, see `adding
new git commit signing gpg
keys <#adding-new-git-commit-signing-gpg-keys>`__.)

Once you have access to a trusted key, generate new gpg keypairs for
each host. The email address will be ``username``\ @\ ``fqdn``, e.g.
``cltsign@signing-linux-1.srv.releng.use1.mozilla.com``. You can use
`this
script <https://github.com/mozilla-releng/scriptworker/blob/master/helper_scripts/create_gpg_keys.py>`__,
like

.. code:: bash

    scriptworker/helper_scripts/create_gpg_keys.py -u cltsign -s host1.fqdn.com host2.fqdn.com
    # This will generate a gpg homedir in ./gpg
    # Keys will be written to ./host{1,2}.fqdn.com.{pub,sec}

Next, sign the newly created gpg keys with your trusted gpg key.

1. `import
   pubkey <https://access.redhat.com/documentation/en-US/Red_Hat_Enterprise_Linux/4/html/Step_by_Step_Guide/s1-gnupg-import.html>`__

.. code:: bash

       gpg --import HOSTNAME.pub

2. sign pubkey

.. code:: bash

    gpg --list-keys EMAIL
    gpg --sign-key EMAIL  # or fingerprint

3. `export signed
   pubkey <https://access.redhat.com/documentation/en-US/Red_Hat_Enterprise_Linux/4/html/Step_by_Step_Guide/s1-gnupg-export.html>`__

.. code:: bash

    gpg --armor --export EMAIL > USERNAME@HOSTNAME.pub  # or fingerprint

The signed pubkey + private key will need to go into hiera, as described
`here <new_instance.html#puppet>`__.

The signed pubkey will need to land in
`scriptworker/valid <https://github.com/mozilla-releng/cot-gpg-keys/tree/master/scriptworker/valid>`__
with a signed commit.

Testing / debugging
-------------------

The new ``verify_cot`` entry point allows you to test chain of trust
verification without running a scriptworker instance locally. (If `PR
#26 <https://github.com/mozilla-releng/scriptworker/pull/26>`__ hasn't
landed yet, the command is ``scriptworker/test/data/verify_cot.py``, but
it should work in the same way.)

Create the virtualenv
~~~~~~~~~~~~~~~~~~~~~

-  Install git, ``python>=3.5``, and python3 virtualenv

-  Clone scriptworker and create virtualenv:

.. code:: bash

        git clone https://github.com/mozilla-releng/scriptworker
        cd scriptworker
        virtualenv3 venv
        . venv/bin/activate
        python setup.py develop

-  Create a ~/.scriptworker or ./secrets.json with test client creds.

-  Create the client at `the client
   manager <https://tools.taskcluster.net/auth/clients/>`__. Mine has
   the ``assume:project:taskcluster:worker-test-scopes`` scope, but I
   don't think that's required.

-  The ~/.scriptworker or ./secrets.json file will look like this (fill
   in your clientId and accessToken):

.. code:: python

        {
          "credentials": {
            "clientId": "mozilla-ldap/asasaki@mozilla.com/signing-test",
            "accessToken": "********"
          }
        }

-  Find a scriptworker task on
   `treeherder <https://treeherder.mozilla.org>`__ to test.

-  Click it, click 'inspect task' in the lower left corner

-  The taskId will be in a field near the top of the page. E.g., for
   `this
   task <https://tools.taskcluster.net/task-inspector/#cbYd3U6dRRCKPUbKsEj1Iw/0>`__,
   the task id is ``cbYd3U6dRRCKPUbKsEj1Iw``

-  Now you should be able to test chain of trust verification! If `PR
   #26 <https://github.com/mozilla-releng/scriptworker/pull/26>`__ has
   landed, then

.. code:: bash

        verify_cot TASKID  # e.g., verify_cot cbYd3U6dRRCKPUbKsEj1Iw

Otherwise,

.. code:: bash

        scriptworker/test/data/verify_cot.py TASKID  # e.g., scriptworker/test/data/verify_cot.py cbYd3U6dRRCKPUbKsEj1Iw
