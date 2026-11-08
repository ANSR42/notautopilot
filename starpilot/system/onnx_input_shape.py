"""Read a static NCHW input shape from an ONNX file.

OpenCV's DNN loader does not need the onnx package. The speed-limit detector
file stores images as [1, 3, 256, 256]. Its attention Reshape mask is
[1, 2, 128, 64], which has the same element count as [1, 256, 8, 8]. OpenCV
4.11 with a 640 blob reaches that layer as [1, 256, 20, 20] and rejects the
mask. This reader uses the protobuf field numbers of ModelProto, not a second
implementation of the network.
"""

from pathlib import Path


def _varint(buf: bytes, index: int) -> tuple[int, int]:
  value = 0
  shift = 0
  while True:
    byte = buf[index]
    index += 1
    value |= (byte & 0x7F) << shift
    if not byte & 0x80:
      return value, index
    shift += 7


def _fields(buf: bytes):
  index = 0
  while index < len(buf):
    key, index = _varint(buf, index)
    field, wire = key >> 3, key & 7
    if wire == 0:
      value, index = _varint(buf, index)
      yield field, value
    elif wire == 2:
      length, index = _varint(buf, index)
      yield field, buf[index:index + length]
      index += length
    elif wire == 1:
      index += 8
    elif wire == 5:
      index += 4
    else:
      return


def first_input_dims(model_path) -> list[int] | None:
  """dim_value list of the first graph input, or None when a dim is not static."""
  try:
    data = Path(model_path).read_bytes()
  except OSError:
    return None
  graph = next((value for field, value in _fields(data) if field == 7 and isinstance(value, bytes)), None)
  if graph is None:
    return None
  first_input = next((value for field, value in _fields(graph) if field == 11 and isinstance(value, bytes)), None)
  if first_input is None:
    return None
  type_proto = next((value for field, value in _fields(first_input) if field == 2 and isinstance(value, bytes)), None)
  if type_proto is None:
    return None
  tensor = next((value for field, value in _fields(type_proto) if field == 1 and isinstance(value, bytes)), None)
  if tensor is None:
    return None
  shape = next((value for field, value in _fields(tensor) if field == 2 and isinstance(value, bytes)), None)
  if shape is None:
    return None
  dims = []
  for field, value in _fields(shape):
    if field != 1 or not isinstance(value, bytes):
      continue
    dim_value = next((item for subfield, item in _fields(value) if subfield == 1 and isinstance(item, int)), None)
    if dim_value is None:
      return None
    dims.append(dim_value)
  return dims or None
