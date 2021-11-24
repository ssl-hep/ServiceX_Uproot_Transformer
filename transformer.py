# Copyright (c) 2019, IRIS-HEP
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# * Neither the name of the copyright holder nor the names of its
#   contributors may be used to endorse or promote products derived from
#   this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
import json
import sys
import traceback

import awkward as ak
import uproot
import time

from servicex.transformer.servicex_adapter import ServiceXAdapter
from servicex.transformer.transformer_argument_parser import TransformerArgumentParser
from servicex.transformer.object_store_manager import ObjectStoreManager
from servicex.transformer.rabbit_mq_manager import RabbitMQManager
from servicex.transformer.arrow_writer import ArrowWriter
from hashlib import sha1
import os
import pyarrow.parquet as pq

# Needed until we use xrootd>=5.2.0
# see https://github.com/ssl-hep/ServiceX_Uproot_Transformer/issues/22
uproot.open.defaults["xrootd_handler"] = uproot.MultithreadedXRootDSource

messaging = None
object_store = None
posix_path = None
MAX_PATH_LEN = 255


class ArrowIterator:
    def __init__(self, arrow, file_path):
        self.arrow = arrow
        self.file_path = file_path
        self.attr_name_list = ["not available"]

    def arrow_table(self):
        yield self.arrow


def hash_path(file_name):
    """
    Make the path safe for object store or POSIX, by keeping the length
    less than MAX_PATH_LEN. Replace the leading (less interesting) characters with a
    forty character hash.
    :param file_name: Input filename
    :return: Safe path string
    """
    if len(file_name) > MAX_PATH_LEN:
        hash = sha1(file_name.encode('utf-8')).hexdigest()
        return ''.join([
            '_', hash,
            file_name[-1 * (MAX_PATH_LEN - len(hash) - 1):],
        ])
    else:
        return file_name


# noinspection PyUnusedLocal
def callback(channel, method, properties, body):
    transform_request = json.loads(body)
    _request_id = transform_request['request-id']
    _file_path = transform_request['file-path']
    _file_id = transform_request['file-id']
    _server_endpoint = transform_request['service-endpoint']
    servicex = ServiceXAdapter(_server_endpoint)

    tick = time.time()
    try:
        # Do the transform
        servicex.post_status_update(file_id=_file_id,
                                    status_code="start",
                                    info="Starting")

        root_file = _file_path.replace('/', ':')
        if not os.path.isdir(posix_path):
            os.makedirs(posix_path)

        safe_output_file = hash_path(root_file+".parquet")
        output_path = os.path.join(posix_path, safe_output_file)
        transform_single_file(_file_path, output_path, servicex)

        tock = time.time()

        if object_store:
            object_store.upload_file(_request_id, safe_output_file, output_path)
            os.remove(output_path)

        servicex.post_status_update(file_id=_file_id,
                                    status_code="complete",
                                    info="Success")

        servicex.put_file_complete(_file_path, _file_id, "success",
                                   num_messages=0,
                                   total_time=round(tock - tick, 2),
                                   total_events=0,
                                   total_bytes=0)

    except Exception as error:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        traceback.print_tb(exc_traceback, limit=20, file=sys.stdout)
        print(exc_value)

        transform_request['error'] = str(error)
        channel.basic_publish(exchange='transformation_failures',
                              routing_key=_request_id + '_errors',
                              body=json.dumps(transform_request))

        servicex.post_status_update(file_id=_file_id,
                                    status_code="failure",
                                    info="error: "+str(exc_value))

        servicex.put_file_complete(file_path=_file_path, file_id=_file_id,
                                   status='failure', num_messages=0, total_time=0,
                                   total_events=0, total_bytes=0)
    finally:
        channel.basic_ack(delivery_tag=method.delivery_tag)


def transform_single_file(file_path, output_path, servicex=None):
    print("Transforming a single path: " + str(file_path))

    try:
        import generated_transformer
        start_transform = time.time()
        awkward_array = generated_transformer.run_query(file_path)
        end_transform = time.time()
        print(f'generated_transformer.py: {round(end_transform - start_transform, 2)} sec')

        start_serialization = time.time()
        try:
            arrow = ak.to_arrow_table(awkward_array, explode_records=True)
        except TypeError:
            arrow = ak.to_arrow_table(ak.repartition(awkward_array, None), explode_records=True)
        end_serialization = time.time()
        print(f'awkward Array -> Arrow: {round(end_serialization - start_serialization, 2)} sec')

        if output_path:
            writer = pq.ParquetWriter(output_path, arrow.schema)
            writer.write_table(table=arrow)
            writer.close()

    except Exception:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        traceback.print_tb(exc_traceback, limit=20, file=sys.stdout)
        print(exc_value)

        raise RuntimeError(
            "Failed to transform input file " + file_path + ": " + str(exc_value))

    if messaging:
        arrow_writer = ArrowWriter(file_format=args.result_format,
                                   object_store=None,
                                   messaging=messaging)

        transformer = ArrowIterator(arrow, file_path=file_path)
        arrow_writer.write_branches_to_arrow(transformer=transformer, topic_name=args.request_id,
                                             file_id=None, request_id=args.request_id)


def compile_code():
    import generated_transformer
    pass


if __name__ == "__main__":
    parser = TransformerArgumentParser(description="Uproot Transformer")
    args = parser.parse_args()

    print("-----", sys.path)

    print(args.result_destination, args.output_dir)

    if args.result_destination == 'object-store':
        messaging = None
        posix_path = "/home/atlas"
        object_store = ObjectStoreManager()
    elif args.result_destination == 'volume':
        messaging = None
        object_store = None
        posix_path = args.output_dir
    elif args.output_dir:
        messaging = None
        object_store = None

    compile_code()

    if args.request_id and not args.path:
        rabbitmq = RabbitMQManager(args.rabbit_uri, args.request_id, callback)

    if args.path:
        print("Transform a single file ", args.path)
        transform_single_file(args.path, args.output_dir)
