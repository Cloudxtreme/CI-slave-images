// vim: ai ts=2 sts=2 et sw=2 ft=groovy fdm=indent et foldlevel=0
// jobs.groovy

// set the GitHub username and repository, and the URL to that same repo
def project = 'ClusterHQ/CI-slave-images'
def git_url = 'https://github.com/ClusterHQ/CI-slave-images.git'

// build functions and steps below this point

def hashbang = """
  #!/bin/bash -l
  # don't leak secrets
  set +x
  set -e

  """.stripIndent()


def add_shell_functions = '''
  # The long directory names where we build our code cause pip to fail.
  # https://gitlab.com/gitlab-org/gitlab-ci-multi-runner/issues/20
  # http://stackoverflow.com/questions/10813538/shebang-line-limit-in-bash-and-linux-kernel
  # https://github.com/spotify/dh-virtualenv/issues/10
  # so we set our virtualenv dir to live in /tmp/<random number>
  #
  export venv=/tmp/${RANDOM}
  # make sure the virtualenv doesn't already exist
  while [ -e ${venv} ]
  do
    export venv=/tmp/${RANDOM}
  done

  '''.stripIndent()


def setup_venv = '''
  # Set up the new venv.
  virtualenv -p python2.7 --clear ${venv}
  . ${venv}/bin/activate
  # Report the version of Python we're using, to aid debugging.
  ${venv}/bin/python --version

  '''.stripIndent()


def pip_install = """
  pip install -r requirements.txt
  """.stripIndent()


def clone_segredos = """
  ssh-keyscan -H github.com >> ~/.ssh/known_hosts
  rm -rf segredos
  git clone git@github.com:ClusterHQ/segredos.git
  """.stripIndent()


def run_fabric = '''
  fab cloud:$CLOUD distribution:$DISTRIBUTION region:$REGION up
  fab bootstrap
  fab tests
  fab create_image
  fab destroy
  '''.stripIndent()


def escape_name(name) {
    /*
        Escape a name to make it suitable for use in a path.
        :param unicode name: the name to escape.
        :return unicode: the escaped name.
    */
    return name.replace('/', '-')
}

def full_job_name(dashProject, dashBranchName, job_name) {
    /*
        Return the full job name (url path) given the constituent parts
        :param unicode dashProject: the name of the top-level project,
            escaped for use in a path.
        :param unicode dashBranchName: the name of the branch,
            escaped for use in a path.
        :param unicode job_name: the sub-task name,
            escaped for use in a path.
        :return unicode: the full name
    */
    return folder_name(dashProject, dashBranchName) + "/${job_name}"
}

// list of clouds, regions, linux distributions for jenkins jobs.
def on_clouds = [
  ec2:[regions: ['eu-central-1',
                 'ap-southeast-1',
                 'ap-northeast-1',
                 'ap-southeast-2',
                 'sa-east-1',
                 'us-west-1',
                 'us-west-2'],
       distributions: [ 'centos7', 'ubuntu1404'] ],

  rackspace:[regions: ['IAD',
                       'DFW',
                       'HKG'],
             distributions: [ 'centos7', 'ubuntu1404'] ],

  gce: [regions: [],
        distributions: [ 'centos7',
                         'ubuntu1404'] ]
]

// job build steps
def with_steps = hashbang +
                 add_shell_functions +
                 setup_venv +
                 pip_install +
                 clone_segredos +
                 run_fabric

// Which slave to run this job
def on_label = 'aws-centos-7-T2Medium_32_executors'

// list of tabs to generate on each feature branch folder
def with_views = [
  on_aws:[description: 'All AWS Jobs',
          regex: '(.*_(?i)aws_.*.*)' ],

  on_rackspace:[description: 'All Rackspace Jobs',
                regex: '(.*_(?i)rackspace_.*.*)' ],

  on_centos_7:[description: 'All Centos Jobs',
               regex: '(.*_(?i)Centos7)' ],

  on_ubuntu_14_04_LTS:[description: 'All Ubuntu Trusty (14.04) Jobs',
                       regex: '(.*_(?i)ubuntu1404)' ]
]

// AWS parameters
def aws_parameters = [
  AWS_ACCESS_KEY_ID:[
    child_job_value:'${AWS_ACCESS_KEY_ID}',
    multijob_value: 'FILL_ME_IN',
    description:'AWS Access key'],

  AWS_SECRET_ACCESS_KEY: [
    child_job_value:'${AWS_SECRET_ACCESS_KEY}',
    multijob_value: 'FILL_ME_IN',
    description:'AWS Secret Key'],

  AWS_KEY_FILENAME:[
    child_job_value:'${AWS_KEY_FILENAME}',
    multijob_value: '~/.ssh/id_rsa',
    description:'Full path to the Jenkins Slave SSH private key'],

  AWS_KEY_PAIR:[
    child_job_value:'${AWS_KEY_PAIR}',
    multijob_value: 'jenkins-slave',
    description:'Name of the AWS key-pair to use'],
]

// Rackspace parameters
def rackspace_parameters = [
  OS_USERNAME:[
    child_job_value:'${OS_USERNAME}',
    multijob_value: 'FILL_ME_IN',
    description:'Rackspace Username'],

  OS_PASSWORD:[
    child_job_value:'${OS_PASSWORD}',
    multijob_value: 'FILL_ME_IN',
    description:'Rackspace API key'],

  OS_TENANT_NAME:[
    child_job_value:'${OS_TENANT_NAME}',
    multijob_value: '929000',
    description:'Rackspace Tenant ID'],

  RACKSPACE_KEY_PAIR:[
    child_job_value:'${RACKSPACE_KEY_PAIR}',
    multijob_value: 'jenkins-slave',
    description:'Rackspace SSH key-pair name'],

  RACKSPACE_KEY_FILENAME:[
    child_job_value:'${RACKSPACE_KEY_FILENAME}',
    multijob_value: '~/.ssh/id_rsa',
    description:'Full path to the Rackspace key-pair to use'],

  RACKSPACE_PUBLIC_KEY_FILENAME: [
    child_job_value:'${RACKSPACE_PUBLIC_KEY_FILENAME}',
    multijob_value: '~/.ssh/id_rsa.pub',
    description:'Full path to the Rackspace public key'],

  OS_AUTH_SYSTEM:[
    child_job_value:'${OS_AUTH_SYSTEM}',
    multijob_value: 'rackspace',
    description:'Openstack Authentication method'],

  OS_AUTH_URL:[
    child_job_value:'${OS_AUTH_URL}',
    multijob_value: 'https://identity.api.rackspacecloud.com/v2.0/',
    description:'Keystone URL'],

  OS_NO_CACHE:[
    child_job_value:'${OS_NO_CACHE}',
    multijob_value: '1',
    description:''],
]

// GCE parameters
def gce_parameters = [
  GCE_PROJECT: [
    child_job_value:'${GCE_PROJECT}',
    multijob_value: 'FILL_ME_IN',
    description:''],

  GCE_ZONE: [
    child_job_value:'${GCE_ZONE}',
    multijob_value: 'FILL_ME_IN',
    description:''],

  GCE_PUBLIC_KEY: [
    child_job_value:'${GCE_PUBLIC_KEY}',
    multijob_value: 'FILL_ME_IN',
    description:''],

  GCE_PRIVATE_KEY: [
    child_job_value:'${GCE_PRIVATE_KEY}',
    multijob_value: 'FILL_ME_IN',
    description:''],
]

// parameters that are common to every job
def common_parameters = [
  TRIGGERED_BRANCH:[
    child_job_value:'${RECONFIGURE_BRANCH}',
    multijob_value: '${RECONFIGURE_BRANCH}',
    description:'Branch that triggered this job'] +

    aws_parameters +
    rackspace_parameters +
    gce_parameters
]

// parameters for the child jobs
def child_job_parameters(cloud, distribution, region) {
  return {
    common_parameters.each { k, v ->
      stringParam(k, v.child_job_value)
    }

    // these are the fabric run options to use
    stringParam("CLOUD", cloud)
    stringParam("DISTRIBUTION", distribution)
    stringParam("AWS_REGION", region)
    stringParam("OS_REGION_NAME", region)
    stringParam("REGION", region)
  }
}

// parameters for the multijob
def multijob_parameters = {
  return {
    common_parameters.each { k, v ->
      stringParam(k, v.multijob_value)
    }
  }
}

// parameters to define in the multijob for the child jobs
def multijob_child_job_parameters(cloud, distribution, region) {
  return {
    common_parameters.each { k, v ->
      predefinedProp(k, v.child_job_value)
    }

    // these are the fabric run options to use
    predefinedProp('AWS_REGION', region)
    predefinedProp('OS_REGION_NAME', region)
    predefinedProp('CLOUD', cloud)
    predefinedProp('DISTRIBUTION', distribution)
  }
}


dashBranchName = escape_name("${RECONFIGURE_BRANCH}")

dashProject = escape_name(project)

// placeholder for our branch
folder(dashProject + '/' + dashBranchName )


// generate all the views
for (view in with_views.keySet()) {
     values = with_views.get(view)

      view_path = dashProject + '/' + dashBranchName + '/' + view

      listView(view_path) {
      description(values['description'])
      filterBuildQueue()
      filterExecutors()
      jobs {
        regex(values['regex'])
      }
      columns {
          status()
          weather()
          name()
          lastSuccess()
          lastFailure()
          lastDuration()
          buildButton()
      }
  }
}

// generate all the child jobs for our multijob
for (cloud in on_clouds.keySet()) {
  values = on_clouds.get(cloud)

  for (region in values['regions']) {

    for (distribution in values['distributions']) {

      job_name = dashProject + '/' + dashBranchName + '/' + 'run_' +
        cloud + '_' + region + '_' + distribution

      job(job_name) {
        parameters {
          child_job_parameters(cloud, distribution, region)
        }

        scm {
          git {
            cloneTimeout(2)
            remote {
              name("upstream")
              github(project)
            }
            configure { node ->
              node / gitConfigName('Jenkins')
              node / gitConfigEmail('jenkins@clusterhq.com')
            }
            branch("${RECONFIGURE_BRANCH}")
            clean(true)
            createTag(false)
            mergeOptions {
              remote('upstream')
              branch('master')
              strategy('recursive')
            }
          }
        }

        wrappers {
            timestamps()
            colorizeOutput()
        }

        label(on_label)

        steps {
          shell(with_steps)
        }
      }
    }
  }
}

// generate our multijob
job_name = dashProject + '/' + dashBranchName + '/' + '__main_multijob'

multiJob(job_name) {

  parameters {
    multijob_parameters()
  }

  wrappers {
    timestamps()
    colorizeOutput()
  }

  steps {
    shell('rm -rf *')
    phase('parallel_tests') {
      continuationCondition('SUCCESSFUL')

      for (cloud in on_clouds.keySet()) {
        values = on_clouds.get(cloud)

        for (region in values['regions']) {

          for (distribution in values['distributions']) {

            job_name = dashProject + '/' + dashBranchName + '/' + 'run_' +
              cloud + '_' + region + '_' + distribution

            phaseJob(job_name) {
              killPhaseCondition("NEVER")
              currentJobParameters(true)
              parameters {
                multijob_child_job_parameters(cloud, distribution, region)
              }
            }
          }
        }
      }
    }
  }
}
