// vim: ai ts=2 sts=2 et sw=2 ft=groovy fdm=indent et foldlevel=0
// jobs.groovy

def project = 'ClusterHQ/CI-slave-images'
def git_url = 'https://github.com/ClusterHQ/CI-slave-images.git'

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
  fab it:cloud=$CLOUD,distribution=$DISTRIBUTION
  '''.stripIndent()


def on_clouds = [
  ec2:[regions: ['us-west-1', 'us-west-2'],
       distributions: [ 'centos7', 'ubuntu14.04'] ],

  rackspace:[regions: ['IAD', 'DFW'],
             distributions: [ 'centos7', 'ubuntu14.04'] ],

  gce: [regions: [],
        distributions: [ 'centos7', 'ubuntu14.04'] ]
]

def on_nodes_with_labels = 'aws-centos-7-T2Smal'

def with_steps = hashbang +
                 add_shell_functions +
                 setup_venv +
                 pip_install +
                 clone_segredos +
                 run_fabric


def timeout = 90

def on_label = 'aws-centos-7-T2Small'

def with_views = [
  on_aws:[description: 'All AWS Jobs',
          regex: '(.*_(?i)aws_.*.*)' ],

  on_rackspace:[description: 'All Rackspace Jobs',
                regex: '(.*_(?i)rackspace_.*.*)' ],

  on_centos_7:[description: 'All Centos Jobs',
               regex: '(.*_(?i)Centos_.*.*)' ],

  on_ubuntu_14_04_LTS:[description: 'All Ubuntu Trusty (14.04) Jobs',
                       regex: '(.*_(?i)trusty_.*.*)' ]
]

def jobs_parameters = [
  AWS_ACCESS_KEY_ID:[
  TRIGGERED_BRANCH:[
    default_value:'${RECONFIGURE_BRANCH}', description:''],

    default_value:'${AWS_ACCESS_KEY_ID}', description:''],
  AWS_SECRET_ACCESS_KEY: [
    default_value:'${AWS_SECRET_ACCESS_KEY}', description:''],
  AWS_KEY_FILENAME:[
    default_value:'${AWS_KEY_FILENAME}', description:''],
  AWS_KEY_PAIR:[
    default_value:'${AWS_KEY_PAIR}', description:''],

  OS_USERNAME:[
    default_value:'${OS_USERNAME}', description:''],
  OS_PASSWORD:[
    default_value:'${OS_PASSWORD}', description:''],
  OS_TENANT_NAME:[
    default_value:'${OS_TENANT_NAME}', description:''],
  RACKSPACE_KEY_PAIR:[
    default_value:'${RACKSPACE_KEY_PAIR}', description:''],
  RACKSPACE_KEY_FILENAME:[
    default_value:'${RACKSPACE_KEY_FILENAME}', description:''],
  OS_AUTH_SYSTEM:[
    default_value:'${OS_AUTH_SYSTEM}', description:''],
  OS_AUTH_URL:[
    default_value:'${OS_AUTH_URL}', description:''],
  OS_NO_CACHE:[
    default_value:'${OS_NO_CACHE}', description:'']
]





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


dashBranchName = escape_name("${RECONFIGURE_BRANCH}")

dashProject = escape_name(project)

folder(dashProject + '/' + dashBranchName )

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

for (cloud in on_clouds.keySet()) {
  values = on_clouds.get(cloud)
  println(values)

  for (region in values['regions']) {

    for (distribution in values['distributions']) {

      job_name = dashProject + '/' + dashBranchName + '/' + 'run_' +
        cloud + '_' + region + '_' + distribution

      job(job_name) {
        parameters {

          jobs_parameters.each { k, v ->
            stringParam(k, v.default_value)
          }

          stringParam("CLOUD", cloud)
          stringParam("DISTRIBUTION", distribution)
          stringParam("AWS_REGION", region)
          stringParam("OS_REGION_NAME", region)


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

job_name = dashProject + '/' + dashBranchName + '/' + '__main_multijob'

multiJob(job_name) {

  parameters {
    stringParam("TRIGGERED_BRANCH", "${RECONFIGURE_BRANCH}",
                  "Branch that triggered this job" )
    stringParam("AWS_ACCESS_KEY_ID", 'FILL_ME_IN')
    stringParam("AWS_SECRET_ACCESS_KEY", 'FILL_ME_IN')
    stringParam("AWS_KEY_FILENAME", '~/.ssh/id_rsa')
    stringParam("AWS_KEY_PAIR", 'jenkins-slave')

    stringParam("OS_USERNAME", 'FILL_ME_IN')
    stringParam("OS_PASSWORD", 'FILL_ME_IN')
    stringParam("OS_TENANT_NAME", '929000')
    stringParam("OS_NO_CACHE", '1')
    stringParam("RACKSPACE_KEY_PAIR", 'jenkins-slave')
    stringParam("RACKSPACE_KEY_FILENAME", '~/.ssh/id_rsa')
    stringParam("OS_AUTH_SYSTEM", 'rackspace')
    stringParam("OS_AUTH_URL", 'https://identity.api.rackspacecloud.com/v2.0/')


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
                jobs_parameters.each { k, v ->
                  predefinedProp(k, v.default_value)
                }

                predefinedProp('AWS_REGION', region)
                predefinedProp('OS_REGION_NAME', region)
                predefinedProp('CLOUD', cloud)
                predefinedProp('DISTRIBUTION', distribution)

              }
            }
          }
        }
      }
    }
  }
}
