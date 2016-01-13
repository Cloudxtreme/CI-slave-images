# vim: ai ts=4 sts=4 et sw=4 ft=python fdm=indent et foldlevel=0

# test functions for the different image types


import re
from fabric.api import sudo, env, run
from bookshelf.api_v1 import (log_green,
                              load_state_from_disk)
from fabric.context_managers import settings
from envassert import (file,
                       process,
                       package,
                       user,
                       group,
                       detect,
                       port)

from lib.bootstrap import (local_docker_images,
                           ubuntu14_required_packages,
                           centos7_required_packages)


def acceptance_tests(distribution):
    """ proxy function that calls acceptance tests for speficic OS

    :param string distribution: which OS to use 'centos7', 'ubuntu1404'
    """

    # run common tests for all platforms
    acceptance_tests_common_tests_for_flocker(distribution)

    if 'ubuntu' in distribution.lower():
        acceptance_tests_on_ubuntu14_img_for_flocker(distribution)

    if 'centos' in distribution.lower():
        acceptance_tests_on_centos7_img_for_flocker(distribution)


def acceptance_tests_common_tests_for_flocker(distribution):
    """ Runs checks that are common to all platforms related to Flocker

    :param string distribution: which OS to use 'centos7', 'ubuntu1404'
    """

    ec2_host = "%s@%s" % (env.user, load_state_from_disk()['ip_address'])
    with settings(host_string=ec2_host):

        env.platform_family = detect.detect()

        # Jenkins should call the correct interpreter based on the shebang
        # However,
        # We noticed that our Ubuntu /bin/bash calls were being executed
        # as /bin/sh.
        # So we as part of the slave image build process symlinked
        # /bin/sh -> /bin/bash.
        # https://clusterhq.atlassian.net/browse/FLOC-2986
        log_green('check that /bin/sh is symlinked to bash')
        assert file.is_link("/bin/sh")
        assert 'bash' in run('ls -l /bin/sh')

        # umask needs to be set to 022, so that the packages we build
        # through the flocker tests have the correct permissions.
        # otherwise rpmlint fails with permssion errors.
        log_green('check that our umask matches 022')
        assert '022' in run('umask')

        # we need to keep the PATH so that we can run virtualenv with sudo
        log_green('check that the environment is not reset on sudo')
        assert sudo("sudo grep "
                    "'Defaults:\%wheel\ \!env_reset\,\!secure_path'"
                    " /etc/sudoers")

        # the run acceptance tests fail if we don't have a known_hosts file
        # so we make sure it exists
        log_green('check that /root/.ssh/known_hosts exists')

        # known_hosts needs to have 600 permissions
        assert sudo("ls /root/.ssh/known_hosts")
        assert "600" in sudo("stat -c %a /root/.ssh/known_hosts")

        # fpm is used for building RPMs/DEBs
        log_green('check that fpm is installed')
        assert 'fpm' in sudo('gem list')

        # A lot of Flocker tests use different docker images,
        # we don't want to have to download those images every time we
        # spin up a new slave node. So we make sure they are cached
        # locally when we bake the image.
        log_green('check that images have been downloaded locally')
        for image in local_docker_images():
            log_green(' checking %s' % image)
            if ':' in image:
                parts = image.split(':')
                expression = parts[0] + '.*' + parts[1]
                assert re.search(expression, sudo('docker images'))
            else:
                assert image in sudo('docker images')

        # CentOS 7 provides us with a fairly old git version, we install
        # a recent version in /usr/local/bin
        log_green('check that git is installed locally')
        assert file.exists("/usr/local/bin/git")

        # and then update the PATH so that our new git comes first
        log_green('check that /usr/local/bin is in path')
        assert '/usr/local/bin/git' in run('which git')

        # update pip
        # We have a devpi cache in AWS which we will consume instead of
        # going upstream to the PyPi servers.
        # We specify that devpi caching server using -i \$PIP_INDEX_URL
        # which requires as to include --trusted_host as we are not (yet)
        # using  SSL on our caching box.
        # The --trusted-host option is only available with pip 7
        log_green('check that pip is the latest version')
        assert '7.' in run('pip --version')

        # The /tmp/acceptance.yaml file is deployed to the jenkins slave
        # during bootstrapping. These are copied from the Jenkins Master
        # /etc/slave_config directory.
        # We just need to make sure that directory exists.
        log_green('check that /etc/slave_config exists')
        assert file.dir_exists("/etc/slave_config")
        assert file.mode_is("/etc/slave_config", "777")

        # pypy will be used in the acceptance tests
        log_green('check that pypy is available')
        assert '2.6.1' in run('pypy --version')

        # the client acceptance tests run on docker instances
        log_green('check that docker is running')
        assert sudo('docker --version | grep "1.9."')
        assert process.is_up("docker")


def acceptance_tests_on_centos7_img_for_flocker(distribution):
    """ checks that the CentOS 7 image is suitable for running the Flocker
    acceptance tests

    :param string distribution: which OS to use 'centos7', 'ubuntu1404'
    """

    ec2_host = "%s@%s" % (env.user, load_state_from_disk()['ip_address'])
    with settings(host_string=ec2_host):

        env.platform_family = detect.detect()

        # disable requiretty
        # http://tinyurl.com/peoffwk
        log_green("check that tty are not required when sudo'ing")
        assert sudo('grep "^\#Defaults.*requiretty" /etc/sudoers')

        # the epel-release repository is required for a bunch of packages
        log_green('assert that EPEL is installed')
        assert package.installed('epel-release')

        # make sure we installed all the packages we need
        log_green('assert that required rpm packages are installed')
        for pkg in centos7_required_packages():
            # we can't check meta-packages
            if '@' not in pkg:
                log_green('... checking %s' % pkg)
                assert package.installed(pkg)

        # ZFS will be required for the ZFS acceptance tests
        log_green('check that the zfs repository is installed')
        assert package.installed('zfs-release')

        log_green('check that zfs from testing repository is installed')
        assert run(
            'grep "SPL_DKMS_DISABLE_STRIP=y" /etc/sysconfig/spl')
        assert run(
            'grep "ZFS_DKMS_DISABLE_STRIP=y" /etc/sysconfig/zfs')
        assert package.installed("zfs")
        assert run('lsmod |grep zfs')

        # We now need SELinux enabled
        log_green('check that SElinux is enforcing')
        assert sudo('getenforce | grep -i "enforcing"')

        # And Firewalld should be running too
        log_green('check that firewalld is enabled')
        assert sudo("systemctl is-enabled firewalld")

        # EL, won't allow us to run docker as non-root
        # http://tinyurl.com/qfuyxjm
        # but our tests require us to, so we add the 'centos' user to the
        # docker group.
        # and the jenkins bootstrapping of the node will change the
        # docker sysconfig file to run as 'docker' group.
        # TODO: move that jenkins code here
        # https://clusterhq.atlassian.net/browse/FLOC-2995
        log_green('check that centos is part of group docker')
        assert user.exists("centos")
        assert group.is_exists("docker")
        assert user.is_belonging_group("centos", "docker")

        # the acceptance tests look for a package in a yum repository,
        # we provide one by starting a webserver and pointing the tests
        # to look over there.
        # for that we need 'nginx' installed and running
        log_green('check that nginx is running')
        assert package.installed('nginx')
        assert port.is_listening(80, "tcp")
        assert process.is_up("nginx")
        assert sudo("systemctl is-enabled nginx")

        # the client acceptance tests run on docker instances
        log_green('check that docker is running')
        assert sudo('rpm -q docker-engine | grep "1.9."')
        assert process.is_up("docker")
        assert sudo("systemctl is-enabled docker")


def acceptance_tests_on_ubuntu14_img_for_flocker(distribution):
    """ checks that the Ubuntu 14 image is suitable for running the Flocker
    acceptance tests

        :param string distribution: which OS to use 'centos7', 'ubuntu1404'
    """

    ec2_host = "%s@%s" % (env.user, load_state_from_disk()['ip_address'])
    with settings(host_string=ec2_host):

        env.platform_family = detect.detect()

        # Jenkins should call the correct interpreter based on the shebang
        # However,
        # We noticed that our Ubuntu /bin/bash call were being executed
        # as /bin/sh.
        # So we as part of the slave image build process symlinked
        # /bin/sh -> /bin/bash.
        # https://clusterhq.atlassian.net/browse/FLOC-2986
        log_green('check that /bin/sh is symlinked to bash')
        assert file.is_link("/bin/sh")
        assert 'bash' in run('ls -l /bin/sh')

        # the client acceptance tests run on docker instances
        log_green('check that docker is enabled')
        assert 'docker' in run('ls -l /etc/init')

        # make sure we installed all the packages we need
        log_green('assert that required deb packages are installed')
        for pkg in ubuntu14_required_packages():
            log_green('... checking package: %s' % pkg)
            assert package.installed(pkg)

        # Our tests require us to run docker as ubuntu.
        # So we add the user ubuntu to the docker group.
        # During bootstrapping of the node, jenkins will update the init
        # file so that docker is running with the correct group.
        # TODO: move that jenkins code here
        log_green('check that ubuntu is part of group docker')
        assert user.exists("ubuntu")
        assert group.is_exists("docker")
        assert user.is_belonging_group("ubuntu", "docker")

        # the acceptance tests look for a package in a yum repository,
        # we provide one by starting a webserver and pointing the tests
        # to look over there.
        # for that we need 'nginx' installed and running
        log_green('check that nginx is running')
        assert package.installed('nginx')
        assert port.is_listening(80, "tcp")
        assert process.is_up("nginx")
        assert 'nginx' in run('ls -l /etc/init.d/')
