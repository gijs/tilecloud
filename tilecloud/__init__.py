#!/usr/bin/env python

import collections
from itertools import ifilter, imap, islice
import logging
from operator import attrgetter
import os.path
import re


logger = logging.getLogger(__name__)


def consume(iterator, n):  # pragma: no cover
    "Advance the iterator n-steps ahead. If n is none, consume entirely."
    # Use functions that consume iterators at C speed.
    if n is None:
        # feed the entire iterator into a zero-length deque
        collections.deque(iterator, maxlen=0)
    else:
        # advance to the empty slice starting at position n
        next(islice(iterator, n, n), None)


class Bounds(object):

    def __init__(self, start=None, stop=None):
        self.start = start
        if stop is None:
            self.stop = self.start + 1 if start is not None else None
        else:
            assert start is not None
            self.stop = stop

    def __cmp__(self, other):
        return cmp(self.start, other.start) or cmp(self.stop, other.stop)

    def __contains__(self, key):
        if self.start is None:
            return False
        else:
            return self.start <= key < self.stop

    def __len__(self):
        if self.start is None:
            return 0
        else:
            return self.stop - self.start

    def __iter__(self):
        if self.start is not None:
            for i in xrange(self.start, self.stop):
                yield i

    def __repr__(self):  # pragma: no cover
        if self.start is None:
            return '%s(None)' % (self.__class__.__name__,)
        else:
            return '%s(%r, %r)' % (self.__class__.__name__,
                                   self.start, self.stop)

    def add(self, value):
        """Extends self to include value"""
        if self.start is None:
            self.start = value
            self.stop = value + 1
        else:
            self.start = min(self.start, value)
            self.stop = max(self.stop, value + 1)
        return self

    def update(self, other):
        """Merges other into self"""
        if self.start is None:
            self.start = other.start
            self.stop = other.stop
        else:
            self.start = min(self.start, other.start)
            self.stop = max(self.stop, other.stop)
        return self

    def union(self, other):
        """Returns a new Bounds which is the union of self and other"""
        if self and other:
            return Bounds(min(self.start, other.start),
                          max(self.stop, other.stop))
        elif self:
            return Bounds(self.start, self.stop)
        elif other:
            return Bounds(other.start, other.stop)
        else:
            return Bounds()


class BoundingPyramid(object):

    def __init__(self, bounds=None):
        self.bounds = bounds or {}

    def __contains__(self, tilecoord):
        """Returns True if tilecoord is in self"""
        if tilecoord.z not in self.bounds:
            return False
        xbounds, ybounds = self.bounds[tilecoord.z]
        return tilecoord.x in xbounds and tilecoord.y in ybounds

    def __eq__(self, other):
        return self.bounds == other.bounds

    def __iter__(self):
        """Generates every TileCoord in self, in increasing z, x, and y order"""
        return self.itertopdown()

    def __len__(self):
        """Returns the total number of TileCoords in self"""
        return sum(len(xbounds) * len(ybounds)
                   for xbounds, ybounds in self.bounds.itervalues())

    def add(self, tilecoord):
        """Extends self to include tilecoord"""
        if tilecoord.z in self.bounds:
            xbounds, ybounds = self.bounds[tilecoord.z]
            xbounds.add(tilecoord.x)
            ybounds.add(tilecoord.y)
        else:
            self.bounds[tilecoord.z] = (Bounds(tilecoord.x),
                                        Bounds(tilecoord.y))
        return self

    def filldown(self, bottom, start=None):
        if start is None:
            start = max(self.bounds)
        for z in xrange(start, bottom):
            xbounds, ybounds = self.bounds[z]
            self.add(TileCoord(z + 1, xbounds.start * 2, ybounds.start * 2))
            self.add(TileCoord(z + 1, xbounds.stop * 2 - 1, ybounds.stop * 2 - 1))

    def fillup(self, top=0):
        for z in xrange(max(self.bounds), top, -1):
            xbounds, ybounds = self.bounds[z]
            self.add(TileCoord(z - 1, xbounds.start // 2, ybounds.start // 2))
            self.add(TileCoord(z - 1, max(xbounds.stop // 2 - 1, 0), max(ybounds.stop // 2 - 1, 0)))

    def iterbottomup(self):
        for z in reversed(sorted(self.bounds.keys())):
            for tilecoord in self.ziter(z):
                yield tilecoord

    def itertopdown(self):
        for z in sorted(self.bounds.keys()):
            for tilecoord in self.ziter(z):
                yield tilecoord

    def metatilecoords(self, n=8):
        for z in sorted(self.bounds.keys()):
            xbounds, ybounds = self.bounds[z]
            metatilecoord = TileCoord(z, xbounds.start, ybounds.start).metatilecoord(n)
            x = metatilecoord.x
            while x < xbounds.stop:
                y = metatilecoord.y
                while y < ybounds.stop:
                    yield TileCoord(z, x, y, n)
                    y += n
                x += n

    def zget(self, z):
        """Return the tuple (xbounds, ybounds) at level z"""
        return self.bounds[z]

    def ziter(self, z):
        """Generates every TileCoord in self at level z"""
        if z in self.bounds:
            xbounds, ybounds = self.bounds[z]
            for x in xbounds:
                for y in ybounds:
                    yield TileCoord(z, x, y)

    def zs(self):
        return self.bounds.keys()

    @classmethod
    def from_string(cls, s):
        match = re.match(
                r'(?P<z1>\d+)/(?P<x1>\d+)/(?P<y1>\d+):' +
                r'(?:(?P<plusz>\+)?(?P<z2>\d+)/)?' +
                r'(?:(?P<plusx>\+)?(?P<x2>\d+)|(?P<starx>\*))/' +
                r'(?:(?P<plusy>\+)?(?P<y2>\d+)|(?P<stary>\*))\Z', s)
        if not match:
            raise ValueError('invalid literal for %s.from_string(): %r' %
                             (cls.__name__, s))
        z1 = int(match.group('z1'))
        x1 = int(match.group('x1'))
        if match.group('starx'):
            x2 = 1 << z1
        elif match.group('plusx'):
            x2 = x1 + int(match.group('x2'))
        else:
            x2 = int(match.group('x2'))
        y1 = int(match.group('y1'))
        if match.group('stary'):
            y2 = 1 << z1
        elif match.group('plusy'):
            y2 = y1 + int(match.group('y2'))
        else:
            y2 = int(match.group('y2'))
        result = cls({z1: (Bounds(x1, x2), Bounds(y1, y2))})
        if match.group('z2'):
            z2 = int(match.group('z2'))
            if match.group('plusz'):
                z2 += z1
            if z1 < z2:
                result.filldown(z2)
            elif z1 > z2:
                result.fillup(z2)
        return result

    @classmethod
    def full(cls, zmin=None, zmax=None):
        assert zmax is not None
        zs = (zmax,) if zmin is None else xrange(zmin, zmax + 1)
        return cls(dict((z, (Bounds(0, 1 << z), Bounds(0, 1 << z)))
                        for z in zs))


class TileCoord(object):
    """A tile coordinate"""

    def __init__(self, z, x, y, n=1):
        self.z = z
        self.x = x
        self.y = y
        self.n = n

    def __cmp__(self, other):
        return cmp(self.n, other.n) or cmp(self.z, other.z) or cmp(self.x, other.x) or cmp(self.y, other.y)

    def __hash__(self):
        return ((self.x // self.n) << self.z) ^ (self.y // self.n)

    def __iter__(self):
        """Yield each TileCoord"""
        for i in xrange(0, self.n):
            for j in xrange(0, self.n):
                yield TileCoord(self.z, self.x + i, self.y + j)

    def __repr__(self):  # pragma: no cover
        if self.n == 1:
            return '%s(%r, %r, %r)' % (self.__class__.__name__,
                                       self.z, self.x, self.y)
        else:
            return '%s(%r, %r, %r, %r)' % (self.__class__.__name__,
                                           self.n, self.z, self.x, self.y)

    def __str__(self):
        if self.n == 1:
            return '%d/%d/%d' % (self.z, self.x, self.y)
        else:
            return '%d/%d/%d:+%d/+%d' % (self.z, self.x, self.y, self.n, self.n)

    def metatilecoord(self, n=8):
        return TileCoord(self.z, n * (self.x // n), n * (self.y // n), n)

    def tuple(self):
        return (self.z, self.x, self.y, self.n)

    @classmethod
    def from_string(cls, s):
        m = re.match(r'(\d+)/(\d+)/(\d+)(?::\+(\d+)/\+\4)?\Z', s)
        if not m:
            raise ValueError('invalid literal for %s.from_string: %r' % (cls.__name__, s))
        x, y, z, n = m.groups()
        return cls(int(x), int(y), int(z), int(n) if n else 1)

    @classmethod
    def from_tuple(cls, tpl):
        return cls(*tpl)


class TileLayout(object):
    """Maps tile coordinates to filenames and vice versa"""

    def filename(self, tilecoord):
        """Return the filename for the given tile coordinate"""
        raise NotImplementedError

    def tilecoord(self, filename):
        """Return the tile coordinate for the given filename"""
        raise NotImplementedError


class TileStructure(object):
    """Lays out tiles at multiple zoom levels"""

    def __init__(self, max_extent=None, tile_size=None, flip_y=False):
        self.max_extent = max_extent or (0.0, 0.0, 1.0, 1.0)
        self.tile_size = tile_size or 256
        self.flip_y = flip_y

    def children(self, tilecoord):
        """Generates all the children of tilecoord"""
        raise NotImplementedError

    def extent(self, tilecoord, border=0):
        """Returns the extent of the tile at tilecoord"""
        raise NotImplementedError

    def parent(self, tilecoord):
        """Returns the parent of tilecoord"""
        raise NotImplementedError

    def roots(self):
        """Generates all the root tiles"""
        raise NotImplementedError

    def tilecoord(self, z, x, y):
        """Returns the TileCoord for location (x, y) at level z"""
        raise NotImplementedError


class Tile(object):
    """An actual tile with optional metadata"""

    def __init__(self, tilecoord, content_encoding=None, content_type=None,
                 data=None, **kwargs):
        self.tilecoord = tilecoord
        self.content_encoding = content_encoding
        self.content_type = content_type
        self.data = data
        self.error = None
        for key, value in kwargs.iteritems():
            setattr(self, key, value)

    def __cmp__(self, other):
        return cmp(self.tilecoord, other.tilecoord)

    def __repr__(self):  # pragma: no cover
        keys = sorted(self.__dict__.keys())
        attrs = ''.join(' %s=%r' % (key, self.__dict__[key]) for key in keys)
        return '<Tile%s>' % (attrs,)


class TileStore(object):
    """A tile store"""

    def __init__(self, bounding_pyramid=None, content_type=None, **kwargs):
        self.bounding_pyramid = bounding_pyramid
        self.content_type = content_type
        for key, value in kwargs.iteritems():
            setattr(self, key, value)

    def __contains__(self, tile):
        if tile and self.bounding_pyramid:
            return tile.tilecoord in self.bounding_pyramid
        else:
            return False

    def __len__(self):
        """Returns the total number of tiles in the store"""
        return reduce(lambda x, _: x + 1, ifilter(None, self.list()), 0)

    def delete(self, tiles):
        """A generator that has the side effect of deleting the specified tiles
           from the store"""
        return imap(self.delete_one, ifilter(None, tiles))

    def delete_one(self, tile):
        """A function that deletes tile from the store and returns the tile"""
        raise NotImplementedError

    def get(self, tiles):
        """A generator that returns the specified tiles and their data from the
           store"""
        return imap(self.get_one, ifilter(None, tiles))

    def get_all(self):
        """A generator that returns all the tiles in the store with their
           data"""
        return imap(self.get_one, ifilter(None, self.list()))

    def get_bounding_pyramid(self):
        """Returns the bounding pyramid that encloses all tiles in the store"""
        return reduce(BoundingPyramid.add,
                      imap(attrgetter('tilecoord'),
                           ifilter(None, self.list())),
                      BoundingPyramid())

    def get_cheap_bounding_pyramid(self):
        """Returns a bounding pyramid that is cheap to calculate, or None if it
           is not possible to calculate a bounding pyramid cheaply"""
        return None

    def get_one(self, tile):
        """A function that gets the specified tile and its data from the
           store"""
        raise NotImplementedError

    def list(self):
        """A generator that returns the tiles in the store without necessarily
           retrieving their data"""
        if self.bounding_pyramid:
            for tilecoord in self.bounding_pyramid:
                yield Tile(tilecoord)

    def put(self, tiles):
        """A generator that has the side effect of putting the specified tiles
           in the store"""
        return imap(self.put_one, ifilter(None, tiles))

    def put_one(self, tile):
        """A function that puts tile in the store and returns the tile"""
        raise NotImplementedError

    @classmethod
    def load(cls, name):  # pragma: no cover
        if name == 'null://':
            from tilecloud.store.null import NullTileStore
            return NullTileStore()
        if name.startswith('bounds://'):
            from tilecloud.store.boundingpyramid import BoundingPyramidTileStore
            return BoundingPyramidTileStore(BoundingPyramid.from_string(name[9:]))
        if name.startswith('http://') or name.startswith('https://'):
            from tilecloud.layout.template import TemplateTileLayout
            from tilecloud.store.url import URLTileStore
            return URLTileStore((TemplateTileLayout(name),))
        if name.startswith('s3://'):
            from tilecloud.layout.template import TemplateTileLayout
            from tilecloud.store.s3 import S3TileStore
            bucket, template = name[5:].split('/', 1)
            return S3TileStore(bucket, TemplateTileLayout(template))
        if name.startswith('sqs://'):
            from tilecloud.store.sqs import SQSTileStore
            import boto.sqs
            from boto.sqs.jsonmessage import JSONMessage
            region_name, queue_name = name[6:].split('/', 1)
            connection = boto.sqs.connect_to_region(region_name)
            queue = connection.create_queue(queue_name)
            queue.set_message_class(JSONMessage)
            return SQSTileStore(queue)
        root, ext = os.path.splitext(name)
        if ext == '.bsddb':
            import bsddb
            from tilecloud.store.bsddb import BSDDBTileStore
            return BSDDBTileStore(bsddb.hashopen(name))
        if ext == '.mbtiles':
            import sqlite3
            from tilecloud.store.mbtiles import MBTilesTileStore
            return MBTilesTileStore(sqlite3.connect(name))
        if ext == '.zip':
            import zipfile
            from tilecloud.store.zip import ZipTileStore
            return ZipTileStore(zipfile.ZipFile(name, 'a'))
        module = __import__(name)
        components = name.split('.')
        module = reduce(lambda module, attr: getattr(module, attr),
                        components[1:],
                        module)
        return getattr(module, 'tilestore')
