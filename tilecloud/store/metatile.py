from cStringIO import StringIO

from PIL import Image

from tilecloud import Tile, TileStore


class MetaTileSplitterTileStore(TileStore):

    def __init__(self, format, tile_size=256, border=0, **kwargs):
        self.format = format
        self.tile_size = tile_size
        self.border = border
        TileStore.__init__(self, **kwargs)

    def get(self, tiles):
        for metatile in tiles:
            metaimage = Image.open(StringIO(metatile.data))
            for tilecoord in metatile.tilecoord:
                x = self.border + (tilecoord.x - metatile.tilecoord.x) * self.tile_size
                y = self.border + (tilecoord.y - metatile.tilecoord.y) * self.tile_size
                image = metaimage.crop((x, y, x + self.tile_size, y + self.tile_size))
                string_io = StringIO()
                image.save(string_io, self.format)
                yield Tile(tilecoord, data=string_io.getvalue())
