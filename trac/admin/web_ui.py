# -*- coding: utf-8 -*-
#
# Copyright (C) 2005-2006 Edgewall Software
# Copyright (C) 2005 Jonas Borgström <jonas@edgewall.com>
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution. The terms
# are also available at http://trac.edgewall.com/license.html.
#
# This software consists of voluntary contributions made by many
# individuals. For the exact contribution history, see the revision
# history and logs, available at http://projects.edgewall.com/trac/.
#
# Author: Jonas Borgström <jonas@edgewall.com>

import email
import inspect
import os
import re
import shutil
import sys

import pkg_resources
from genshi.builder import tag

from trac import __version__ as TRAC_VERSION
from trac.admin.api import IAdminPanelProvider
from trac.core import *
from trac.perm import PermissionSystem
from trac.util.compat import partial, sorted
from trac.web import HTTPNotFound, IRequestHandler
from trac.web.chrome import add_script, add_stylesheet, Chrome, \
                            INavigationContributor


class AdminModule(Component):
    """Web administration interface."""

    implements(INavigationContributor, IRequestHandler)

    panel_providers = ExtensionPoint(IAdminPanelProvider)

    # INavigationContributor methods

    def get_active_navigation_item(self, req):
        return 'admin'

    def get_navigation_items(self, req):
        # The 'Admin' navigation item is only visible if at least one
        # admin panel is available
        panels, providers = self._get_panels(req)
        if panels:
            yield 'mainnav', 'admin', tag.a('Admin', href=req.href.admin(),
                                            title='Administration')

    # IRequestHandler methods

    def match_request(self, req):
        match = re.match('/admin(?:/([^/]+))?(?:/([^/]+))?(?:/(.*)$)?',
                         req.path_info)
        if match:
            req.args['cat_id'] = match.group(1)
            req.args['panel_id'] = match.group(2)
            req.args['path_info'] = match.group(3)
            return True

    def process_request(self, req):
        panels, providers = self._get_panels(req)
        if not panels:
            raise HTTPNotFound('No administration panels available')

        cat_id = req.args.get('cat_id') or panels[0][0]
        panel_id = req.args.get('panel_id')
        path_info = req.args.get('path_info')
        if not panel_id:
            panel_id = filter(lambda panel: panel[0] == cat_id, panels)[0][2]

        provider = providers.get((cat_id, panel_id), None)
        if not provider:
            raise HTTPNotFound('Unknown administration panel')

        template, data = provider.render_admin_panel(req, cat_id, panel_id,
                                                     path_info)
        data.update({
            'active_cat': cat_id, 'active_panel': panel_id,
            'panel_href': partial(req.href, 'admin', cat_id, panel_id),
            'panels': [{
                'category': {'id': panel[0], 'label': panel[1]},
                'panel': {'id': panel[2], 'label': panel[3]}
            } for panel in sorted(panels)]
        })

        add_stylesheet(req, 'common/css/admin.css')
        return template, data, None

    # Internal methods

    def _get_panels(self, req):
        """Return a list of available admin panels."""
        panels = []
        providers = {}
        for provider in self.panel_providers:
            p = list(provider.get_admin_panels(req))
            for panel in p:
                providers[(panel[0], panel[2])] = provider
            panels += p
        return panels, providers


class BasicsAdminPanel(Component):

    implements(IAdminPanelProvider)

    # IAdminPanelProvider methods

    def get_admin_panels(self, req):
        if 'TRAC_ADMIN' in req.perm:
            yield ('general', 'General', 'basics', 'Basic Settings')

    def render_admin_panel(self, req, cat, page, path_info):
        req.perm.require('TRAC_ADMIN')

        if req.method == 'POST':
            for option in ('name', 'url', 'descr'):
                self.config.set('project', option, req.args.get(option))
            self.config.save()
            req.redirect(req.href.admin(cat, page))

        data = {
            'name': self.env.project_name,
            'description': self.env.project_description,
            'url': self.env.project_url
        }
        return 'admin_basics.html', {'project': data}


class LoggingAdminPanel(Component):

    implements(IAdminPanelProvider)

    # IAdminPanelProvider methods

    def get_admin_panels(self, req):
        if 'TRAC_ADMIN' in req.perm:
            yield ('general', 'General', 'logging', 'Logging')

    def render_admin_panel(self, req, cat, page, path_info):
        log_type = self.env.log_type
        log_level = self.env.log_level
        log_file = self.env.log_file
        log_dir = os.path.join(self.env.path, 'log')

        log_types = [
            dict(name='', label=''),
            dict(name='stderr', label='Console', selected=log_type == 'stderr'),
            dict(name='file', label='File', selected=log_type == 'file'),
            dict(name='syslog', label='Syslog', disabled=os.name != 'posix',
                 selected=log_type in ('unix', 'syslog')),
            dict(name='eventlog', label='Windows event log',
                 disabled=os.name != 'nt',
                 selected=log_type in ('winlog', 'eventlog', 'nteventlog')),
        ]

        log_levels = ['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG']

        if req.method == 'POST':
            changed = False

            new_type = req.args.get('log_type')
            if new_type and new_type not in ('stderr', 'file', 'syslog',
                                             'eventlog'):
                raise TracError('Unknown log type %s' % new_type,
                                'Invalid log type')
            if new_type != log_type:
                self.config.set('logging', 'log_type', new_type or 'none')
                changed = True
                log_type = new_type

            if log_type:
                new_level = req.args.get('log_level')
                if new_level and new_level not in log_levels:
                    raise TracError('Unknown log level %s' % new_level,
                                    'Invalid log level')
                if new_level and new_level != log_level:
                    self.config.set('logging', 'log_level', new_level)
                    changed = True
                    log_evel = new_level
            else:
                self.config.remove('logging', 'log_level')
                changed = True

            if log_type == 'file':
                new_file = req.args.get('log_file', 'trac.log')
                if new_file != log_file:
                    self.config.set('logging', 'log_file', new_file or '')
                    changed = True
                    log_file = new_file
                if log_type == 'file' and not log_file:
                    raise TracError('You must specify a log file',
                                    'Missing field')
            else:
                self.config.remove('logging', 'log_file')
                changed = True

            if changed:
                self.config.save()
            req.redirect(req.href.admin(cat, page))

        data = {
            'type': log_type, 'types': log_types,
            'level': log_level, 'levels': log_levels,
            'file': log_file, 'dir': log_dir
        }
        return 'admin_logging.html', {'log': data}


class PermissionAdminPanel(Component):

    implements(IAdminPanelProvider)

    # IAdminPanelProvider
    def get_admin_panels(self, req):
        if 'TRAC_ADMIN' in req.perm:
            yield ('general', 'General', 'perm', 'Permissions')

    def render_admin_panel(self, req, cat, page, path_info):
        perm = PermissionSystem(self.env)
        perms = perm.get_all_permissions()
        subject = req.args.get('subject')
        action = req.args.get('action')
        group = req.args.get('group')

        if req.method == 'POST':
            # Grant permission to subject
            if req.args.get('add') and subject and action:
                if action not in perm.get_actions():
                    raise TracError('Unknown action')
                perm.grant_permission(subject, action)
                req.redirect(req.href.admin(cat, page))

            # Add subject to group
            elif req.args.get('add') and subject and group:
                perm.grant_permission(subject, group)
                req.redirect(req.href.admin(cat, page))

            # Remove permissions action
            elif req.args.get('remove') and req.args.get('sel'):
                sel = req.args.get('sel')
                sel = isinstance(sel, list) and sel or [sel]
                for key in sel:
                    subject, action = key.split(':', 1)
                    if (subject, action) in perms:
                        perm.revoke_permission(subject, action)
                req.redirect(req.href.admin(cat, page))

        perms.sort()
        perms = [{'subject': p[0], 'action': p[1], 'key': '%s:%s' % p}
                 for p in perms]

        return 'admin_perms.html', {
            'actions': perm.get_actions(),
            'perms': perms
        }


class PluginAdminPanel(Component):

    implements(IAdminPanelProvider)

    # Ideally, this wouldn't be hard-coded like this
    required_components = ('AboutModule', 'DefaultPermissionGroupProvider',
        'Environment', 'EnvironmentSetup', 'PermissionSystem', 'RequestDispatcher',
        'Mimeview', 'Chrome')

    def __init__(self):
        self.trac_path = self._find_base_path(sys.modules['trac.core'].__file__,
                                              'trac.core')

    # IAdminPanelProvider methods

    def get_admin_panels(self, req):
        if 'TRAC_ADMIN' in req.perm:
            yield ('general', 'General', 'plugin', 'Plugins')

    def render_admin_panel(self, req, cat, page, _):
        req.perm.require('TRAC_ADMIN')

        if req.method == 'POST':
            if 'install' in req.args:
                self._do_install(req)
            elif 'uninstall' in req.args:
                self._do_uninstall(req)
            else:
                self._do_update(req)
            anchor = ''
            if req.args.has_key('plugin'):
                anchor = '#no' + req.args.get('plugin')
            req.redirect(req.href.admin(cat, page) + anchor)

        return self._render_view(req)

    # Internal methods

    def _do_install(self, req):
        """Install a plugin."""
        if not req.args.has_key('plugin_file'):
            raise TracError, 'No file uploaded'
        upload = req.args['plugin_file']
        if not upload.filename:
            raise TracError, 'No file uploaded'
        plugin_filename = upload.filename.replace('\\', '/').replace(':', '/')
        plugin_filename = os.path.basename(plugin_filename)
        if not plugin_filename:
            raise TracError, 'No file uploaded'
        if not plugin_filename.endswith('.egg') and \
                not plugin_filename.endswith('.py'):
            raise TracError, 'Uploaded file is not a Python source file or egg'

        target_path = os.path.join(self.env.path, 'plugins', plugin_filename)
        if os.path.isfile(target_path):
            raise TracError, 'Plugin %s already installed' % plugin_filename

        self.log.info('Installing plugin %s', plugin_filename)
        flags = os.O_CREAT + os.O_WRONLY + os.O_EXCL
        try:
            flags += os.O_BINARY
        except AttributeError:
            # OS_BINARY not available on every platform
            pass
        target_file = os.fdopen(os.open(target_path, flags), 'w')
        try:
            shutil.copyfileobj(upload.file, target_file)
            self.log.info('Plugin %s installed to %s', plugin_filename,
                          target_path)
        finally:
            target_file.close()

        # TODO: Validate that the uploaded file is actually a valid Trac plugin

    def _do_uninstall(self, req):
        """Uninstall a plugin."""
        plugin_filename = req.args.get('plugin_filename')
        if not plugin_filename:
            return
        plugin_path = os.path.join(self.env.path, 'plugins', plugin_filename)
        if not os.path.isfile(plugin_path):
            return
        self.log.info('Uninstalling plugin %s', plugin_filename)
        os.remove(plugin_path)

    def _do_update(self, req):
        """Update component enablement."""
        components = req.args.getlist('component')
        enabled = req.args.getlist('enable')
        changes = False

        # FIXME: this needs to be more intelligent and minimize multiple
        # component names to prefix rules

        for component in components:
            is_enabled = self.env.is_component_enabled(component)
            if is_enabled != (component in enabled):
                self.config.set('components', component,
                                is_enabled and 'disabled' or 'enabled')
                self.log.info('%sabling component %s',
                              is_enabled and 'Dis' or 'En', component)
                changes = True

        if changes:
            self.config.save()

    def _render_view(self, req):
        plugins = {}
        plugins_dir = os.path.realpath(os.path.join(self.env.path, 'plugins'))

        from trac.core import ComponentMeta
        for component in ComponentMeta._components:
            module = sys.modules[component.__module__]

            dist = self._find_distribution(module)
            plugin_filename = None
            if os.path.realpath(os.path.dirname(dist.location)) == plugins_dir:
                plugin_filename = os.path.basename(dist.location)

            description = inspect.getdoc(component)
            if description:
                description = description.split('.', 1)[0] + '.'

            if dist.project_name not in plugins:
                readonly = True
                if plugin_filename and os.access(dist.location,
                                                 os.F_OK + os.W_OK):
                    readonly = False
                plugins[dist.project_name] = {
                    'name': dist.project_name, 'version': dist.version,
                    'path': dist.location, 'description': description,
                    'plugin_filename': plugin_filename, 'readonly': readonly,
                    'info': self._get_pkginfo(dist), 'components': []
                }
            plugins[dist.project_name]['components'].append({
                'name': component.__name__, 'module': module.__name__,
                'description': description,
                'enabled': self.env.is_component_enabled(component),
                'required': component.__name__ in self.required_components,
            })

        def component_order(a, b):
            c = cmp(len(a['module'].split('.')), len(b['module'].split('.')))
            if c == 0:
                c = cmp(a['module'].lower(), b['module'].lower())
                if c == 0:
                    c = cmp(a['name'].lower(), b['name'].lower())
            return c
        for category in plugins:
            plugins[category]['components'].sort(component_order)

        plugin_list = [plugins['Trac']]
        addons = [key for key in plugins.keys() if key != 'Trac']
        addons.sort()
        plugin_list += [plugins[category] for category in addons]

        add_script(req, 'common/js/folding.js')
        data = {
            'plugins': plugin_list,
            'readonly': not os.access(plugins_dir, os.F_OK + os.W_OK)
        }
        return 'admin_plugins.html', data

    def _find_distribution(self, module):
        # Determine the plugin that this component belongs to
        path = module.__file__
        if path.endswith('.pyc') or path.endswith('.pyo'):
            path = path[:-1]
        if os.path.basename(path) == '__init__.py':
            path = os.path.dirname(path)
        path = self._find_base_path(path, module.__name__)
        if path == self.trac_path:
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

    def _find_base_path(self, path, module_name):
        base_path = os.path.splitext(path)[0]
        while base_path.replace(os.sep, '.').endswith(module_name):
            base_path = os.path.dirname(base_path)
            module_name = '.'.join(module_name.split('.')[:-1])
            if not module_name:
                break
        return base_path

    def _get_pkginfo(self, dist):
        attrs = ('author', 'author-email', 'license', 'home-page', 'summary',
                 'description')
        info = {}
        try:
            pkginfo = email.message_from_string(dist.get_metadata('PKG-INFO'))
            for attr in [key for key in attrs if key in pkginfo]:
                info[attr.lower().replace('-', '_')] = pkginfo[attr]
        except email.Errors.MessageError, e:
            self.log.warning('Failed to parse PKG-INFO file for %s: %s', dist,
                             e, exc_info=True)
        return info
