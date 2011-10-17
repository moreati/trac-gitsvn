# -*- coding: utf-8 -*-
#
# Copyright (C) 2003-2009 Edgewall Software
# Copyright (C) 2003-2004 Jonas Borgström <jonas@edgewall.com>
# Copyright (C) 2006 Christian Boos <cboos@neuf.fr>
# Copyright (C) 2006 Matthew Good <trac@matt-good.net>
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
# Author: Jonas Borgström <jonas@edgewall.com>

from __future__ import with_statement

import csv
import re
from StringIO import StringIO

from genshi.builder import tag

from trac.config import IntOption
from trac.core import *
from trac.db import get_column_names
from trac.perm import IPermissionRequestor
from trac.resource import Resource, ResourceNotFound
from trac.ticket.api import TicketSystem
from trac.util import as_int, content_disposition
from trac.util.datefmt import format_datetime, format_time, from_utimestamp
from trac.util.presentation import Paginator
from trac.util.text import exception_to_unicode, to_unicode, quote_query_string
from trac.util.translation import _, tag_
from trac.web.api import IRequestHandler, RequestDone
from trac.web.chrome import (INavigationContributor, Chrome, 
                             add_ctxtnav, add_link, add_notice, add_script,
                             add_stylesheet, add_warning, auth_link,
                             web_context)
from trac.wiki import IWikiSyntaxProvider, WikiParser


def cell_value(v):
    """Normalize a cell value for display.
    >>> (cell_value(None), cell_value(0), cell_value(1), cell_value('v'))
    ('', '0', u'1', u'v')
    """
    return '0' if v is 0 else unicode(v) if v else ''


class ReportModule(Component):

    implements(INavigationContributor, IPermissionRequestor, IRequestHandler,
               IWikiSyntaxProvider)

    items_per_page = IntOption('report', 'items_per_page', 100,
        """Number of tickets displayed per page in ticket reports,
        by default (''since 0.11'')""")

    items_per_page_rss = IntOption('report', 'items_per_page_rss', 0,
        """Number of tickets displayed in the rss feeds for reports
        (''since 0.11'')""")
    
    # INavigationContributor methods

    def get_active_navigation_item(self, req):
        return 'tickets'

    def get_navigation_items(self, req):
        if 'REPORT_VIEW' in req.perm:
            yield ('mainnav', 'tickets', tag.a(_('View Tickets'),
                                               href=req.href.report()))

    # IPermissionRequestor methods  

    def get_permission_actions(self):  
        actions = ['REPORT_CREATE', 'REPORT_DELETE', 'REPORT_MODIFY',  
                   'REPORT_SQL_VIEW', 'REPORT_VIEW']  
        return actions + [('REPORT_ADMIN', actions)]  

    # IRequestHandler methods

    def match_request(self, req):
        match = re.match(r'/report(?:/(?:([0-9]+)|-1))?$', req.path_info)
        if match:
            if match.group(1):
                req.args['id'] = match.group(1)
            return True

    def process_request(self, req):
        req.perm.require('REPORT_VIEW')

        # did the user ask for any special report?
        id = int(req.args.get('id', -1))
        action = req.args.get('action', 'view')

        data = {}
        if req.method == 'POST':
            if action == 'new':
                self._do_create(req)
            elif action == 'delete':
                self._do_delete(req, id)
            elif action == 'edit':
                self._do_save(req, id)
        elif action in ('copy', 'edit', 'new'):
            template = 'report_edit.html'
            data = self._render_editor(req, id, action=='copy')
            Chrome(self.env).add_wiki_toolbars(req)
        elif action == 'delete':
            template = 'report_delete.html'
            data = self._render_confirm_delete(req, id)
        elif id == -1:
            template, data, content_type = self._render_list(req)
            if content_type: # i.e. alternate format
                return template, data, content_type
            if action == 'clear':
                if 'query_href' in req.session:
                    del req.session['query_href']
                if 'query_tickets' in req.session:
                    del req.session['query_tickets']
        else:
            template, data, content_type = self._render_view(req, id)
            if content_type: # i.e. alternate format
                return template, data, content_type

        if id != -1 or action == 'new':
            add_ctxtnav(req, _('Available Reports'), href=req.href.report())
            add_link(req, 'up', req.href.report(), _('Available Reports'))
        else:
            add_ctxtnav(req, _('Available Reports'))

        # Kludge: only show link to custom query if the query module is actually
        # enabled
        from trac.ticket.query import QueryModule
        if 'TICKET_VIEW' in req.perm and \
                self.env.is_component_enabled(QueryModule):
            add_ctxtnav(req, _('Custom Query'), href=req.href.query())
            data['query_href'] = req.href.query()
            data['saved_query_href'] = req.session.get('query_href')
        else:
            data['query_href'] = None

        add_stylesheet(req, 'common/css/report.css')
        return template, data, None

    # Internal methods

    def _do_create(self, req):
        req.perm.require('REPORT_CREATE')

        if 'cancel' in req.args:
            req.redirect(req.href.report())

        title = req.args.get('title', '')
        query = req.args.get('query', '')
        description = req.args.get('description', '')
        with self.env.db_transaction as db:
            cursor = db.cursor()
            cursor.execute("""
                INSERT INTO report (title,query,description) VALUES (%s,%s,%s)
                """, (title, query, description))
            report_id = db.get_last_id(cursor, 'report')
        add_notice(req, _("The report has been created."))
        req.redirect(req.href.report(report_id))

    def _do_delete(self, req, id):
        req.perm.require('REPORT_DELETE')

        if 'cancel' in req.args:
            req.redirect(req.href.report(id))

        self.env.db_transaction("DELETE FROM report WHERE id=%s", (id,))
        add_notice(req, _("The report {%(id)d} has been deleted.", id=id))
        req.redirect(req.href.report())

    def _do_save(self, req, id):
        """Save report changes to the database"""
        req.perm.require('REPORT_MODIFY')

        if 'cancel' not in req.args:
            title = req.args.get('title', '')
            query = req.args.get('query', '')
            description = req.args.get('description', '')
            self.env.db_transaction("""
                UPDATE report SET title=%s, query=%s, description=%s
                WHERE id=%s
                """, (title, query, description, id))
            add_notice(req, _("Your changes have been saved."))
        req.redirect(req.href.report(id))

    def _render_confirm_delete(self, req, id):
        req.perm.require('REPORT_DELETE')

        for title, in self.env.db_query("""
                SELECT title FROM report WHERE id=%s
                """, (id,)):
            return {'title': _("Delete Report {%(num)s} %(title)s", num=id,
                               title=title),
                    'action': 'delete',
                    'report': {'id': id, 'title': title}}
        else:
            raise TracError(_("Report {%(num)s} does not exist.", num=id),
                            _("Invalid Report Number"))

    def _render_editor(self, req, id, copy):
        if id != -1:
            req.perm.require('REPORT_MODIFY')
            for title, description, query in self.env.db_query(
                    "SELECT title, description, query FROM report WHERE id=%s",
                    (id,)):
                break
            else:
                raise TracError(_("Report {%(num)s} does not exist.", num=id),
                                _("Invalid Report Number"))
        else:
            req.perm.require('REPORT_CREATE')
            title = description = query = ''

        # an explicitly given 'query' parameter will override the saved query
        query = req.args.get('query', query)

        if copy:
            title += ' (copy)'

        if copy or id == -1:
            data = {'title': _('Create New Report'),
                    'action': 'new',
                    'error': None}
        else:
            data = {'title': _('Edit Report {%(num)d} %(title)s', num=id,
                               title=title),
                    'action': 'edit',
                    'error': req.args.get('error')}

        data['report'] = {'id': id, 'title': title,
                          'sql': query, 'description': description}
        return data

    def _render_list(self, req):
        """Render the list of available reports."""
        sort = req.args.get('sort', 'report')
        asc = bool(int(req.args.get('asc', 1)))
        format = req.args.get('format')
        
        rows = self.env.db_query("""
                SELECT id, title, description FROM report ORDER BY %s %s
                """ % ('title' if sort == 'title' else 'id',
                       '' if asc else 'DESC'))
            
        if format == 'rss':
            data = {'rows': rows}
            return 'report_list.rss', data, 'application/rss+xml'
        elif format == 'csv':
            self._send_csv(req, ['report', 'title', 'description'],
                           rows, mimetype='text/csv',
                           filename='reports.csv')
        elif format == 'tab':
            self._send_csv(req, ['report', 'title', 'description'],
                           rows, '\t', mimetype='text/tab-separated-values',
                           filename='reports.tsv')

        def report_href(**kwargs):
            return req.href.report(sort=req.args.get('sort'),
                                   asc='1' if asc else '0', **kwargs)

        add_link(req, 'alternate',
                 auth_link(req, report_href(format='rss')),
                 _('RSS Feed'), 'application/rss+xml', 'rss')
        add_link(req, 'alternate', report_href(format='csv'),
                 _('Comma-delimited Text'), 'text/plain')
        add_link(req, 'alternate', report_href(format='tab'),
                 _('Tab-delimited Text'), 'text/plain')
        
        reports = [(id, title, description, 
                    'REPORT_MODIFY' in req.perm('report', id),
                    'REPORT_DELETE' in req.perm('report', id))
                   for id, title, description in rows]
        data = {'reports': reports, 'sort': sort, 'asc': asc}

        return 'report_list.html', data, None

    _html_cols = set(['__class__', '__style__', '__color__', '__fgcolor__',
                      '__bgcolor__', '__grouplink__'])

    def _render_view(self, req, id):
        """Retrieve the report results and pre-process them for rendering."""
        for title, sql, description in self.env.db_query("""
                SELECT title, query, description from report WHERE id=%s
                """, (id,)):
            break
        else:
            raise ResourceNotFound(_("Report {%(num)s} does not exist.",
                                     num=id), _("Invalid Report Number"))
        try:
            args = self.get_var_args(req)
        except ValueError, e:
            raise TracError(_("Report failed: %(error)s", error=e))

        # If this is a saved custom query, redirect to the query module
        #
        # A saved query is either an URL query (?... or query:?...),
        # or a query language expression (query:...).
        #
        # It may eventually contain newlines, for increased clarity.
        #
        query = ''.join([line.strip() for line in sql.splitlines()])
        if query and (query[0] == '?' or query.startswith('query:?')):
            query = query if query[0] == '?' else query[6:]
            report_id = 'report=%s' % id
            if 'report=' in query:
                if not report_id in query:
                    err = _('When specified, the report number should be '
                            '"%(num)s".', num=id)
                    req.redirect(req.href.report(id, action='edit', error=err))
            else:
                if query[-1] != '?':
                    query += '&'
                query += report_id
            req.redirect(req.href.query() + quote_query_string(query))
        elif query.startswith('query:'):
            try:
                from trac.ticket.query import Query, QuerySyntaxError
                query = Query.from_string(self.env, query[6:], report=id)
                req.redirect(query.get_href(req))
            except QuerySyntaxError, e:
                req.redirect(req.href.report(id, action='edit',
                                             error=to_unicode(e)))

        format = req.args.get('format')
        if format == 'sql':
            self._send_sql(req, id, title, description, sql)

        title = '{%i} %s' % (id, title)

        report_resource = Resource('report', id)
        req.perm.require('REPORT_VIEW', report_resource)
        context = web_context(req, report_resource)

        page = int(req.args.get('page', '1'))
        default_max = {'rss': self.items_per_page_rss,
                       'csv': 0, 'tab': 0}.get(format, self.items_per_page)
        max = req.args.get('max')
        limit = as_int(max, default_max, min=0) # explict max takes precedence
        offset = (page - 1) * limit

        sort_col = req.args.get('sort', '')
        asc = req.args.get('asc', 1)
        asc = bool(int(asc)) # string '0' or '1' to int/boolean

        def report_href(**kwargs):
            """Generate links to this report preserving user variables, 
            and sorting and paging variables.
            """
            params = args.copy()
            if sort_col:
                params['sort'] = sort_col
            params['page'] = page
            if max:
                params['max'] = max
            params.update(kwargs)
            params['asc'] = '1' if params.get('asc', asc) else '0'            
            return req.href.report(id, params)

        data = {'action': 'view',
                'report': {'id': id, 'resource': report_resource},
                'context': context,
                'title': title, 'description': description,
                'max': limit, 'args': args, 'show_args_form': False,
                'message': None, 'paginator': None,
                'report_href': report_href, 
                }

        with self.env.db_query as db:
            try:
                cols, results, num_items, missing_args = \
                    self.execute_paginated_report(req, db, id, sql, args, limit,
                                                  offset)
                results = [list(row) for row in results]
                numrows = len(results)

            except Exception, e:
                data['message'] = tag_('Report execution failed: %(error)s',
                        error=tag.pre(exception_to_unicode(e, traceback=True)))
                return 'report_view.html', data, None

        paginator = None
        if limit > 0:
            paginator = Paginator(results, page - 1, limit, num_items)
            data['paginator'] = paginator
            if paginator.has_next_page:
                add_link(req, 'next', report_href(page=page + 1),
                         _('Next Page'))
            if paginator.has_previous_page:
                add_link(req, 'prev', report_href(page=page - 1),
                         _('Previous Page'))

            pagedata = []
            shown_pages = paginator.get_shown_pages(21)
            for p in shown_pages:
                pagedata.append([report_href(page=p), None, str(p),
                                 _('Page %(num)d', num=p)])
            fields = ['href', 'class', 'string', 'title']
            paginator.shown_pages = [dict(zip(fields, p)) for p in pagedata]
            paginator.current_page = {'href': None, 'class': 'current',
                                    'string': str(paginator.page + 1),
                                    'title': None}
            numrows = paginator.num_items

        # Place retrieved columns in groups, according to naming conventions
        #  * _col_ means fullrow, i.e. a group with one header
        #  * col_ means finish the current group and start a new one

        field_labels = TicketSystem(self.env).get_ticket_field_labels()

        header_groups = [[]]
        for idx, col in enumerate(cols):
            if col in field_labels:
                title = field_labels[col]
            else:
                title = col.strip('_').capitalize()
            header = {
                'col': col,
                'title': title,
                'hidden': False,
                'asc': None,
            }

            if col == sort_col:
                header['asc'] = asc
                if not paginator:
                    # this dict will have enum values for sorting
                    # and will be used in sortkey(), if non-empty:
                    sort_values = {}
                    if sort_col in ('status', 'resolution', 'priority', 
                                    'severity'):
                        # must fetch sort values for that columns
                        # instead of comparing them as strings
                        with self.env.db_query as db:
                            for name, value in db(
                                    "SELECT name, %s FROM enum WHERE type=%%s"
                                    % db.cast('value', 'int'),
                                    (sort_col,)):
                                sort_values[name] = value

                    def sortkey(row):
                        val = row[idx]
                        # check if we have sort_values, then use them as keys.
                        if sort_values:
                            return sort_values.get(val)
                        # otherwise, continue with string comparison:
                        if isinstance(val, basestring):
                            val = val.lower()
                        return val
                    results = sorted(results, key=sortkey, reverse=(not asc))

            header_group = header_groups[-1]

            if col.startswith('__') and col.endswith('__'): # __col__
                header['hidden'] = True
            elif col[0] == '_' and col[-1] == '_':          # _col_
                header_group = []
                header_groups.append(header_group)
                header_groups.append([])
            elif col[0] == '_':                             # _col
                header['hidden'] = True
            elif col[-1] == '_':                            # col_
                header_groups.append([])
            header_group.append(header)

        # Structure the rows and cells:
        #  - group rows according to __group__ value, if defined
        #  - group cells the same way headers are grouped
        chrome = Chrome(self.env)
        row_groups = []
        authorized_results = []
        prev_group_value = None
        for row_idx, result in enumerate(results):
            col_idx = 0
            cell_groups = []
            row = {'cell_groups': cell_groups}
            realm = 'ticket'
            email_cells = []
            for header_group in header_groups:
                cell_group = []
                for header in header_group:
                    value = cell_value(result[col_idx])
                    cell = {'value': value, 'header': header, 'index': col_idx}
                    col = header['col']
                    col_idx += 1
                    # Detect and create new group
                    if col == '__group__' and value != prev_group_value:
                        prev_group_value = value
                        # Brute force handling of email in group by header
                        row_groups.append(
                            (value and chrome.format_author(req, value), []))
                    # Other row properties
                    row['__idx__'] = row_idx
                    if col in self._html_cols:
                        row[col] = value
                    if col in ('report', 'ticket', 'id', '_id'):
                        row['id'] = value
                    # Special casing based on column name
                    col = col.strip('_')
                    if col in ('reporter', 'cc', 'owner'):
                        email_cells.append(cell)
                    elif col == 'realm':
                        realm = value
                    cell_group.append(cell)
                cell_groups.append(cell_group)
            resource = Resource(realm, row.get('id'))
            # FIXME: for now, we still need to hardcode the realm in the action
            if resource.realm.upper()+'_VIEW' not in req.perm(resource):
                continue
            authorized_results.append(result)
            if email_cells:
                for cell in email_cells:
                    emails = chrome.format_emails(context.child(resource),
                                                  cell['value'])
                    result[cell['index']] = cell['value'] = emails
            row['resource'] = resource
            if row_groups:
                row_group = row_groups[-1][1]
            else:
                row_group = []
                row_groups = [(None, row_group)]
            row_group.append(row)

        data.update({'header_groups': header_groups,
                     'row_groups': row_groups,
                     'numrows': numrows,
                     'sorting_enabled': len(row_groups) == 1})

        if format == 'rss':
            data['email_map'] = chrome.get_email_map()
            data['context'] = web_context(req, report_resource,
                                                   absurls=True)
            return 'report.rss', data, 'application/rss+xml'
        elif format == 'csv':
            filename = 'report_%s.csv' % id if id else 'report.csv'
            self._send_csv(req, cols, authorized_results, mimetype='text/csv',
                           filename=filename)
        elif format == 'tab':
            filename = 'report_%s.tsv' % id if id else 'report.tsv'
            self._send_csv(req, cols, authorized_results, '\t',
                           mimetype='text/tab-separated-values',
                           filename=filename)
        else:
            p = page if max is not None else None
            add_link(req, 'alternate',
                     auth_link(req, report_href(format='rss', page=None)),
                     _('RSS Feed'), 'application/rss+xml', 'rss')
            add_link(req, 'alternate', report_href(format='csv', page=p),
                     _('Comma-delimited Text'), 'text/plain')
            add_link(req, 'alternate', report_href(format='tab', page=p),
                     _('Tab-delimited Text'), 'text/plain')
            if 'REPORT_SQL_VIEW' in req.perm:
                add_link(req, 'alternate', 
                         req.href.report(id=id, format='sql'),
                         _('SQL Query'), 'text/plain')

            # reuse the session vars of the query module so that
            # the query navigation links on the ticket can be used to 
            # navigate report results as well
            try:
                req.session['query_tickets'] = \
                    ' '.join([str(int(row['id']))
                              for rg in row_groups for row in rg[1]])
                req.session['query_href'] = \
                    req.session['query_href'] = report_href()
                # Kludge: we have to clear the other query session
                # variables, but only if the above succeeded 
                for var in ('query_constraints', 'query_time'):
                    if var in req.session:
                        del req.session[var]
            except (ValueError, KeyError):
                pass
            if set(data['args']) - set(['USER']):
                data['show_args_form'] = True
                add_script(req, 'common/js/folding.js')
            if missing_args:
                add_warning(req, _(
                    'The following arguments are missing: %(args)s',
                    args=", ".join(missing_args)))
            return 'report_view.html', data, None

    def execute_report(self, req, db, id, sql, args):
        """Execute given sql report (0.10 backward compatibility method)
        
        :see: ``execute_paginated_report``
        """
        return self.execute_paginated_report(req, db, id, sql, args)[:2]

    def execute_paginated_report(self, req, db, id, sql, args, 
                                 limit=0, offset=0):
        sql, args, missing_args = self.sql_sub_vars(sql, args, db)
        if not sql:
            raise TracError(_("Report {%(num)s} has no SQL query.", num=id))

        cursor = db.cursor()

        num_items = 0
        if id != -1 and limit > 0:
            cursor.execute("SELECT COUNT(*) FROM (%s) AS tab" % sql, args)
            num_items = cursor.fetchone()[0]
    
            # get the column names
            cursor.execute("SELECT * FROM (%s) AS tab LIMIT 1" % sql, args)
            cols = get_column_names(cursor)

            sort_col = req.args.get('sort', '')
            order_cols = []
            if sort_col:
                if '__group__' in cols:
                    order_cols.append('__group__')
                if sort_col in cols:
                    order_cols.append(sort_col)
                else:
                    raise TracError(_('Query parameter "sort=%(sort_col)s" '
                                      ' is invalid', sort_col=sort_col))

            # get the (partial) report results
            order_by = ''
            if order_cols:
                asc = req.args.get('asc', '1')
                order_by = " ORDER BY %s %s" % (
                       ', '.join(db.quote(col) for col in order_cols),
                        'ASC' if asc == '1' else 'DESC')
            sql = "SELECT * FROM (%s) AS tab %s LIMIT %s OFFSET %s" % \
                    (sql, order_by, str(limit), str(offset))
            self.log.debug("Query SQL: " + sql)
        cursor.execute(sql, args)
        rows = cursor.fetchall() or []
        cols = get_column_names(cursor)
        return cols, rows, num_items, missing_args

    def get_var_args(self, req):
        # reuse somehow for #9574 (wiki vars)
        report_args = {}
        for arg in req.args.keys():
            if not arg.isupper():
                continue
            report_args[arg] = to_unicode(req.args.get(arg))

        # Set some default dynamic variables
        if 'USER' not in report_args:
            report_args['USER'] = req.authname

        return report_args

    def sql_sub_vars(self, sql, args, db=None):
        """Extract $XYZ-style variables from the `sql` query.

        :since 0.13: the `db` parameter is no longer needed and will be removed
        in version 0.14
        """
        names = set()
        values = []
        missing_args = []
        def add_value(aname):
            names.add(aname)
            try:
                arg = args[aname]
            except KeyError:
                arg = args[str(aname)] = ''
                missing_args.append(aname)
            values.append(arg)

        var_re = re.compile("[$]([A-Z_][A-Z0-9_]*)")

        # simple parameter substitution outside literal
        def repl(match):
            add_value(match.group(1))
            return '%s'

        # inside a literal break it and concatenate with the parameter
        def repl_literal(expr):
            parts = var_re.split(expr[1:-1])
            if len(parts) == 1:
                return expr
            params = parts[1::2]
            parts = ["'%s'" % p for p in parts]
            parts[1::2] = ['%s'] * len(params)
            for param in params:
                add_value(param)
            return self.env.get_read_db().concat(*parts)

        sql_io = StringIO()

        # break SQL into literals and non-literals to handle replacing
        # variables within them with query parameters
        for expr in re.split("('(?:[^']|(?:''))*')", sql):
            if expr.startswith("'"):
                sql_io.write(repl_literal(expr))
            else:
                sql_io.write(var_re.sub(repl, expr))
        
        # Remove arguments that don't appear in the SQL query
        for name in set(args) - names:
            del args[name]
        return sql_io.getvalue(), values, missing_args

    def _send_csv(self, req, cols, rows, sep=',', mimetype='text/plain',
                  filename=None):
        def iso_time(t):
            return format_time(from_utimestamp(t), 'iso8601')

        def iso_datetime(dt):
            return format_datetime(from_utimestamp(dt), 'iso8601')

        col_conversions = {
            'time': iso_time,
            'datetime': iso_datetime,
            'changetime': iso_datetime,
            'date': iso_datetime,
            'created': iso_datetime,
            'modified': iso_datetime,
        }

        converters = [col_conversions.get(c.strip('_'), cell_value)
                      for c in cols]

        out = StringIO()
        out.write('\xef\xbb\xbf')       # BOM
        writer = csv.writer(out, delimiter=sep)
        writer.writerow([unicode(c).encode('utf-8') for c in cols
                         if c not in self._html_cols])
        for row in rows:
            writer.writerow([converters[i](cell).encode('utf-8')
                             for i, cell in enumerate(row)
                             if cols[i] not in self._html_cols])
        data = out.getvalue()

        req.send_response(200)
        req.send_header('Content-Type', mimetype + ';charset=utf-8')
        req.send_header('Content-Length', len(data))
        if filename:
            req.send_header('Content-Disposition',
                            content_disposition(filename=filename))
        req.end_headers()
        req.write(data)
        raise RequestDone

    def _send_sql(self, req, id, title, description, sql):
        req.perm.require('REPORT_SQL_VIEW')

        out = StringIO()
        out.write('-- ## %s: %s ## --\n\n' % (id, title.encode('utf-8')))
        if description:
            lines = description.encode('utf-8').splitlines()
            out.write('-- %s\n\n' % '\n-- '.join(lines))
        out.write(sql.encode('utf-8'))
        data = out.getvalue()

        req.send_response(200)
        req.send_header('Content-Type', 'text/plain;charset=utf-8')
        req.send_header('Content-Length', len(data))
        if id:
            req.send_header('Content-Disposition',
                            content_disposition(filename='report_%s.sql' % id))
        req.end_headers()
        req.write(data)
        raise RequestDone
        
    # IWikiSyntaxProvider methods
    
    def get_link_resolvers(self):
        yield ('report', self._format_link)

    def get_wiki_syntax(self):
        yield (r"!?\{(?P<it_report>%s\s*)\d+\}" % WikiParser.INTERTRAC_SCHEME,
               lambda x, y, z: self._format_link(x, 'report', y[1:-1], y, z))

    def _format_link(self, formatter, ns, target, label, fullmatch=None):
        intertrac = formatter.shorthand_intertrac_helper(ns, target, label,
                                                         fullmatch)
        if intertrac:
            return intertrac
        report, args, fragment = formatter.split_link(target)
        return tag.a(label, href=formatter.href.report(report) + args,
                     class_='report')
