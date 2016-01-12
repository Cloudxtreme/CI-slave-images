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


For Google Compute Engine:

    * GCE_PUBLIC_KEY_FILENAME

    * GCE_PRIVATE_KEY_FILENAME

    * OS_USERNAME


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


Updating Jenkins to use the new images:
=======================================


1. Generate the new Cloud server images used by Jenkins:

    fab it:cloud=ec2,distribution=centos7 \
        it:cloud=ec2,distribution=ubuntu14.04 \
        it:cloud=rackspace,distribution=centos7 \
        it:cloud=rackspace,distribution=ubuntu14.04 | tee /tmp/fabbing.it.log


2. Gather the IDs for the different images:

   grep the AWS AMIs from the log:

    grep Image: fabbing.it.log
    ami ami-nnnnnnnn Image:ami-nnnnnnnn
    ami ami-nnnnnnnn Image:ami-nnnnnnnn


   And The Rackspace AMIs:

    grep "finished image" fabbing.it.log
    finished image: nnnnnnnn-nnnn-nnnn-nnnn-nnnnnnnnnnnn
    finished image: nnnnnnnn-nnnn-nnnn-nnnn-nnnnnnnnnnnn


3. Clone the ci-platform and segredos git repositories:

   https://github.com/ClusterHQ/ci-platform
   https://github.com/ClusterHQ/segredos


3. Update the segredos/ci-plaform/yaml dictionary with the new AMIs

   Look under:

   jenkins:
    clouds:
        images:
            aws:
                <my-region>:
            rackspace:
                <my-region>:


3. Copy the new images across all the regions:

* For AWS:

on the AWS Console, find the new AMIs and click copy selecting the destination.
Take note on the new AMI id and the destination.
Then update the cloud/images/aws/<region>/ with the new AMIs

* For RACKSPACE

It is easier to simply create a new image by defining a different region.
```
OS_REGION_NAME=IAD
```
and repeat the steps to generate the new image.


4. Generate a new Jenkins personal test server

Follow the steps in the https://github.com/ClusterHQ/ci-platform
Make sure you link group_vars to your local segredos repository copy.

Then:

    rake default aws


5. Test a master build using your new personal test jenkins instance.

Run the setupClusterHQFlocker job to generate the jenkins jobs for the
*master* branch.


6. Open a Pull Request:

    git checkout -b my_new_branch
    git add your changes to the segredos/ci-platform/yaml
    git commit
    git push your new branch
    open a PR in GitHub


7. Update JIRA Ticket

Make sure there is a JIRA ticket/subtask mentioning that Jenkins master
needs to be re-provisioned after your PR is accepted.
(yes, there is another stage after 'ADDRESS_AND_MERGE', let's just call it DEPLOYMENT)


8. Wait for JIRA to move to ACCEPTED


8. Deploy the changes to the Jenkins Master

   Until https://clusterhq.atlassian.net/browse/FLOC-2703 is complete, follow
   these steps:

   - update /etc/hosts on your laptop so that 'jenkins' points to the ci-live.clusterhq.com
   - git checkout the master branch on for *ci-platform* and *segredos*
   - run a vagrant provision to update the Jenkins Master


9. Close the JIRA and its subtasks
