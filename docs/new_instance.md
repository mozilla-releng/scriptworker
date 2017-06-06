# Adding new scriptworker instances of an existing type

We don't yet have a scriptworker provisioner, so spinning up new instances of a specific type is still a manual process that can definitely use improvement.  Here are docs on how to spin a new instance up.

## signing scriptworker
### gpg keypair
If this is a chain of trust enabled scriptworker, you'll need to generate a gpg keypair.  Otherwise (dev or dep scriptworker), skip to the next step.

Generate and sign a gpg keypair for cltsign@**fqdn**, per [these docs](chain_of_trust.html#adding-new-worker-gpg-keys).

The pubkey will need to land in the [cot-gpg-keys repo](https://github.com/mozilla-releng/cot-gpg-keys), in the `scriptworker/valid` directory.  The keypair will need to go into puppet hiera, as specified below.

### aws

For a signing scriptworker instance, find a valid signing-range IP and add to dns, like [the slave loan](https://wiki.mozilla.org/ReleaseEngineering/How_To/Loan_a_Slave#Build_machines).  These will be in similar subnets to the existing instances:

```
    10.134.30.12 signing-linux-1.srv.releng.use1.mozilla.com
    10.132.30.46 signing-linux-2.srv.releng.usw2.mozilla.com
    10.134.30.125 signing-linux-3.srv.releng.use1.mozilla.com
    10.132.30.82 signing-linux-4.srv.releng.usw2.mozilla.com
```

Go to the EC2 console, go to the appropriate region (usw2, use1).

- Instances -> Launch Instance -> My AMIs -> `centos-65-x86_64-hvm-base-2015-08-28-15-51` -> Select
- t2-micro -> configure instance details
- change the subnet to the `signing` subnet; add a public IP; specify the DNS IP at the bottom -> Add storage
- General purpose SSD -> Tag Instance
- Tag with its name, e.g. signing-linux-5 -> Configure security group
- Select an existing group; choose the `signing-worker` group; review and launch
- make sure to choose a keypair you have access to, e.g. aws-releng or generate your own keypair.  Puppet will overwrite this.

### puppet

If this is a chain of trust enabled scriptworker, add the gpg keypair into [hiera](https://wiki.mozilla.org/ReleaseEngineering/PuppetAgain/Secrets).  This will be the `scriptworker_gpg_private_keys` and `scriptworker_gpg_public_keys` dictionaries.  The dictionary key is the instance fqdn; the value is the [encrypted file](https://wiki.mozilla.org/ReleaseEngineering/PuppetAgain/Secrets#Encrypt_files_.28e.g._private_keys.29).

ssh into the instance as root, using the ssh keypair you specified above.

Install puppet:

```bash
    yum -c /etc/yum-local.cfg install puppet
```

Then puppetize (you need the deploy pass for this):

```bash
    # change the hostname so the cert matches
    hostname FQDN
    # grab puppetize.sh and run it
    wget https://hg.mozilla.org/build/puppet/raw-file/tip/modules/puppet/files/puppetize.sh
    sh puppetize.sh
```

It is probably best to reboot after puppetizing.  After this point, it should Just Work.
