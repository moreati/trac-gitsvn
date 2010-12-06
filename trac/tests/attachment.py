# -*- coding: utf-8 -*-

from datetime import datetime
import os.path
import shutil
from StringIO import StringIO
import tempfile
import unittest

from trac.attachment import IAttachmentChangeListener, \
                            Attachment, AttachmentModule
from trac.core import Component, implements
from trac.perm import IPermissionPolicy, PermissionCache
from trac.resource import Resource, resource_exists
from trac.test import EnvironmentStub
from trac.util.datefmt import utc, to_utimestamp


class TicketOnlyViewsTicket(Component):
    implements(IPermissionPolicy)

    def check_permission(self, action, username, resource, perm):
        if action.startswith('TICKET_'):
            return resource.realm == 'ticket'
        else:
            return None


class TestAttachmentChangeListener(Component):
    implements(IAttachmentChangeListener)
    def __init__(self):
        self.added = []
        self.deleted = []
        self.deleted_version = []
        self.reparented = []

    def attachment_added(self, attachment):
        self.added.append(attachment)

    def attachment_deleted(self, attachment):
        self.deleted.append(attachment)

    def attachment_version_deleted(self, attachment, old_version):
        self.deleted_version.append((attachment, old_version))

    def attachment_reparented(self, attachment, old_parent_realm,
                              old_parent_id):
        self.reparented.append((attachment, old_parent_realm, old_parent_id))


class AttachmentTestCase(unittest.TestCase):

    def setUp(self):
        self.env = EnvironmentStub(enable=['trac.attachment.*',
                                           TicketOnlyViewsTicket,
                                           TestAttachmentChangeListener])
        self.env.path = os.path.join(tempfile.gettempdir(), 'trac-tempenv')
        os.mkdir(self.env.path)
        self.attachments_dir = os.path.join(self.env.path, 'attachments')
        self.archive_dir = os.path.join(self.env.path,
                                        AttachmentModule.ARCHIVE_DIR)
        self.env.config.set('trac', 'permission_policies',
                            'TicketOnlyViewsTicket, LegacyAttachmentPolicy')
        self.env.config.set('attachment', 'max_size', 512)

        self.perm = PermissionCache(self.env)

    def tearDown(self):
        shutil.rmtree(self.env.path)
        self.env.reset_db()

    def test_new_attachment(self):
        attachment = Attachment(self.env, 'ticket', 42)
        self.assertEqual(None, attachment.filename)
        self.assertEqual(0, attachment.version)
        self.assertEqual(False, attachment.exists)
        self.assertEqual(None, attachment.description)
        self.assertEqual(None, attachment.size)
        self.assertEqual(None, attachment.date)
        self.assertEqual(None, attachment.author)
        self.assertEqual(None, attachment.ipnr)
        self.assertEqual(None, attachment.status)

    def test_existing_attachment(self):
        t = datetime(2001, 1, 1, 1, 1, 1, 0, utc)
        db = self.env.get_db_cnx()
        cursor = db.cursor()
        cursor.execute("""INSERT INTO attachment
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                       ('ticket', '42', 'foo.txt', 1, 8, to_utimestamp(t), 
                        'A comment', 'joe', '::1', None))

        attachment = Attachment(self.env, 'ticket', 42, 'foo.txt')
        self.assertEqual('foo.txt', attachment.filename)
        self.assertEqual(1, attachment.version)
        self.assertEqual(True, attachment.exists)
        self.assertEqual('A comment', attachment.description)
        self.assertEqual(8, attachment.size)
        self.assertEqual(t, attachment.date)
        self.assertEqual('joe', attachment.author)
        self.assertEqual('::1', attachment.ipnr)
        self.assertEqual(None, attachment.status)
        
        resource = Resource('ticket', 42).child('attachment', 'foo.txt')
        attachment = Attachment(self.env, resource)
        self.assertEqual('foo.txt', attachment.filename)
        self.assertEqual(1, attachment.version)
        self.assertEqual(True, attachment.exists)
        self.assertEqual('A comment', attachment.description)
        self.assertEqual(8, attachment.size)
        self.assertEqual(t, attachment.date)
        self.assertEqual('joe', attachment.author)
        self.assertEqual('::1', attachment.ipnr)
        self.assertEqual(None, attachment.status)

    def test_get_path(self):
        attachment = Attachment(self.env, 'ticket', 42)
        attachment.filename = 'foo.txt'
        self.assertEqual(os.path.join(self.attachments_dir, 'ticket', '42',
                                      'foo.txt'),
                         attachment.path)
        attachment = Attachment(self.env, 'wiki', 'SomePage')
        attachment.filename = 'bar.jpg'
        self.assertEqual(os.path.join(self.attachments_dir, 'wiki', 'SomePage',
                                      'bar.jpg'),
                         attachment.path)

    def test_get_path_archived(self):
        attachment = Attachment(self.env, 'ticket', 42)
        attachment.filename = 'foo.txt'
        attachment.status = 'archived'
        self.assertEqual(os.path.join(self.archive_dir, 'ticket', '42',
                                      '00000_foo.txt'),
                         attachment.path)

    def test_get_path_encoded(self):
        attachment = Attachment(self.env, 'ticket', 42)
        attachment.filename = 'Teh foo.txt'
        self.assertEqual(os.path.join(self.attachments_dir, 'ticket', '42',
                                      'Teh%20foo.txt'),
                         attachment.path)
        attachment = Attachment(self.env, 'wiki', u'ÜberSicht')
        attachment.filename = 'Teh bar.jpg'
        self.assertEqual(os.path.join(self.attachments_dir, 'wiki',
                                      '%C3%9CberSicht', 'Teh%20bar.jpg'),
                         attachment.path)

    def test_get_path_internal(self):
        attachment = Attachment(self.env, 'ticket', 42)
        attachment.filename = 'foo.txt'
        self.assertEquals(self.attachments_dir, attachment._get_path())
        self.assertEquals(self.archive_dir,
                          attachment._get_path(status='archived'))
        attachment.status = 'archived'
        self.assertEquals(self.archive_dir, attachment._get_path())

    def test_select_empty(self):
        self.assertRaises(StopIteration,
                          Attachment.select(self.env, 'ticket', 42).next)
        self.assertRaises(StopIteration,
                          Attachment.select(self.env, 'wiki', 'SomePage').next)

    def test_insert(self):
        attachment = Attachment(self.env, 'ticket', 42)
        attachment.insert('foo.txt', StringIO(''), 0, 1)
        attachment = Attachment(self.env, 'ticket', 42)
        attachment.insert('bar.jpg', StringIO(''), 0, 2)

        attachments = Attachment.select(self.env, 'ticket', 42)
        self.assertEqual('foo.txt', attachments.next().filename)
        self.assertEqual('bar.jpg', attachments.next().filename)
        self.assertRaises(StopIteration, attachments.next)

        listener = TestAttachmentChangeListener(self.env)
        self.assertEquals('foo.txt', listener.added[0].filename)
        self.assertEquals('bar.jpg', listener.added[1].filename)

    def test_insert_unique(self):
        attachment = Attachment(self.env, 'ticket', 42)
        attachment.insert('foo.txt', StringIO(''), 0)
        self.assertEqual('foo.txt', attachment.filename)
        attachment = Attachment(self.env, 'ticket', 42)
        attachment.insert('foo.txt', StringIO(''), 0)
        self.assertEqual('foo.2.txt', attachment.filename)

    def test_insert_replace(self):
        attachment = Attachment(self.env, 'ticket', 42)
        attachment.insert('foo.txt', StringIO(''), 0)
        attachment = Attachment(self.env, 'ticket', 42)
        attachment.insert('foo.txt', StringIO(''), 0, replace=True)
        self.assertEqual('foo.txt', attachment.filename)
        self.assertEqual(2, attachment.version)

    def test_insert_replace_with_different_filename(self):
        attachment = Attachment(self.env, 'ticket', 42)
        attachment.insert('foo.txt', StringIO(''), 0)
        self.assertRaises(ValueError, attachment.insert, 'bar.jpg',
                          StringIO(''), 0)

        self.assertEqual('foo.txt', attachment.filename)

    def test_insert_archive_without_replace(self):
        # Without an existing version
        attachment = Attachment(self.env, 'ticket', 42)
        self.assertRaises(ValueError, attachment.insert, 'foo.txt',
                          StringIO(''), 0, replace=False, archive=True)
        attachment.insert('foo.txt', StringIO(''), 0)

        # With an existing version
        attachment = Attachment(self.env, 'ticket', 42)
        self.assertRaises(ValueError, attachment.insert, 'foo.txt',
                          StringIO(''), 0, replace=False, archive=True)

    def test_insert_archive_not_exist(self):
        attachment = Attachment(self.env, 'ticket', 42)
        self.assertRaises(ValueError, attachment.insert, 'foo.txt',
                          StringIO(''), 0, replace=True, archive=True)

    def test_insert_replace_archive(self):
        attachment = Attachment(self.env, 'ticket', 42)
        attachment.insert('foo.txt', StringIO(''), 0)
        attachment = Attachment(self.env, 'ticket', 42, filename='foo.txt')
        attachment.insert('foo.txt', StringIO(''), 0, replace=True,
                           archive=True)
        self.assertEqual(True, attachment.exists)
        self.assertEqual(2, attachment.version)
        self.assertEqual(None, attachment.status)
        self.assertEqual(os.path.join(self.attachments_dir,
                                      'ticket', '42', 'foo.txt'),
                         attachment.path)
        assert os.path.exists(attachment.path)

        attachment = Attachment(self.env, 'ticket', 42,
                                filename='foo.txt', version=1)
        self.assertEqual(True, attachment.exists)
        self.assertEqual(1, attachment.version)
        self.assertEqual('archived', attachment.status)
        self.assertEqual(os.path.join(self.archive_dir,
                                      'ticket', '42', '00001_foo.txt'),
                         attachment.path)
        assert os.path.exists(attachment.path)

    def test_insert_outside_attachments_dir(self):
        attachment = Attachment(self.env, '../../../../../sth/private', 42)
        self.assertRaises(AssertionError, attachment.insert, 'foo.txt',
                          StringIO(''), 0)

    def test_get_history(self):
        attachment = Attachment(self.env, 'wiki', 'SomePage')
        attachment.insert('foo.txt', StringIO(''), 0)

        attachment = Attachment(self.env, 'wiki', 'SomePage')
        attachment.insert('bar.jpg', StringIO(''), 0)
        attachment = Attachment(self.env, 'wiki', 'SomePage')
        attachment.description = 'New version'
        attachment.insert('bar.jpg', StringIO(''), 0, replace=True)

        history = list(attachment.get_history())
        self.assertEqual(2, len(history))
        self.assertEqual('bar.jpg', history[0].filename)
        self.assertEqual('New version', history[0].description)
        self.assertEqual('bar.jpg', history[1].filename)
        self.assertEqual(None, history[1].description)

        self.assertEqual(2, len(list(attachment.get_history(version=2))))

    def test_prev_next(self):
        attachment = Attachment(self.env, 'wiki', 'SomePage')
        attachment.insert('foo.txt', StringIO(''), 0)
        self.assertEqual((None, None), attachment.prev_next())

        attachment = Attachment(self.env, 'wiki', 'SomePage')
        attachment.insert('foo.txt', StringIO(''), 0, replace=True)
        self.assertEqual((1, None), attachment.prev_next())
        self.assertEqual((None, 2), attachment.prev_next(version=1))

        attachment = Attachment(self.env, 'wiki', 'SomePage')
        attachment.insert('foo.txt', StringIO(''), 0, replace=True)
        self.assertEqual((2, None), attachment.prev_next())
        self.assertEqual((None, 2), attachment.prev_next(version=1))
        self.assertEqual((1, 3), attachment.prev_next(version=2))

    def test_delete(self):
        attachment1 = Attachment(self.env, 'wiki', 'SomePage')
        attachment1.insert('foo.txt', StringIO(''), 0)
        attachment2 = Attachment(self.env, 'wiki', 'SomePage')
        attachment2.insert('bar.jpg', StringIO(''), 0)

        attachments = Attachment.select(self.env, 'wiki', 'SomePage')
        self.assertEqual(2, len(list(attachments)))

        attachment1.delete()
        attachment2.delete()

        assert not os.path.exists(attachment1.path)
        assert not os.path.exists(attachment2.path)

        attachments = Attachment.select(self.env, 'wiki', 'SomePage')
        self.assertEqual(0, len(list(attachments)))

        listener = TestAttachmentChangeListener(self.env)
        self.assertEqual('foo.txt', listener.deleted[0].filename)
        self.assertEqual('bar.jpg', listener.deleted[1].filename)

    def test_delete_file_gone(self):
        """
        Verify that deleting an attachment works even if the referenced file
        doesn't exist for some reason.
        """
        attachment = Attachment(self.env, 'wiki', 'SomePage')
        attachment.insert('foo.txt', StringIO(''), 0)
        os.unlink(attachment.path)

        attachment.delete()

    def test_delete_version(self):
        attachment = Attachment(self.env, 'wiki', 'SomePage')
        attachment.insert('foo.txt', StringIO(''), 0)
        attachment = Attachment(self.env, 'wiki', 'SomePage')
        attachment.insert('foo.txt', StringIO(''), 0, replace=True)

        attachment.delete(version=attachment.version)
        self.assertEqual(1, attachment.version)
        self.assertEqual(True, attachment.exists)
        assert not os.path.exists(attachment.path) #TODO Break with archiving?

        attachments = list(Attachment.select(self.env, 'wiki', 'SomePage'))
        self.assertEqual(1, len(attachments))

        listener = TestAttachmentChangeListener(self.env)
        self.assertEqual(1, len(listener.deleted_version))
        deleted_att, old_version = listener.deleted_version[0]
        self.assertEqual(attachment.filename, deleted_att.filename)
        self.assertEqual(2, old_version)

    def test_delete_archived(self):
        attachment = Attachment(self.env, 'wiki', 'SomePage')
        attachment.insert('foo.txt', StringIO(''), 0)
        attachment = Attachment(self.env, 'wiki', 'SomePage',
                                filename='foo.txt')
        attachment.insert('foo.txt', StringIO(''), 0, replace=True,
                          archive=True)
        attachment.delete()

        self.assertEqual([], os.listdir(os.path.join(self.attachments_dir,
                                                     'wiki', 'SomePage')))
        self.assertEqual([], os.listdir(os.path.join(self.archive_dir,
                                                     'wiki', 'SomePage')))

    def test_delete_version_archived(self):
        attachment = Attachment(self.env, 'wiki', 'SomePage')
        attachment.insert('foo.txt', StringIO(''), 0)
        attachment = Attachment(self.env, 'wiki', 'SomePage',
                                filename='foo.txt')
        attachment.insert('foo.txt', StringIO(''), 0, replace=True,
                          archive=True)

        # Delete older version
        attachment = Attachment(self.env, 'wiki', 'SomePage',
                                filename='foo.txt', version=1)
        old_path = attachment.path
        attachment.delete(version=attachment.version)
        self.assertEqual(2, attachment.version)
        self.assertEqual(True, attachment.exists)
        self.assertNotEqual('archived', attachment.status)
        self.assertNotEqual('deleted', attachment.status)
        assert not os.path.exists(old_path)

        # Delete current version
        attachment = Attachment(self.env, 'wiki', 'SomePage',
                                filename='foo.txt')
        old_path = attachment.path
        attachment.delete(version=attachment.version)
        assert not os.path.exists(old_path)

    def test_delete_last_version(self):
        attachment = Attachment(self.env, 'wiki', 'SomePage')
        attachment.insert('foo.txt', StringIO(''), 0)
        attachment.delete(version=attachment.version)
        self.assertEqual(False, attachment.exists)
        self.assertEqual(0, attachment.version)
        self.assertEqual('deleted', attachment.status)

    def test_reparent(self):
        attachment1 = Attachment(self.env, 'wiki', 'SomePage')
        attachment1.insert('foo.txt', StringIO(''), 0)
        path1 = attachment1.path
        attachment2 = Attachment(self.env, 'wiki', 'SomePage')
        attachment2.insert('bar.jpg', StringIO(''), 0)

        attachments = Attachment.select(self.env, 'wiki', 'SomePage')
        self.assertEqual(2, len(list(attachments)))
        attachments = Attachment.select(self.env, 'ticket', 123)
        self.assertEqual(0, len(list(attachments)))
        assert os.path.exists(path1) and os.path.exists(attachment2.path)

        attachment1.reparent('ticket', 123)
        self.assertEqual('ticket', attachment1.parent_realm)
        self.assertEqual('ticket', attachment1.resource.parent.realm)
        self.assertEqual('123', attachment1.parent_id)
        self.assertEqual('123', attachment1.resource.parent.id)
        
        attachments = Attachment.select(self.env, 'wiki', 'SomePage')
        self.assertEqual(1, len(list(attachments)))
        attachments = Attachment.select(self.env, 'ticket', 123)
        self.assertEqual(1, len(list(attachments)))
        assert not os.path.exists(path1) and os.path.exists(attachment1.path)
        assert os.path.exists(attachment2.path)

        listener = TestAttachmentChangeListener(self.env)
        self.assertEqual(1, len(listener.reparented))
        reparented_att, old_parent_realm, old_parent_id = \
                                                listener.reparented[0]
        self.assertEqual((attachment1.filename, 'wiki', 'SomePage'),
                         (reparented_att.filename,
                          old_parent_realm, old_parent_id))

    def test_reparent_versioned(self):
        attachment1 = Attachment(self.env, 'wiki', 'SomePage')
        attachment1.insert('foo.txt', StringIO(''), 0)
        attachment2 = Attachment(self.env, 'wiki', 'SomePage')
        attachment2.insert('foo.txt', StringIO(''), 0, replace=True)

        attachments = Attachment.select(self.env, 'wiki', 'SomePage')
        self.assertEqual(1, len(list(attachments)))
        attachments = Attachment.select(self.env, 'ticket', 123)
        self.assertEqual(0, len(list(attachments)))
        
        attachment1.reparent('ticket', 123)
        attachments = Attachment.select(self.env, 'wiki', 'SomePage')
        self.assertEqual(0, len(list(attachments)))
        attachments = Attachment.select(self.env, 'ticket', 123)
        self.assertEqual(1, len(list(attachments)))

        # TODO attachment2.{resource, path} is now invalid, does this matter?
        # TODO Test Listener 

    def test_legacy_permission_on_parent(self):
        """Ensure that legacy action tests are done on parent.  As
        `ATTACHMENT_VIEW` maps to `TICKET_VIEW`, the `TICKET_VIEW` is tested
        against the ticket's resource."""
        attachment = Attachment(self.env, 'ticket', 42)
        self.assert_('ATTACHMENT_VIEW' in self.perm(attachment.resource))

    def test_resource_doesnt_exist(self):
        r = Resource('wiki', 'WikiStart').child('attachment', 'file.txt')
        self.assertEqual(False, AttachmentModule(self.env).resource_exists(r))

    def test_resource_exists(self):
        att = Attachment(self.env, 'wiki', 'WikiStart')
        att.insert('file.txt', StringIO(''), 1)
        self.assertTrue(resource_exists(self.env, att.resource))


def suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(AttachmentTestCase, 'test'))
    return suite

if __name__ == '__main__':
    unittest.main(defaultTest='suite')
