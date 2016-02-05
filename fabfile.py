# vim: ai ts=4 sts=4 et sw=4 ft=python fdm=indent et

# fabric task file for building new CI slave images
#
# usage:
#       fab help
#


import os
import json
from datetime import datetime
from fabric.api import task, env
from pprint import PrettyPrinter
import sys

from bookshelf.api_v1 import (up as f_up,
                              down as f_down,
                              destroy as f_destroy)


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
from bookshelf.api_v3.gce import GCE
from bookshelf.api_v3.rackspace import Rackspace
from bookshelf.api_v1 import ssh_session

from lib.mycookbooks import (setup_fab_env,
                             parse_config,
                             has_state,
                             load_state,
                             save_state)


from lib.bootstrap import (bootstrap_jenkins_slave_centos7,
                           bootstrap_jenkins_slave_ubuntu14)

from tests.acceptance import acceptance_tests


CLOUD_YAML_FILE = {
    'gce': 'gce.yaml',
    'ec2': 'ec2.yaml',
    'rackspace': 'rackspace.yaml'
}


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


def get_config():
    if not has_state():
        raise Exception("Can't get a config without a state file")
    saved_state = load_state()
    cloud = saved_state['cloud']
    config = parse_config(CLOUD_YAML_FILE[cloud])
    return config


def create_new_instance_from_config(cloud, distro, region):
    config = parse_config(CLOUD_YAML_FILE[cloud])
    env.user = config['username']
    env.key_filename = config['private_key_filename']
    if cloud == 'ec2':
        raise NotImplementedError("ec2 is not implemented yet")
    elif cloud == 'rackspace':
        return Rackspace.create_from_config(config, distro, region)
    elif cloud == 'gce':
        return GCE.create_from_config(config, distro, region)


def create_instance_from_saved_state():
    saved_state = load_state()
    cloud = saved_state['cloud']
    if 'cloud' in env.config and env.config['cloud']:
        if cloud != env.config['cloud']:
            log_red("The specified cloud: {} does not match the cloud "
                    "specified in the saved state file: {}".format(
                        env.config['cloud'], cloud))
            sys.exit(1)

    config = parse_config(CLOUD_YAML_FILE[cloud])
    env.user = config['username']
    env.key_filename = config['private_key_filename']

    instance = None
    if cloud == 'ec2':
        raise NotImplementedError("ec2 is not implemented yet")
    elif cloud == 'rackspace':
        instance = Rackspace.create_from_saved_state(
            config,saved_state['data']
        )
    elif cloud == 'gce':
        instance = GCE.create_from_saved_state(config, saved_state['data'])
    else:
        raise RuntimeError("unknown cloud type {}".format(cloud))
    # bringing the instance up can change the IP address
    # go ahead and re-save the state
    save_state(instance)
    return instance


@task
def create_image():
    """ create ami/image for either AWS, Rackspace or GCE """
    datestr = datetime.utcnow().strftime("%Y%m%d%H%M")
    instance = create_instance_from_saved_state()
    save_state(instance)
    image_name = "{}-{}".format(instance.description, datestr)
    instance.create_image(image_name)

    log_green('created server image: %s' % image_name)


@task
def destroy():
    """ destroy an existing instance """

    instance = create_instance_from_saved_state()
    instance.destroy()
    os.unlink('.state.json')

@task
def down():
    """ halt an existing instance """
    instance = create_instance_from_saved_state()
    instance.down()


@task
def bootstrap():
    """ bootstraps an existing running instance

    :param string distribution: which OS to use 'centos7', 'ubuntu1404'
    """
    config = get_config()
    instance = create_instance_from_saved_state()

    if 'centos7' in instance.distro:
        bootstrap_jenkins_slave_centos7(config, instance)

    if 'ubuntu14' in instance.distro:
        bootstrap_jenkins_slave_ubuntu14(config, instance)


@task
def status():
    """ returns current status of the instance """

    #cloud, region, distro, k = cloud_region_distro_config()
    #config, state = get_config_and_state()
    config = get_config()
    #data = env.config
    pp = PrettyPrinter(indent=4)
    pp.pprint(config)
    #pp.pprint(state)


@task
def ssh(*cli):
    """ opens an ssh connection to the instance

    :param string cli: the commands to run on the host
    """
    #config, state = get_config_and_state()
    config = get_config()

    instance = create_instance_from_saved_state()


    ssh_session(key_filename=config['public_key_filename'],
                username=config['username'],
                ip_address=instance.ip_address,
                *cli)


@task
def tests():
    """ run tests against an existing instance """
    config = get_config()
    state = load_state()
    acceptance_tests(state['distro'], config)



@task
def up():
    """
    boots a new instance on the specified cloud provider
    """
    # XXX: if the saved state doesn't agree with our environment vars,
    # throw an exception and tell the user to remove the saved state
    cloud = env.config['cloud']
    distro = env.config['distribution']
    region = env.config['region']

    if not has_state():
        instance = create_new_instance_from_config(cloud, distro, region)
    else:
        instance = create_instance_from_saved_state()
    save_state(instance)


@task
def cloud(cloud_provider):
    env.config['cloud'] = cloud_provider


@task
def distribution(linux_distro):
    env.config['distribution'] = linux_distro


@task
def region(cloud_region):
    env.config['region'] = cloud_region


"""
    ___main___
"""

setup_fab_env()
