"""Feishu WS wire schema, matching the official pbbp2.proto (SDK v2).

Only protobuf is needed; importing the complete SDK also imports every REST
model and its own event loop. Wire fields: larksuite/oapi-sdk-python/ws/pb.
"""
from google.protobuf.descriptor_pb2 import FileDescriptorProto, FieldDescriptorProto as F
from google.protobuf.descriptor_pool import DescriptorPool
from google.protobuf.message_factory import GetMessageClass


def frame_type():
    schema = FileDescriptorProto(name='tiance_feishu.proto', package='tiance_feishu', syntax='proto2')
    header = schema.message_type.add(name='Header')
    for number, name in enumerate(('key', 'value'), 1):
        header.field.add(name=name, number=number, type=F.TYPE_STRING, label=F.LABEL_REQUIRED)
    frame = schema.message_type.add(name='Frame')
    for number, name, kind in [(1, 'SeqID', F.TYPE_UINT64), (2, 'LogID', F.TYPE_UINT64),
                               (3, 'service', F.TYPE_INT32), (4, 'method', F.TYPE_INT32),
                               (6, 'payload_encoding', F.TYPE_STRING), (7, 'payload_type', F.TYPE_STRING),
                               (8, 'payload', F.TYPE_BYTES), (9, 'LogIDNew', F.TYPE_STRING)]:
        frame.field.add(name=name, number=number, type=kind,
                        label=F.LABEL_REQUIRED if number < 5 else F.LABEL_OPTIONAL)
    frame.field.add(name='headers', number=5, type=F.TYPE_MESSAGE, label=F.LABEL_REPEATED,
                    type_name='.tiance_feishu.Header')
    pool = DescriptorPool()
    pool.Add(schema)
    return GetMessageClass(pool.FindMessageTypeByName('tiance_feishu.Frame'))


Frame = frame_type()
