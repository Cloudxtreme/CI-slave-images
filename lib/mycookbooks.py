# vim: ai ts=4 sts=4 et sw=4 ft=python fdm=indent et foldlevel=0

""" Collection of helpers for fabric tasks

Contains a collection of helper functions for fabric task used in this
fabfile.
List them a-z if you must.
"""

import os
import sys
import yaml
import re
import json

from time import sleep

from fabric.api import sudo, env
from fabric.context_managers import settings, cd, hide
from fabric.contrib.files import (sed,
                                  exists as file_exists,
                                  append as file_append)

from cuisine import (user_ensure,
                     group_ensure,
                     group_user_ensure)

from bookshelf.api_v1 import (dir_ensure,
                              file_attribs,
                              log_green,
                              enable_firewalld_service,
                              log_yellow,
                              add_firewalld_port,
                              systemd,
                              reboot,
                              yum_install)


STATE_FILE_NAME = '.state.json'


def add_user_to_docker_group(distro):
    """ make sure the user running jenkins is part of the docker group """
    log_green('adding the user running jenkins into the docker group')

    with settings(hide('warnings', 'running', 'stdout', 'stderr'),
                  warn_only=True, capture=True):
        if 'centos' in distro.value:
            user_ensure('centos', home='/home/centos', shell='/bin/bash')
            group_ensure('docker', gid=55)
            group_user_ensure('docker', 'centos')

        if 'ubuntu' in distro.value:
            user_ensure('ubuntu', home='/home/ubuntu', shell='/bin/bash')
            group_ensure('docker', gid=55)
            group_user_ensure('docker', 'ubuntu')


def create_etc_slave_config():
    """ creates /etc/slave_config directory on master

    /etc/slave_config is used by jenkins slave_plugin.
    it allows files to be copied from the master to the slave.
    These files are copied to /etc/slave_config on the slave.
    """
    # TODO: fix these permissions, likely ubuntu/centos/jenkins users
    # need read/write permissions.
    log_green('create /etc/slave_config')
    with settings(hide('warnings', 'running', 'stdout', 'stderr'),
                  warn_only=True, capture=True):
        dir_ensure('/etc/slave_config', mode="777", use_sudo=True)


def fix_umask(username):
    """ Sets umask to 022

    fix an issue with the the build package process where it fails, due
    the files in the produced package have the wrong permissions.
    """
    with settings(hide('warnings', 'running', 'stdout', 'stderr'),
                  warn_only=True, capture=True):

        sed('/etc/login.defs',
            'USERGROUPS_ENAB.*yes', 'USERGROUPS_ENAB no',
            use_sudo=True)

        sed('/etc/login.defs',
            'UMASK.*', 'UMASK  022',
            use_sudo=True)

        homedir = '/home/' + username + '/'
        for f in [homedir + '.bash_profile',
                  homedir + '.bashrc']:
            file_append(filename=f, text='umask 022')
            file_attribs(f, mode=750, owner=username)


def get_cloud_environment():
    """ returns cloud_type from command line arguments

    returns the cloud type from a fab execution string:
    fab it:cloud=rackspace,distribution=centos7
    """
    clouds = []
    for action in sys.argv:
        if 'cloud=ec2' in action:
            clouds.append('ec2')
        if 'cloud=rackspace' in action:
            clouds.append('rackspace')
        if 'cloud=gce' in action:
            clouds.append('gce')
    return clouds


def install_docker():
    """ installs latest docker """
    sudo('curl -sSL https://get.docker.com/ | sh')


def install_nginx(username):
    """ installs nginx

        nginx is used for the packaging process.
        the acceptance tests will produce a rpm/deb package.
        that package is then made available on http so that the acceptance
        test node can connect to it as a yub/deb repository and download,
        install the package during the acceptance tests.
    """

    if 'centos' in username:
        yum_install(packages=['nginx'])
        systemd('nginx', start=False, unmask=True)
        systemd('nginx', start=True, unmask=True)
        enable_firewalld_service()
        add_firewalld_port('80/tcp', permanent=True)
    if 'ubuntu' in username:
        sudo('apt-get -y install nginx')
        # systemd('nginx', start=False, unmask=True)
        # systemd('nginx', start=True, unmask=True)
        # enable_firewalld_service()
        # add_firewalld_port('80/tcp', permanent=True)
    # give it some time for the dockerd to restart
    sleep(20)


def local_docker_images():
    return ['busybox',
            'openshift/busybox-http-app',
            'python:2.7-slim',
            'clusterhqci/fpm-ubuntu-trusty',
            'clusterhqci/fpm-ubuntu-vivid',
            'clusterhqci/fpm-centos-7']


def segredos():
    secrets = yaml.load(open('segredos/ci-platform/all/all.yaml', 'r'))
    return secrets


def symlink_sh_to_bash(distro):
    """ Forces /bin/sh to point to /bin/bash

    jenkins seems to default to /bin/dash instead of bash
    on ubuntu. There is a shell config parameter that I haven't
    to set, so in order to force ubuntu nodes to execute jobs
    using bash, let's symlink /bin/sh -> /bin/bash
    """
    # read distribution from state file
    if 'ubuntu' in distro.value.lower():
        sudo('/bin/rm /bin/sh')
        sudo('/bin/ln -s /bin/bash /bin/sh')


def install_python_pypy(version,
                        replace=False,
                        pypy_home='/opt/python-pypy',
                        mode='755'):
    """ installs python pypy """
    dir_ensure(pypy_home, mode=mode, use_sudo=True)
    pypy_path = "%s/%s/bin/pypy" % (pypy_home, version)
    pathname = "pypy-%s-linux_x86_64-portable" % version
    tgz = "%s.tar.bz2" % pathname
    url = "https://bitbucket.org/squeaky/portable-pypy/downloads/%s" % tgz

    if not file_exists(pypy_path):
        with cd(pypy_home):
            sudo('wget -c %s' % url)
            sudo('tar xjf %s' % tgz)
            sudo('mv %s %s' % (pathname, version))
            sudo('ln -s %s /usr/local/bin/pypy' % pypy_path)


def upgrade_kernel_and_grub(do_reboot=False, log=True):
    """ updates the kernel and the grub config """

    if log:
        log_yellow('upgrading kernel')

    with settings(hide('running', 'stdout')):
        sudo('unset UCF_FORCE_CONFFOLD; '
             'export UCF_FORCE_CONFFNEW=YES; '
             'ucf --purge /boot/grub/menu.lst; '
             'export DEBIAN_FRONTEND=noninteractive ; '
             'apt-get update; '
             'apt-get -o Dpkg::Options::="--force-confnew" --force-yes -fuy '
             'dist-upgrade')
        with settings(warn_only=True):
            if do_reboot:
                if log:
                    log_yellow('rebooting host')
                reboot()


def parse_config(filename):
    """ parses the YAML config file and expands any environment variables """

    pattern = re.compile(r'^\<%= ENV\[\'(.*)\'\] %\>(.*)$')
    yaml.add_implicit_resolver("!pathex", pattern)

    def pathex_constructor(loader, node):
        value = loader.construct_scalar(node)
        envVar, remainingPath = pattern.match(value).groups()
        return os.environ[envVar] + remainingPath

    yaml.add_constructor('!pathex', pathex_constructor)

    with open(filename) as f:
        return(
            yaml.load(f)
        )


def setup_fab_env():
    # Modify some global Fabric behaviours:
    # Let's disable known_hosts, since on Clouds that behaviour can get in the
    # way as we continuosly destroy/create boxes.
    env.disable_known_hosts = True
    env.use_ssh_config = False
    env.eagerly_disconnect = True
    env.connection_attemtps = 5

    # initialise some keys
    env.config = {}

    # slurp the yaml config file
    # try:
    #     env.global_config = parse_config('config.yaml')['clouds']
    # except:
    #     raise("Unable to parse config.yaml, see README")

    # # look up our state.json file, and override any settings found
    # load_state_from_disk()


def has_state():
    if not os.path.isfile(STATE_FILE_NAME):
        return False
    try:
        with open(STATE_FILE_NAME) as data_file:
            json.load(data_file)
    except ValueError:
        return False
    return True


def load_state():
    with open(STATE_FILE_NAME) as data_file:
        return json.load(data_file)


def save_state(state):
    with open(STATE_FILE_NAME, "w") as data_file:
        json.dump(state, data_file)
