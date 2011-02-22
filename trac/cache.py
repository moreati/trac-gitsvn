# -*- coding: utf-8 -*-
#
# Copyright (C) 2009 Edgewall Software
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution. The terms
# are also available at http://trac.edgewall.com/license.html.
#
# This software consists of voluntary contributions made by many
# individuals. For the exact contribution history, see the revision
# history and logs, available at http://trac.edgewall.org/.

from __future__ import with_statement

from .core import Component
from .util import arity
from .util.concurrency import ThreadLocal, threading

__all__ = ['CacheManager', 'cached']


_id_to_key = {}

def key_to_id(s):
    """Return a hash of the given property key."""
    # This is almost the same algorithm as Python's string hash,
    # except we only keep a 31-bit result.
    result = ord(s[0]) << 7 if s else 0
    for c in s:
        result = ((1000003 * result) & 0x7fffffff) ^ ord(c)
    result ^= len(s)
    _id_to_key[result] = s
    return result


class CachedPropertyBase(object):
    """Base class for cached property descriptors"""

    def __init__(self, retriever):
        self.retriever = retriever
        self.__doc__ = retriever.__doc__
        
    def make_key(self, cls):
        attr = self.retriever.__name__
        for base in cls.mro():
            if base.__dict__.get(attr) is self:
                cls = base
                break
        return '%s.%s.%s' % (cls.__module__, cls.__name__, attr)

    
class CachedSingletonProperty(CachedPropertyBase):
    """Cached property descriptor for singleton classes"""
    
    def __get__(self, instance, owner):
        if instance is None:
            return self
        try:
            id = self.id
        except AttributeError:
            id = self.id = key_to_id(self.make_key(owner))
        return CacheManager(instance.env).get(id, self.retriever, instance)
        
    def __delete__(self, instance):
        try:
            id = self.id
        except AttributeError:
            id = self.id = key_to_id(self.make_key(instance.__class__))
        CacheManager(instance.env).invalidate(id)


class CachedProperty(CachedPropertyBase):
    """Cached property descriptor"""
    
    def __init__(self, retriever, key_attr):
        super(CachedProperty, self).__init__(retriever)
        self.key_attr = key_attr
        
    def __get__(self, instance, owner):
        if instance is None:
            return self
        id = getattr(instance, self.key_attr)
        if isinstance(id, str):
            id = key_to_id(self.make_key(owner) + ':' + id)
            setattr(instance, self.key_attr, id)
        return CacheManager(instance.env).get(id, self.retriever, instance)
        
    def __delete__(self, instance):
        id = getattr(instance, self.key_attr)
        if isinstance(id, str):
            id = key_to_id(self.make_key(instance.__class__) + ':' + id)
            setattr(instance, self.key_attr, id)
        CacheManager(instance.env).invalidate(id)


def cached(fn_or_attr=None):
    """Method decorator creating a cached attribute from a data
    retrieval method.
    
    Accessing the cached attribute gives back the cached value.  The
    data retrieval method is called as needed by the
    `CacheManager`. Invalidating the cache for this value is done by
    ``del``\ eting the attribute.
    
    Note that the cache validity is maintained using a table in the
    database.  Cache invalidation is performed within a transaction
    block, and can be nested within another transaction block.
    
    The key used to identify the attribute in the database is
    constructed from the names of the containing module, class and
    retriever method. If the decorator is used in non-signleton
    (typically non-`Component`) objects, an string specifying the name
    of an attribute containing a string unique to the instance must be
    passed to the decorator. This value will be appended to the key
    constructed from module, class and method name::

        class SomeClass(object):
            def __init__(self, env, name):
                self.env = env
                self.name = name
                self._metadata_id = name

            @cached('_metadata_id')
            def metadata(self):
                ...

    Note that the key attribute is overwritten with a hash of the key on first
    access, so it should not be used for any other purpose.
    
    This decorator requires that the object on which it is used has an `env`
    attribute containing the application `Environment`.

    .. versionchanged:: 0.13 

        The data retrieval method used to be called with a single
        argument ``db`` containing a reference to a database
        connection.  This is the same connection that can be retrieved
        via the normal `~trac.env.Environment.db_query` or
        `~trac.env.Environment.db_transaction`, so this is no longer
        needed, though methods supporting that argument are still
        supported (but will be removed in version 0.14).
    """
    if hasattr(fn_or_attr, '__call__'):
        return CachedSingletonProperty(fn_or_attr)
    def decorator(fn):
        return CachedProperty(fn, fn_or_attr)
    return decorator


class CacheManager(Component):
    """Cache manager."""

    required = True
    
    def __init__(self):
        self._cache = {}
        self._local = ThreadLocal(meta=None, cache=None)
        self._lock = threading.RLock()
    
    # Public interface
    
    def reset_metadata(self):
        """Reset per-request cache metadata."""
        self._local.meta = self._local.cache = None

    def get(self, id, retriever, instance):
        """Get cached or fresh data for the given id."""
        # Get cache metadata
        local_meta = self._local.meta
        local_cache = self._local.cache
        if local_meta is None:
            # First cache usage in this request, retrieve cache metadata
            # from the database and make a thread-local copy of the cache
            meta = self.env.db_query("SELECT id, generation FROM cache")
            self._local.meta = local_meta = dict(meta)
            self._local.cache = local_cache = self._cache.copy()
        
        db_generation = local_meta.get(id, -1)
        
        # Try the thread-local copy first
        try:
            (data, generation) = local_cache[id]
            if generation == db_generation:
                return data
        except KeyError:
            pass
        
        with self.env.db_query as db:
            with self._lock:
                # Get data from the process cache
                try:
                    (data, generation) = local_cache[id] = self._cache[id]
                    if generation == db_generation:
                        return data
                except KeyError:
                    generation = None   # Force retrieval from the database
                
                # Check if the process cache has the newest version, as it may
                # have been updated after the metadata retrieval
                for db_generation, in db(
                        "SELECT generation FROM cache WHERE id=%s", (id,)):
                    break
                else:
                    db_generation = -1
                if db_generation == generation:
                    return data
                
                # Retrieve data from the database
                if arity(retriever) == 2:
                    data = retriever(instance, db)
                else:
                    data = retriever(instance)
                local_cache[id] = self._cache[id] = (data, db_generation)
                local_meta[id] = db_generation
                return data
        
    def invalidate(self, id):
        """Invalidate cached data for the given id."""
        with self.env.db_transaction as db:
            with self._lock:
                # Invalidate in other processes

                # The row corresponding to the cache may not exist in the table
                # yet.
                #  - If the row exists, the UPDATE increments the generation,
                #    the SELECT returns a row and we're done.
                #  - If the row doesn't exist, the UPDATE does nothing, but 
                #    starts a transaction. The SELECT then returns nothing, 
                #    and we can safely INSERT a new row.
                db("UPDATE cache SET generation=generation+1 WHERE id=%s",
                   (id,))
                if not db("SELECT generation FROM cache WHERE id=%s", (id,)):
                    db("INSERT INTO cache VALUES (%s, %s, %s)",
                       (id, 0, _id_to_key.get(id, '<unknown>')))
                
                # Invalidate in this process
                self._cache.pop(id, None)
                
                # Invalidate in this thread
                try:
                    del self._local.cache[id]
                except (KeyError, TypeError):
                    pass
