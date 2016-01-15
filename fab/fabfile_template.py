#!/usr/bin/env python


"""
Odekro deployment script
"""

import os
import time
from fabric.api import task
from fabric.api import cd, env, put, get, require
from fabric.api import local, run, sudo
from fabric.contrib.files import exists
from fab import postgres as pg
from fab import server, nginx, webapp

LOCAL_BASEDIR = os.path.abspath(os.path.dirname(__file__))
PRODUCTION_ENV_USER = ''
PRODUCTION_ENV_PASS = ''
PRODUCTION_ENV_HOST = ''
PRODUCTION_ENV_DOMAIN = ''

STAGING_ENV_USER = ''
STAGING_ENV_PASS = ''
STAGING_ENV_HOST = ''
STAGING_ENV_DOMAIN = ''

DEV_ENV_USER = ''
DEV_ENV_PASS = ''
DEV_ENV_HOST = ''
DEV_ENV_DOMAIN = ''


env.local_root = LOCAL_BASEDIR
env.use_ssh_config = True
env.log_level = 'debug'
env.is_staging = True
env.country_app = 'ghana'

env.project = 'odekro'
env.git_remote = 'origin'
env.git_branch = 'HEAD'
env.pip_requirements = 'requirements.txt'

env.dbname = 'dbname'
env.dbuser = 'dbuser'
env.dbpassword = 'password'

env.webapp_user = 'webapp_user'
env.webapp_group = 'webapp_group'

env.basedir = '/var/www/%(project)s' % env
env.virtualenv = env.basedir

# nginx
env.collected_static = '%(basedir)s/releases/collected_static' % env
env.media_root = '%(basedir)s/releases' % env
env.robots_dir = '%(basedir)s/releases/current/web' % env


@task
def upload_hansards(src):
    require('basedir')
    require('project')

    if os.path.isfile(src):
        put(src, '/tmp/')
        app('add_hansard', os.path.join('/tmp', os.path.basename(src)))
    elif os.path.isdir(src):
        try:
            local('rm -fr /tmp/debates')
        except:
            pass
        local('mkdir /tmp/debates && cp %(src)s/debate*.txt /tmp/debates' % locals())
        local('cd /tmp && tar -czf debates.tar.gz debates')
        put('/tmp/debates.tar.gz', '/tmp/')
        try:
            run('rm -fr /tmp/debates')
        except:
            pass
        run('cd /tmp && tar -xzf debates.tar.gz')
        app('add_hansard', '/tmp/debates')
    else:
        print 'Wuptidoo'


@task
def odekro(cmd):
    webapp.ctl(cmd)


@task
def app(cmd, args='', version='current'):
    require('basedir')
    require('project')

    basedir = env.basedir
    project = env.project
    virtualenv = basedir

    if args:
        args = ' %s' % args

    project_home = '%(basedir)s/releases/%(version)s/' % locals()
    with cd(project_home):
        webapp._sudo(('source %(virtualenv)s/bin/activate && '
                      '%(virtualenv)s/bin/python manage.py %(cmd)s%(args)s') % locals())


@task
def install_webapp():
    require('hosts', provided_by=[dev, staging, production])
    require('basedir')
    require('virtualenv')
    require('webapp_user')
    require('git_branch')
    webapp.install()


@task
def deploy(db=env.dbname, dbuser=env.dbuser, dbpasswd=env.dbpassword, email_passwd=None,
           version=None, init='no'):
    """Deploy latest (or a specific version) of the site.

    Deploys a version to the servers, install any required third party
    modules, install the virtual host and then restart the web app server
    """
    require('hosts', provided_by=[dev, staging, production])
    require('basedir')
    require('virtualenv')
    require('webapp_user')
    require('git_branch')
    require('project')

    restart = False

    try:
        webapp.stop()
    except:
        pass

    if not version:
        # env.version = time.strftime('%Y%m%d%H%M%S')
        env.version = time.strftime('%Y%m%d')

        webapp.upload()
        webapp.install()

        if db and dbuser and dbpasswd:
            configure(db, dbuser, dbpasswd, email_passwd, env.version)

        webapp.configure()

        if init is 'yes':
            webapp.init()

        # ensite nginx.conf -> odekro
        try:
            nginx.dissite('default')
        except:
            pass

        try:
            nginx.dissite('%(project)s' % env)
        except:
            pass

        nginx.ensite('%(basedir)s/releases/%(version)s/conf/nginx.conf' % env,
                     '%(project)s' % env)

        restart = True
    else:
        # TODO check to see if version exists
        # env.version = version
        # _symlink_current_version()
        pass

    if restart:
        nginx.reload()
        webapp.start()


@task
def setup():
    require('hosts', provided_by=[dev, staging, production])
    require('webapp_user')
    require('basedir')
    require('virtualenv')

    try:
        webapp.stop()
    except:
        pass

    prepare()

    setup_postgis()
    setup_db()

    if not exists('/etc/init.d/nginx'):
        nginx.install()


@task
def prepare():
    require('hosts')
    require('webapp_user')

    server.install_packages()
    server.create_webapp_user()
    webapp.prepare()


@task
def setup_postgis():
    require('hosts', provided_by=[dev, staging, production])
    require('basedir')
    require('virtualenv')

    try:
        # install postgres and postgis
        pg.setup_postgis()
    except:
        pass


@task
def clean():
    require('hosts', provided_by=[dev, staging, production])
    require('basedir')
    require('virtualenv')

    try:
        webapp.stop()
    except:
        pass

    try:
        sudo('rm -fr %(basedir)s' % env)
    except:
        pass


@task
def init():
    webapp.init()


# ADHOC
@task
def configure(db=env.dbname, dbuser=env.dbuser, dbpasswd=env.dbpassword, email_passwd='', version='current'):
    setup_db(db, dbuser, dbpasswd)
    configure_webapp(db, dbuser, dbpasswd, email_passwd, version)


@task
def setup_db(db=env.dbname, dbuser=env.dbuser, dbpasswd=env.dbpassword):
    if not pg.user_exists(dbuser):
        pg.create_user(dbuser, dbpasswd, groups=['gisgroup'])
    if not pg.database_exists(db):
        pg.create_database(db, dbuser, template='template_postgis')


@task
def restore_db(backup=None, format='custom', db=env.dbname, dbuser=env.dbuser, dbpasswd=env.dbpassword):
    if backup is not None:
        print 'Restoring %s' % backup
        if os.path.isfile(backup):
            put(backup, '/tmp/')
            destpath = '/tmp/%s' % os.path.basename(backup)
            sudo('''pg_restore --dbname="%(db)s"  --username=%(dbuser)s --format="%(format)s" -O --schema-only --no-owner
                    --no-acl %(destpath)s''' % locals())
    else:
        print 'Nothing to restore'


@task
def configure_webapp(db=env.dbname, dbuser=env.dbuser, dbpasswd='', email_passwd='', version='current'):
    env.version = version
    webapp.configure(db=db, dbuser=dbuser, dbpasswd=dbpasswd, email_passwd=email_passwd)


@task
def update_file(src, dest=None, relative=True):
    # webapp._sudo
    put(src, _dest(dest) if dest and relative else dest or _dest(src),
        use_sudo=True)


def get_file(src, dest=None, relative=True):
    get(_dest(src), dest or ('/tmp/%s' % src))


def _dest(src):
    project_home = '%(basedir)s/releases/current/%(project)s/' % env
    return os.path.join(project_home, src)


def rollback():
    pass


# ENVIRONMENTS
@task
def dev():
    """Local VMware test server.

    Specs: RAM - 512 MB
           HDD - 64bit 20 GB
    """
    env.hosts = [DEV_ENV_HOST]
    env.user = DEV_ENV_USER
    if DEV_ENV_USER:
        env.password = DEV_ENV_PASS
    env.log_level = 'debug'
    env.domain = DEV_ENV_DOMAIN


@task
def staging():
    env.hosts = [STAGING_ENV_HOST]
    env.user = STAGING_ENV_USER
    if STAGING_ENV_USER:
        env.password = STAGING_ENV_PASS
    env.log_level = 'info'
    env.is_staging = True
    env.domain = STAGING_ENV_DOMAIN


@task
def production():
    env.hosts = [PRODUCTION_ENV_HOST]
    env.user = PRODUCTION_ENV_USER
    if PRODUCTION_ENV_PASS:
        env.password = PRODUCTION_ENV_PASS
    env.log_level = 'info'
    env.is_staging = False
    env.domain = PRODUCTION_ENV_DOMAIN
