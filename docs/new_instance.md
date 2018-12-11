# Adding new scriptworker instances of an existing type

We don't yet have a scriptworker provisioner, so spinning up new instances of a specific type is still a manual process that can definitely use improvement.  Here are docs on how to spin a new instance up. These instructions apply to any type of scriptworker that
already has an instance running, hence configurations already exists.

## 1. initial setup

To begin with, you need to figure out the network basics, IP and DNS entries. With these at hand, you'll be ready to spin out a new instance. To ease some of these operations, you need to use the `build-cloud-tools` repository.

Firstly, you need to clone it and have a python environment read, to run some of its scripts:

```
$ git clone git@github.com:mozilla-releng/build-cloud-tools.git
$ cd build-cloud-tools
$ mkvirtualenv cloudtools
$ python setup.py develop
```

The scripts that you're about to run are using `boto` library under the hood, for which you need to define the credentials to access the AWS console. These can be set in different ways, from environment variables to configurations files. More on this [here](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/configuration.html#configuring-credentials).
It's indicated that you create a dedicated set of AWS credentials in your AWS RelEng console, under your IAM user. For example, if you were to choose config files, you should have something like this:

```
$ cat ~/.aws/credentials
[default]
aws_access_key_id= ...
aws_secret_access_key= ...
```

Next, make sure you're connected to the **VPN**.

You can now run your script to find out available IPs. For example, if one wanted to ramp-up another `beetmoverworker` instance within the `us-west-2` AWS region, the script to run would be:

```
(cloudtools) $ python cloudtools/scripts/free_ips.py -c configs/beetmoverworker -r us-west-2 -n1
```

With the IP returned above, [file a bug](https://bugzilla.mozilla.org/enter_bug.cgi?product=Infrastructure%20%26%20Operations&component=DNS%20and%20Domain%20Registration)
like [bug 1503550](https://bugzilla.mozilla.org/show_bug.cgi?id=1503550) to ask for DNS records to be assigned for your IP.

Once the bug is fixed, you should be able to see the DNS entries correspond to your IP address by using the following:

```
dig -x <ip_address>
```

## 2. creating an AWS instance

Furthermore, you need to spin up an AWS instance and for that there are *two* options.

## 2a - using automation script

In order to use the `build-cloud-tools` scripts, you'll first need access to some of the secrets.
Grab the `deploypass` from private repo and dump it in a JSON file.
```
$ cat secrets.json
{
    "deploy_password": "..."
}
```
Grab the `aws-releng` SSH key from private repo.

Make sure to split the DNS as anything `mozilla.(com|net|org)` should be forwarding over the VPN. In order to do so, you should have something like this in Viscosity's connection details:

![DNS split in VPN](_static/dns.png?raw=true)

This change is needed because your local machine is likely using other DNS servers by default, hence the sanity checks that automation does will bail for `PTR` records not found. By splitting the DNS trafic via VPN, you ensure that
both `A` and `PTR` records can be found for your IP/hostname touple so that sanity check passes successfully.

Now it's time to spin a new instance in AWS. For example, continuing the aforemnetioned example, if one wanted to ramp-up a `beetmoverworker` instance within the `us-west-2` AWS region, the script to run would be:
```
$ host=<your hostname>
$ python cloudtools/scripts/aws_create_instance.py -c configs/beetmoverworker -r us-west-2 -s aws-releng -k secrets.json --ssh-key aws-releng -i instance_data/us-west-2.instance_data_prod.json $host
```

This spins a new AWS instance, but puppetization may fail, hence you'll have to run in manually. See instructions [below](#puppet).

## 2b - using AWS console

Go to the EC2 console, go to the appropriate region (usw2, use1).

- Instances -> Launch Instance -> My AMIs -> `centos-65-x86_64-hvm-base-2015-08-28-15-51` -> Select
- t2-micro -> configure instance details
- change the subnet to the type of scriptworker's configs from `build-cloud-tools`; add the public IP; specify the DNS IP at the bottom -> Add storage
- General purpose SSD -> Tag Instance
- Tag with its name, e.g. `beetmoverworker` -> Configure security group
- Select an existing group; e.g. choose the `beetmover-worker` group; review and launch
- make sure to choose a keypair you have access to, e.g. aws-releng or generate your own keypair.  Puppet will overwrite this.

Alternatively, you can create a template based on an existing instance and then launch another instance based on that template, after you amend the `ami-id`, `subnet`, `security-groups` and IP/DNS entries.


## 3. Puppetize the instance

Once the machine is up and running (can check its state in the AWS console), ssh into the instance as root, using the ssh keypair you specified above.
```
$ ssh -i aws-releng root@<fqdn>
```

To begin with, Install puppet:

```bash
    sed -i -e 's/puppetagain.*\/data/releng-puppet2.srv.releng.mdc1.mozilla.com/g' /etc/yum-local.cfg
    yum -c /etc/yum-local.cfg install puppet
```

Then puppetize (you need the deploy pass for this):

```bash
    # change the hostname so the cert matches
    hostname FQDN
    # grab puppetize.sh and run it
    wget https://hg.mozilla.org/build/puppet/raw-file/tip/modules/puppet/files/puppetize.sh
    # if we're doing a standard puppetize
    PUPPET_SERVER=releng-puppet2.srv.releng.mdc1.mozilla.com sh puppetize.sh
    # else if we want to puppetize against an environment
    PUPPET_SERVER=releng-puppet2.srv.releng.mdc1.mozilla.com PUPPET_EXTRA_OPTIONS="--environment=USER" sh puppetize.sh
    # run puppet
    puppet agent --test # first round takes > 6000 seconds
    puppet agent --test # second run is faster, applies kernel update, requires reboot afterwards
    reboot
```
The instance should be now accessible via LDAP login via ssh keys.

Wipe of the secrets from your local machine
```
rm secrets.json
rm aws-releng
```

## monitoring

The new instance(s) should be added to the nagios configuration in IT's puppet repo so that we're
notified of any problems. There's more information about what is monitored in the [new instance
doc](new_instance.html#monitoring).

With the VPN running, clone the puppet repo
([see point 10 for the location](https://mana.mozilla.org/wiki/display/MOC/NEW+New+Hire+Onboarding)).
Then modify `modules/nagios4/manifests/prod/releng/mdc1.pp` by copying over the config of one of
the existing instances and updating the hostname. For example a new balrogworker would look like:
```
    'balrogworker-42.srv.releng.use1.mozilla.com' => {
        contact_groups => 'build',
        hostgroups => [
            'balrog-scriptworkers'
        ]
    },
```
The checks are added by membership to that hostgroup.

Create a patch, attach it to Bugzilla, and ask someone from RelOps for review, before
landing. After a 15-30 minute delay the checks should be live and you can look for them on the
[mdc1 nagios server](https://nagios1.private.releng.mdc1.mozilla.com/releng-mdc1/).
