# vim: ai ts=4 sts=4 et sw=4 ft=python fdm=indent et

# fabric task file for building new CI slave images
#
# usage:
#       fab help
#


import os
from datetime import datetime
import uuid
from fabric.api import task, env
from pprint import PrettyPrinter

from bookshelf.api_v1 import (up as f_up,
                              down as f_down,
                              destroy as f_destroy,
                              startup_gce_instance as f_startup_gce_instance)


from bookshelf.api_v2.ec2 import (
    up_ec2,
    down_ec2,
    destroy_ec2,
    create_ami
)

from bookshelf.api_v2.rackspace import (
    create_rackspace_image,
    destroy_rackspace
)

from bookshelf.api_v2.logging_helpers import log_green, log_red

from bookshelf.api_v1 import (ssh_session, create_gce_image)

from lib.mycookbooks import (ec2,
                             rackspace,
                             gce,
                             get_cloud_environment,
                             segredos,
                             load_config,
                             cloud_region_distro_config,
                             connect_to_cloud_provider,
                             create_new_vm)


from lib.bootstrap import (bootstrap_jenkins_slave_centos7,
                           bootstrap_jenkins_slave_ubuntu14)

from tests.acceptance import acceptance_tests


@task(default=True)
def help():
    """ help """
    print("""
          usage: fab <action>[:arguments] <action>[:arguments]

            # shows this page
            $ fab help

            # boots an existing instance
            $ fab up

            # creates a new instance
            $ fab cloud:ec2|rackspace|gce region:us-west-2 distribution:centos7

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

            The following environment variables must be set:

            For AWS:
            http://docs.aws.amazon.com/cli/latest/userguide/cli-chap-getting-started.html#cli-environment

            # AWS_ACCESS_KEY_ID
            # AWS_KEY_FILENAME (the full path to your private key file)
            # AWS_KEY_PAIR (the KEY_PAIR to use)
            # AWS_SECRET_ACCESS_KEY
            # AWS_ACCESS_REGION (optional)
            # AWS_AMI (optional)
            # AWS_INSTANCE_TYPE (optional)

            For Rackspace:
            http://docs.rackspace.com/servers/api/v2/cs-gettingstarted/content/gs_env_vars_summary.html

            # OS_USERNAME
            # OS_TENANT_NAME
            # OS_PASSWORD
            # OS_NO_CACHE
            # RACKSPACE_KEY_PAIR (the KEY_PAIR to use)
            # RACKSPACE_KEY_FILENAME (the full path to your private key file)
            # OS_AUTH_SYSTEM (optional)
            # OS_AUTH_URL (optional)
            # OS_REGION_NAME (optional)

            For Google Compute Engine (GCE):
            # GCE_PUBLIC_KEY (Absolute file path to a public ssh key to use)
            # GCE_PRIVATE_KEY (Absolute file path to a private ssh key to use)
            # GCE_PROJECT (The GCE project to create the image in)
            # GCE_ZONE (The GCE zone to use to make the image)
            # GCE_MACHINE_TYPE (The machine type to use to make the image,
              defaults to n1-standard-2)

            Metadata state is stored locally in .state.json.

            config.yaml contains a list of default configuration parameters.
          """)


@task
def create_image():
    """ create ami/image for either AWS, Rackspace or GCE """
    (year, month, day, hour, mins,
     sec, wday, yday, isdst) = datetime.utcnow().timetuple()
    date = "%s%s%s%s%s" % (year, month, day, hour, mins)

    cloud, region, distro, k = cloud_region_distro_config()
    connect_to_cloud_provider()

    if cloud == 'ec2':
        image_id = create_ami(connection=env.connection,
                              region=region,
                              instance_id=env.config['instance_id'],
                              name=k['instance_name'] + date,
                              description=k['description'])

    if cloud == 'rackspace':
        image_id = create_rackspace_image(connection=env.connection,
                                          server_id=env.config['instance_id'],
                                          name=k['instance_name'] + date,
                                          description=k['description'])

    if cloud == 'gce':
        create_gce_image(description=k['description'],
                         project=k['project'],
                         instance_name=k['instance_name'] + date,
                         name=k['description'])

    log_green('created server image: %s' % image_id)


@task
def destroy():
    """ destroy an existing instance """
    cloud, region, distro, k = cloud_region_distro_config()
    connect_to_cloud_provider()

    if cloud == 'ec2':
        destroy_ec2(connection=env.connection,
                    region=region,
                    instance_id=env.config['instance_id'])
        os.unlink('.state.json')

    if cloud == 'rackspace':
        destroy_rackspace(connection=env.connection,
                          region=region,
                          instance_id=env.config['instance_id'])
        os.unlink('.state.json')

    if cloud == 'gce':
        f_destroy(cloud='gce',
                  zone=k['region'],
                  project=k['project'],
                  disk_name=env.config['instance_name'])
        os.unlink('.state.json')


@task
def down():
    """ halt an existing instance """
    cloud, region, distro, k = cloud_region_distro_config()
    connect_to_cloud_provider()

    if cloud == 'ec2':
        down_ec2(connection=env.connection,
                 instance_id=env.config['instance_id'],
                 region=region)

    if cloud == 'rackspace':
        destroy()

    if cloud == 'gce':
        f_down(cloud=cloud,
               zone=k['region'],
               project=k['project'],
               instance_name=env.config['instance_name'])


@task
def bootstrap():
    """ bootstraps an existing running instance

    :param string distribution: which OS to use 'centos7', 'ubuntu1404'
    """

    cloud, region, distro, k = cloud_region_distro_config()
    env.user = k['username']

    if 'centos7' in distro:
        bootstrap_jenkins_slave_centos7()

    if 'ubuntu14' in distro:
        bootstrap_jenkins_slave_ubuntu14()


@task
def status():
    """ returns current status of the instance """

    cloud, region, distro, k = cloud_region_distro_config()

    data = env.config
    data['username'] = k['username']
    pp = PrettyPrinter(indent=4)
    pp.pprint(data)


@task
def ssh(*cli):
    """ opens an ssh connection to the instance

    :param string cli: the commands to run on the host
    """
    cloud, region, distro, k = cloud_region_distro_config()

    state = env.config

    ssh_session(key_filename=k['key_filename'],
                username=state['username'],
                ip_address=state['public_dns_name'],
                *cli)


@task
def tests():
    """ run tests against an existing instance """

    cloud, region, distro, k = cloud_region_distro_config()

    acceptance_tests(distribution=distro)


@task
def up():
    """ boots a new instance on amazon or rackspace
    """
    cloud = env.config['cloud']
    region = env.config['region']
    distro = env.config['distribution']
    k = env.global_config[cloud]['regions'][region]['distribution'][distro]

    if not env.state:
        create_new_vm()
    else:
        connect_to_cloud_provider()

        if cloud in ['ec2']:
            up_ec2(connection=env.connection,
                   region=region,
                   instance_id=env.config['instance_id'])

        if cloud in ['rackspace']:
            log_red('fab up operations not implemented for Rackspace ')

        if cloud == 'gce':
            f_up(cloud='gce',
                 project=k['project'],
                 zone=k['region'],
                 username=k['username'],
                 machine_type=k['machine_type'],
                 base_image_prefix=k['base_image_prefix'],
                 base_image_project=k['base_image_project'],
                 public_key=k['public_key'],
                 instance_name=env.config['instance_name'],
                 disk_name=env.config['instance_name'])


@task
def startup_gce_jenkins_slave(cloud, slave_image):
    """
    Background: At this time, jclouds and the Jenkins jclouds plugin
    don't work correctly on GCE.  Until this is fixed we're going to
    have static slaves running our GCE builds.

    This function will spin up a slave instance in GCE running the
    specified image (that should have already been provisioned via
    ``fab it``.
    """

    if 'ubuntu' in slave_image:
        distribution = 'ubuntu14.04'
    elif 'centos' in slave_image:
        distribution = 'centos7'
    else:
        raise RuntimeError("could not parse distribution from image"
                           "{}".format(slave_image))
    creation_args = C[cloud][distribution]['creation_args']
    jenkins_public_key = (segredos()['env']['default']['ssh']['ssh_keys']
                          [1]['contents'][0])
    username = 'jenkins'
    instance_name = u"jenkins-slave-image-" + unicode(uuid.uuid4())
    f_startup_gce_instance(instance_name,
                           creation_args['project'],
                           creation_args['zone'],
                           username,
                           creation_args['machine_type'],
                           slave_image,
                           jenkins_public_key)


@task
def cloud(cloud_provider):
    env.config['cloud'] = cloud_provider

# GCE environment variables,
    if 'gce' in cloud_provider:
        gce_private_key_filename = os.environ['GCE_PRIVATE_KEY']
        with open(os.environ['GCE_PUBLIC_KEY'], 'r') as f:
            gce_public_key = f.read()
        gce_project = os.environ['GCE_PROJECT']
        gce_zone = os.environ['GCE_ZONE']
        gce_machine_type = os.getenv('GCE_MACHINE_TYPE', 'n1-standard-2')


@task
def distribution(linux_distro):
    env.config['distribution'] = linux_distro


@task
def region(cloud_region):
    env.config['region'] = cloud_region


"""
    ___main___
"""

load_config()
