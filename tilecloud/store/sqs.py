import logging

from boto.exception import SQSDecodeError, SQSError

from tilecloud import Tile, TileCoord, TileStore


logger = logging.getLogger(__name__)


class SQSTileStore(TileStore):

    def __init__(self, queue, **kwargs):
        TileStore.__init__(self, **kwargs)
        self.queue = queue

    def __contains__(self, tile):
        return False

    def get_one(self, tile):
        return tile

    def list(self):
        while True:
            try:
                sqs_message = self.queue.read()
                if sqs_message is None:
                    break  # FIXME or maybe retry?
                z = sqs_message.get('z')
                x = sqs_message.get('x')
                y = sqs_message.get('y')
                # FIXME deserialize other attributes
                tile = Tile(TileCoord(z, x, y), sqs_message=sqs_message)
                yield tile
            except SQSDecodeError as e:
                logger.warning(str(e))
                sqs_message.delete()

    def delete_one(self, tile):
        assert hasattr(tile, 'sqs_message')
        tile.sqs_message.delete()
        delattr(tile, 'sqs_message')
        return tile

    def put_one(self, tile):
        sqs_message = self.queue.new_message()
        sqs_message['z'] = tile.tilecoord.z
        sqs_message['x'] = tile.tilecoord.x
        sqs_message['y'] = tile.tilecoord.y
        # FIXME serialize other attributes
        try:
            self.queue.write(sqs_message)
            tile.sqs_message = sqs_message
        except SQSError as e:
            tile.error = e