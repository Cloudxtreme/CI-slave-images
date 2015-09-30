contains fabric code to build the CI slave images.

usage:

clone the following repos:


```
     git clone git@github.com:ClusterHQ/CI-slave-images
     cd CI-slave-images
     git clone git@github.com:ClusterHQ/segredos.git segredos
```

export the following environment variables:


For EC2:


    * AWS_KEY_PAIR (the KEY_PAIR to use)

    * AWS_KEY_FILENAME (the full path to your .pem file)

    * AWS_SECRET_ACCESS_KEY

    * AWS_ACCESS_KEY_ID


For Rackspace:


    * RACKSPACE_KEY_PAIR (the KEY_PAIR to use)

    * RACKSPACE_KEY_FILENAME (the full path to your .pem file)

    * OS_USERNAME

    * OS_TENANT_NAME

    * OS_PASSWORD

    * OS_AUTH_URL

    * OS_AUTH_SYSTEM

    * OS_REGION_NAME

    * OS_NO_CACHE


create your virtualenv:

```
    virtualenv2 venv
    . venv/bin/activate
    pip2 install -r requirements.txt --upgrade

```

then execute as:

```
    fab it:cloud=ec2,distribution=centos7
    fab destroy
    fab it:cloud=rackspace,distribution=ubuntu14.04

    fab help

    Available commands:

        bootstrap     bootstraps an existing running instance
        create_image  create ami/image for either AWS or Rackspace
        destroy       destroy an existing instance
        down          halt an existing instance
        help          help
        it            runs the full stack
        ssh           opens an ssh connection to the instance
        status        returns current status of the instance
        tests         run tests against an existing instance
        up            boots a new instance on amazon or rackspace

```

The fab code should bootstrap an AWS/Rackspace instance,
provision it and bake an image before deleting the original instance.

NOTE: if you get an:
```
    image = conn.get_all_images(ami)[0]
    IndexError: list index out of range
```
while bootstrapping an ubuntu instance, it is likely the base AMI is no longer
available.
Find out the new one from:
http://cloud-images.ubuntu.com/locator/ec2/
[us-west-2][trusty][14.04 LTS][amd64][ebs][Any][Any][hvm]

and update the fabfile.py with the new AMI id, commit, push, etc.
