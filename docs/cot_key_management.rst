.. _cot-key-management:

Chain of Trust Key Management
-----------------------------

Ed25519 key management is a critical part of the chain of trust. There are
valid ed25519 keys per worker implementation (docker-worker, generic-worker,
and scriptworker).

Base64-encoded seeds that can be converted to valid level 3 ed25519 pubkeys are
recorded in ``scriptworker.constants``, in
``DEFAULT_CONFIG['ed25519_public_keys']``. These are tuples to allow for key
rotation.

At some point we may add per-cot-project sets of pubkeys. We may also move
the source of truth of these pubkeys to a separate location, to enable
cot signature verification elsewhere, outside of scriptworker.

verifying new ed25519 keys
~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``verify_cot`` commandline tool supports a ``--verify-sigs`` option. This
will turn on signature verification, and will break if the cot artifacts are
not signed by valid level 3 ed25519 keys.

There is also a ``verify_ed25519_signature`` commandline tool. This takes
a file path and a signature path, and verifies if the file was validly signed
by a known valid level 3 key. It also takes an optional ``--pubkey PUBKEY``
argument, which allows you to verify if the file was signed by that pubkey.

Rotating the FirefoxCI CoT keys
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

See `this mana page <https://mana.mozilla.org/wiki/pages/viewpage.action?spaceKey=RelEng&title=Chain+of+Trust+key+rotation>`__.
