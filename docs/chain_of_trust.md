# Chain of Trust

## Overview
Taskcluster is versatile and self-serve, which is awesome for developers to be able to make their own automation changes without being blocked on other teams.  However, this freedom presents security concerns around release tasks.

We have scopes as our auth model.  These are not leak-proof, and to be able to trigger a graph with a release task in it, you need to already have the release scopes required... which means you also have the ability to trigger an arbitrary release task with the same scopes.

The chain of trust is a second factor that isn't automatically compromised if scopes are compromised.  This chain allows us to trace a task's request back to the tree.

## Chain of Trust Generation
- Embedded GPG keys

  - These are the second factor.
  - docker-worker has these embedded in the AMI, inaccessible to tasks run inside the docker container.  These are unique per AMI, which we can rotate every N days (monthly?)
  - generic-worker has the ability to embed these into the AMI for ec2 instances
  - taskcluster-worker will need the ability to embed these
  - scriptworker has these on the host

- Chain of Trust artifacts

  - After the task finishes, the worker creates a chain of trust json blob, gpg signs it, then uploads it as public/chainOfTrust.json.asc .  It looks like

```python
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
```

  - [v1 schema](https://github.com/mozilla-releng/scriptworker/blob/master/scriptworker/data/cot_v1_schema.json)
  - [example artifact](https://queue.taskcluster.net/v1/task/YF5KkwPdRk610ervsXPbgA/runs/0/artifacts/public/chainOfTrust.json.asc)

## Chain of Trust Verification

- GPG homedir management
  - The chain of trust artifacts are signed, but without somehow having access to the public key and marking it as valid, we don't know if it's been signed by a real worker key or just some rando gpg key
  - We have a [github repo of pubkeys](https://github.com/mozilla-releng/cot-gpg-keys)
    - scriptworker instances have the pubkeys (from puppet) that are allowed to sign those git commits.  ~/.gnupg imports and signs those pubkeys, so we can validate the git commit signatures
    - docker-worker and generic-worker just have pubkeys in their respective directories.  Scriptworker instances create separate gpg homedirs with those pubkeys, and sign each key so we can verify the signatures of the chain of trust artifacts from those workers
    - scriptworker has `scriptworker/trusted/` and `scriptworker/valid`.  `trusted/` are the pubkeys allowed to sign scriptworker keys.  `valid/` are the worker keys.  The scriptworker gpg homedir imports, signs, and trusts the trusted/ pubkeys, and then imports the valid keys without signing or trusting.
- Follow the chain to the tree
  - For upstream tasks, we have `task.extra.chainOfTrust.inputs`, which is a dictionary like `{"docker-image": "docker-image-taskid"}`
  - We also have the decision task id, which is the `taskGroupId`.
  - For scriptworker tasks, we have `task.payload.upstreamArtifacts`, which looks like
```python
      [{
        "taskId": "upstream-task-id",
        "taskType": "build",  # for cot verification purposes
        "paths": ["path/to/artifact1", "path/to/artifact2"],
        "formats": ["gpg", "jar"]  # This is signing-specific for now; we could make formats optional, or use it for other task-specific info
      }, {
        ...
      }]
```
  We can add upstream task ids to the list of chain links to follow
- Download the chain of trust artifacts and verify their signatures
  - Using the above gpg homedirs
- Download upstreamArtifacts and verify their shas against the chain of trust artifact shas
  - These live in `$work_dir/cot/$upstream-task-id/$path` , so the script doesn't have to re-download and re-verify
- Verify the chain of trust
  - verify each task type:
    - [decision](https://github.com/mozilla-releng/scriptworker/blob/910c2056bf31c190a2c95c8f6435386dceb66083/scriptworker/cot/verify.py#L759)
      - [verifying the decision command](https://github.com/mozilla-releng/scriptworker/blob/910c2056bf31c190a2c95c8f6435386dceb66083/scriptworker/cot/verify.py#L685) is a little hairy atm, but needed.
      - download the full-task.json and [make sure all tasks that specify this as the decision task are in that graph](https://github.com/mozilla-releng/scriptworker/blob/910c2056bf31c190a2c95c8f6435386dceb66083/scriptworker/cot/verify.py#L643)
        - [PR #26](https://github.com/mozilla-releng/scriptworker/pull/26) will allow for retriggers
    - [build/l10n](https://github.com/mozilla-releng/scriptworker/blob/910c2056bf31c190a2c95c8f6435386dceb66083/scriptworker/cot/verify.py#L793)
    - [docker-image](https://github.com/mozilla-releng/scriptworker/blob/910c2056bf31c190a2c95c8f6435386dceb66083/scriptworker/cot/verify.py#L826)
    - [signing](https://github.com/mozilla-releng/scriptworker/blob/910c2056bf31c190a2c95c8f6435386dceb66083/scriptworker/cot/verify.py#L849)
  - [Between 1 and 2 decision tasks](https://github.com/mozilla-releng/scriptworker/blob/910c2056bf31c190a2c95c8f6435386dceb66083/scriptworker/cot/verify.py#L864)
  - [docker-worker check](https://github.com/mozilla-releng/scriptworker/blob/910c2056bf31c190a2c95c8f6435386dceb66083/scriptworker/cot/verify.py#L917)
    - non-interactive; verify the docker image sha against the expected
  - [trace back to the tree](https://github.com/mozilla-releng/scriptworker/blob/910c2056bf31c190a2c95c8f6435386dceb66083/scriptworker/cot/verify.py#L992)
    - match scopes against tree; [restricted scopes require specific branches](https://github.com/mozilla-releng/scriptworker/blob/910c2056bf31c190a2c95c8f6435386dceb66083/scriptworker/constants.py#L213-L245)
    - if [`is_try`](https://github.com/mozilla-releng/scriptworker/blob/910c2056bf31c190a2c95c8f6435386dceb66083/scriptworker/cot/verify.py#L293), also fail out on restricted scopes
- then launch the task script after chain of trust verification passes.  If it fails, don't launch the task script.

## GPG Key management

GPG key management is a critical part of the chain of trust.  There are several types of gpg keys:

- [taskcluster team] worker keys, which are unsigned pubkeys for docker- and generic- workers
- [releng team] scriptworker keys, which are signed pubkeys for scriptworkers
  - [releng team] scriptworker trusted keys, which are the pubkeys of releng team members who are allowed to generate and sign scriptworker keys
- [various] git commit signing keys.  We keep the above pubkeys in a git repo, and we sign the commits.  These are the pubkeys that are allowed to sign the git commits.

### Adding new git commit signing gpg keys

To update the other pubkeys, we need to be able to add them to the [git repo](https://github.com/mozilla-releng/cot-gpg-keys).  We add the new pubkeys in two places: [add the long keyid in-repo](https://github.com/mozilla-releng/cot-gpg-keys/blob/master/check_commit_signatures.py#L13), and [add the pubkey itself in puppet](http://hg.mozilla.org/build/puppet/file/tip/modules/scriptworker/files/git_pubkeys)

### Adding new worker gpg keys

New worker gpg keys should be committed to the [repo](https://github.com/mozilla-releng/cot-gpg-keys) with signed commits.  Only certain people can sign the commits, as per [above](#adding-new-git-commit-signing-gpg-keys).

#### new docker and generic worker gpg keys

When generating a new AMI or image, the docker and generic workers generate a new gpg keypair.  The Taskcluster team has the option of recording the public key and adding it to the repo.

The pubkeys for build, decision, and docker-image workerTypes should be added to the repo, with signed commits per the [readme](https://github.com/mozilla-releng/cot-gpg-keys/blob/master/README.md).

#### new scriptworker gpg keys

First, you will need access to a trusted key (The trusted keys are in the [scriptworker/trusted dir](https://github.com/mozilla-releng/cot-gpg-keys/tree/master/scriptworker/trusted).  That may mean someone else needs to generate the keys, or you may petition for access to create and sign these keys.  (To do so, update the trusted keys with a new pubkey, sign that commit with a trusted git commit key, and merge.  If you don't have a trusted git key, see [adding new git commit signing gpg keys](#adding-new-git-commit-signing-gpg-keys).)

Once you have access to a trusted key, generate new gpg keypairs for each host.  The email address will be `username`@`fqdn`, e.g. `cltsign@signing-linux-1.srv.releng.use1.mozilla.com`.  You can use [this script](https://github.com/mozilla-releng/scriptworker/blob/master/helper_scripts/create_gpg_keys.py), like

```bash
scriptworker/helper_scripts/create_gpg_keys.py -u cltsign -s host1.fqdn.com host2.fqdn.com
# This will generate a gpg homedir in ./gpg
# Keys will be written to ./host{1,2}.fqdn.com.{pub,sec}
```

Next, sign the newly created gpg keys with your trusted gpg key.

1. [import pubkey](https://access.redhat.com/documentation/en-US/Red_Hat_Enterprise_Linux/4/html/Step_by_Step_Guide/s1-gnupg-import.html)

```bash
   gpg --import HOSTNAME.pub
```

2. sign pubkey

```bash
gpg --list-keys EMAIL
gpg --sign-key EMAIL  # or fingerprint
```
3. [export signed pubkey](https://access.redhat.com/documentation/en-US/Red_Hat_Enterprise_Linux/4/html/Step_by_Step_Guide/s1-gnupg-export.html)

```bash
gpg --armor --export EMAIL > USERNAME@HOSTNAME.pub  # or fingerprint
```

The signed pubkey + private key will need to go into hiera, as described [here](new_instance.html#puppet).

The signed pubkey will need to land in [scriptworker/valid](https://github.com/mozilla-releng/cot-gpg-keys/tree/master/scriptworker/valid) with a signed commit.

## Testing / debugging
The new `verify_cot` entry point allows you to test chain of trust verification without running a scriptworker instance locally.  (If [PR #26](https://github.com/mozilla-releng/scriptworker/pull/26) hasn't landed yet, the command is `scriptworker/test/data/verify_cot.py`, but it should work in the same way.)

### Create the virtualenv
- Install git, `python>=3.5`, and python3 virtualenv

- Clone scriptworker and create virtualenv:

```bash
    git clone https://github.com/mozilla-releng/scriptworker
    cd scriptworker
    virtualenv3 venv
    . venv/bin/activate
    python setup.py develop
```

- Create a ~/.scriptworker or ./secrets.json with test client creds.

  - Create the client at [the client manager](https://tools.taskcluster.net/auth/clients/).  Mine has the `assume:project:taskcluster:worker-test-scopes` scope, but I don't think that's required.

  - The ~/.scriptworker or ./secrets.json file will look like this (fill in your clientId and accessToken):

```python
    {
      "credentials": {
        "clientId": "mozilla-ldap/asasaki@mozilla.com/signing-test",
        "accessToken": "********"
      }
    }
```

- Find a scriptworker task on [treeherder](https://treeherder.mozilla.org) to test.

  - Click it, click 'inspect task' in the lower left corner

  - The taskId will be in a field near the top of the page.  E.g., for [this task](https://tools.taskcluster.net/task-inspector/#cbYd3U6dRRCKPUbKsEj1Iw/0), the task id is `cbYd3U6dRRCKPUbKsEj1Iw`

- Now you should be able to test chain of trust verification!  If [PR #26](https://github.com/mozilla-releng/scriptworker/pull/26) has landed, then

```bash
    verify_cot TASKID  # e.g., verify_cot cbYd3U6dRRCKPUbKsEj1Iw
```

  Otherwise,

```bash
    scriptworker/test/data/verify_cot.py TASKID  # e.g., scriptworker/test/data/verify_cot.py cbYd3U6dRRCKPUbKsEj1Iw
```
