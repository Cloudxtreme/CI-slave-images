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

    * Either
 
      * Run `gcloud auth login`

      * Set GOOGLE_APPLICATION_CREDENTIALS to a json key file downloaded from
        the GCE console to authenticate as a service account.

    * GCE_PUBLIC_KEY (Absolute file path to a public ssh key to use)

    * GCE_PRIVATE_KEY (Absolute file path to a private ssh key to use)

    * GCE_PROJECT (The GCE project to create the image in)

    * GCE_ZONE (The GCE zone to use to make the image)

    * GCE_MACHINE_TYPE (The machine type to use to make the image, defaults to
                        n1-standard-2)




create your virtualenv:

```
    virtualenv2 venv
    . venv/bin/activate
    pip2 install -r requirements.txt --upgrade

```

then execute as:

```


  usage: fab <action>[:arguments] <action>[:arguments]

    # shows this page
    $ fab help

    # boots an existing instance
    $ fab up

    # creates a new instance
    $ fab cloud:ec2|rackspace|gce region:us-west-2 distribution:centos7 up

    # installs packages on an existing instance
    $ fab bootstrap

    # creates a new ami
    $ fab create_image

    # destroy the box
    $ fab destroy

    # power down the box
    $ fab down

    # ssh to the instance
    $ fab ssh

    # execute a command on the instance
    $ fab ssh:'ls -l'

    # run acceptance tests against new instance
    $ fab tests

    Metadata state is stored locally in .state.json.

    config.yaml contains a list of default configuration parameters.
```

The fab code should bootstrap an AWS/Rackspace instance,
provision it and bake an image before deleting the original instance.

On GCE it also bootstraps a GCE instance, but destroys the instance prior to
constructing the image from the disk, as required by the GCE API.

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

    fab cloud:ec2 region:us-west-2 distribution:centos7 up
    fab bootstrap
    fab tests
    fab create_image 2>&1 >> fabbing.it.log
    fab destroy

2. Gather the IDs for the different images:

   grep the AWS AMIs from the log:

    grep Image: fabbing.it.log
    created server image: ami-nnnnnnnn

   And The Rackspace AMIs:

    grep "created server image" fabbing.it.log
    created server image: nnnnnnnn-nnnn-nnnn-nnnn-nnnnnnnnnnnn


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
