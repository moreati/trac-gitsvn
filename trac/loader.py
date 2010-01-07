# -*- coding: utf-8 -*-
#
# Copyright (C) 2005-2009 Edgewall Software
# Copyright (C) 2005-2006 Christopher Lenz <cmlenz@gmx.de>
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution. The terms
# are also available at http://trac.edgewall.org/wiki/TracLicense.
#
# This software consists of voluntary contributions made by many
# individuals. For the exact contribution history, see the revision
# history and logs, available at http://trac.edgewall.org/log/.
#
# Author: Christopher Lenz <cmlenz@gmx.de>

from glob import glob
import imp
import inspect
import os.path
import pkg_resources
from pkg_resources import working_set, DistributionNotFound, VersionConflict, \
                          UnknownExtra
import sys

from trac import __version__ as TRAC_VERSION
from trac.util import get_doc, get_module_path, get_pkginfo
from trac.util.text import exception_to_unicode, to_unicode

__all__ = ['load_components']

# Ideally, this wouldn't be hard-coded like this
required_components = (
    'trac.about.AboutModule',
    'trac.cache.CacheManager',
    'trac.env.Environment',
    'trac.env.EnvironmentSetup',
    'trac.mimeview.api.Mimeview',
    'trac.perm.DefaultPermissionGroupProvider',
    'trac.perm.PermissionSystem',
    'trac.web.chrome.Chrome',
    'trac.web.main.RequestDispatcher',
)

def _enable_plugin(env, module):
    """Enable the given plugin module by adding an entry to the configuration.
    """
    if module + '.*' not in env.config['components']:
        env.config['components'].set(module + '.*', 'enabled')

def load_eggs(entry_point_name):
    """Loader that loads any eggs on the search path and `sys.path`."""
    def _load_eggs(env, search_path, auto_enable=None):
        # Note that the following doesn't seem to support unicode search_path
        distributions, errors = working_set.find_plugins(
            pkg_resources.Environment(search_path)
        )
        for dist in distributions:
            if dist not in working_set:
                env.log.debug('Adding plugin %s from %s', dist, dist.location)
                working_set.add(dist)

        def _log_error(item, e):
            ue = exception_to_unicode(e)
            if isinstance(e, DistributionNotFound):
                env.log.debug('Skipping "%s": ("%s" not found)', item, ue)
            elif isinstance(e, VersionConflict):
                env.log.error('Skipping "%s": (version conflict "%s")',
                              item, ue)
            elif isinstance(e, UnknownExtra):
                env.log.error('Skipping "%s": (unknown extra "%s")', item, ue)
            elif isinstance(e, ImportError):
                env.log.error('Skipping "%s": (can\'t import "%s")', item, ue)
            else:
                env.log.error('Skipping "%s": %s)', item,
                              exception_to_unicode(e, traceback=True))

        for dist, e in errors.iteritems():
            _log_error(dist, e)

        for entry in sorted(working_set.iter_entry_points(entry_point_name),
                            key=lambda entry: entry.name):
            env.log.debug('Loading %s from %s', entry.name, entry.dist.location)
            try:
                entry.load(require=True)
            except Exception, e:
                _log_error(entry, e)
            else:
                if os.path.dirname(entry.dist.location) == auto_enable:
                    _enable_plugin(env, entry.module_name)
    return _load_eggs

def load_py_files():
    """Loader that look for Python source files in the plugins directories,
    which simply get imported, thereby registering them with the component
    manager if they define any components.
    """
    def _load_py_files(env, search_path, auto_enable=None):
        for path in search_path:
            plugin_files = glob(os.path.join(path, '*.py'))
            for plugin_file in plugin_files:
                try:
                    plugin_name = os.path.basename(plugin_file[:-3])
                    env.log.debug('Loading file plugin %s from %s' % \
                                  (plugin_name, plugin_file))
                    if plugin_name not in sys.modules:
                        module = imp.load_source(plugin_name, plugin_file)
                    if path == auto_enable:
                        _enable_plugin(env, plugin_name)
                except Exception, e:
                    env.log.error('Failed to load plugin from %s: %s',
                                  plugin_file,
                                  exception_to_unicode(e, traceback=True))

    return _load_py_files

def get_plugins_dir(env):
    """Return the path to the `plugins` directory of the environment."""
    plugins_dir = os.path.realpath(os.path.join(env.path, 'plugins'))
    return os.path.normcase(plugins_dir)

def load_components(env, extra_path=None, loaders=(load_eggs('trac.plugins'),
                                                   load_py_files())):
    """Load all plugin components found on the given search path."""
    plugins_dir = get_plugins_dir(env)
    search_path = [plugins_dir]
    if extra_path:
        search_path += list(extra_path)

    for loadfunc in loaders:
        loadfunc(env, search_path, auto_enable=plugins_dir)

def get_plugin_info(env):
    """Return package information about Trac core and installed plugins."""
    plugins_dir = get_plugins_dir(env)
    plugins = {}
    from trac.core import ComponentMeta
    for component in ComponentMeta._components:
        module = sys.modules[component.__module__]

        dist = _find_distribution(env, module)
        plugin_filename = None
        if os.path.realpath(os.path.dirname(dist.location)) == plugins_dir:
            plugin_filename = os.path.basename(dist.location)

        description = inspect.getdoc(component)
        if description:
            description = to_unicode(description).split('.', 1)[0] + '.'

        if dist.project_name not in plugins:
            readonly = True
            if plugin_filename and os.access(dist.location,
                                             os.F_OK + os.W_OK):
                readonly = False
            # retrieve plugin metadata
            info = get_pkginfo(dist)
            if not info:
                info = {}
                for k in ('author', 'author_email', 'home_page', 'url',
                          'license', 'trac'):
                    v = getattr(module, k, '')
                    if v:
                        if k == 'home_page' or k == 'url':
                            k = 'home_page'
                            v = v.replace('$', '').replace('URL: ', '') 
                        if k == 'author':
                            v = to_unicode(v)
                        info[k] = v
            else:
                # Info found; set all those fields to "None" that have the 
                # value "UNKNOWN" as this is the value for fields that
                # aren't specified in "setup.py"
                for k in info:
                    if info[k] == 'UNKNOWN':
                        info[k] = ''
                    elif k == 'author':
                        # Must be encoded as unicode as otherwise Genshi 
                        # may raise a "UnicodeDecodeError".
                        info[k] = to_unicode(info[k])

            # retrieve plugin version info
            version = dist.version
            if not version:
                version = (getattr(module, 'version', '') or
                           getattr(module, 'revision', ''))
                # special handling for "$Rev$" strings
                version = version.replace('$', '').replace('Rev: ', 'r') 
            plugins[dist.project_name] = {
                'name': dist.project_name, 'version': version,
                'path': dist.location, 'plugin_filename': plugin_filename,
                'readonly': readonly, 'info': info, 'modules': {},
            }
        modules = plugins[dist.project_name]['modules']
        if module.__name__ not in modules:
            summary, description = get_doc(module)
            plugins[dist.project_name]['modules'][module.__name__] = {
                'summary': summary, 'description': description,
                'components': {},
            }
        full_name = module.__name__ + '.' + component.__name__
        summary, description = get_doc(component)
        modules[module.__name__]['components'][component.__name__] = {
            'full_name': full_name,
            'summary': summary, 'description': description,
            'enabled': env.is_component_enabled(component),
            'required': full_name in required_components,
        }
    return plugins

def _find_distribution(env, module):
    path = get_module_path(module)
    if path == env.trac_path:
        return pkg_resources.Distribution(project_name='Trac',
                                          version=TRAC_VERSION,
                                          location=path)
    for dist in pkg_resources.find_distributions(path, only=True):
        return dist
    else:
        # This is a plain Python source file, not an egg
        return pkg_resources.Distribution(project_name=module.__name__,
                                          version='',
                                          location=module.__file__)

def match_plugins_to_frames(plugins, frames):
    """Add a `frame_idx` element to plugin information as returned by
    `get_plugin_info()`, containing the index of the highest frame in the
    list that was located in the plugin.
    """
    egg_frames = [(i, f) for i, f in enumerate(frames)
                  if f['filename'].startswith('build/')]
    
    def find_egg_frame_index(plugin):
        for dist in pkg_resources.find_distributions(plugin['path'],
                                                     only=True):
            sources = dist.get_metadata('SOURCES.txt')
            for src in sources.splitlines():
                if src.endswith('.py'):
                    nsrc = os.path.normpath(src)
                    for i, f in egg_frames:
                        if f['filename'].endswith(nsrc):
                            plugin['frame_idx'] = i
                            return
    
    for plugin in plugins.itervalues():
        base, ext = os.path.splitext(plugin['path'])
        if ext == '.egg' and egg_frames:
            find_egg_frame_index(plugin)
        else:
            for i, f in enumerate(frames):
                if f['filename'].startswith(base):
                    plugin['frame_idx'] = i
                    break
