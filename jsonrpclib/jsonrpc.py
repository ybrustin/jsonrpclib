#!/usr/bin/python
# -- Content-Encoding: UTF-8 --
"""
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

============================
JSONRPC Library (jsonrpclib)
============================

This library is a JSON-RPC v.2 (proposed) implementation which
follows the xmlrpclib API for portability between clients. It
uses the same Server / ServerProxy, loads, dumps, etc. syntax,
while providing features not present in XML-RPC like:

* Keyword arguments
* Notifications
* Versioning
* Batches and batch notifications

Eventually, I'll add a SimpleXMLRPCServer compatible library,
and other things to tie the thing off nicely. :)

For a quick-start, just open a console and type the following,
replacing the server address, method, and parameters
appropriately.
>>> import jsonrpclib
>>> server = jsonrpclib.Server('http://localhost:8181')
>>> server.add(5, 6)
11
>>> server._notify.add(5, 6)
>>> batch = jsonrpclib.MultiCall(server)
>>> batch.add(3, 50)
>>> batch.add(2, 3)
>>> batch._notify.add(3, 5)
>>> batch()
[53, 5]

See http://code.google.com/p/jsonrpclib/ for more info.
"""

# Library includes
from jsonrpclib import config, utils

# Standard library
import sys
import uuid

if sys.version_info[0] < 3:
    # Python 2
    from urllib import splittype
    from urllib import splithost
    from xmlrpclib import Transport as XMLTransport
    from xmlrpclib import SafeTransport as XMLSafeTransport
    from xmlrpclib import ServerProxy as XMLServerProxy
    from xmlrpclib import _Method as XML_Method

else:
    # Python 3
    from urllib.parse import splittype
    from urllib.parse import splithost
    from xmlrpc.client import Transport as XMLTransport
    from xmlrpc.client import SafeTransport as XMLSafeTransport
    from xmlrpc.client import ServerProxy as XMLServerProxy
    from xmlrpc.client import _Method as XML_Method

# ------------------------------------------------------------------------------
# JSON library import

# JSON class serialization
from jsonrpclib import jsonclass

try:
    # Using cjson
    import cjson

    # Declare cjson methods
    def jdumps(obj, encoding='utf-8'):
        return cjson.encode(obj)

    def jloads(json_string):
        return cjson.decode(json_string)

except ImportError:
    # Use json or simplejson
    try:
        import json
    except ImportError:
        try:
            import simplejson as json
        except ImportError:
            raise ImportError('You must have the cjson, json, or simplejson ' \
                              'module(s) available.')

    # Declare json methods
    if sys.version_info[0] < 3:
        def jdumps(obj, encoding='utf-8'):
            # Python 2 (explicit encoding)
            return json.dumps(obj, encoding=encoding)

    else:
        # Python 3
        def jdumps(obj, encoding='utf-8'):
            # Python 3 (the encoding parameter has been removed)
            return json.dumps(obj)

    def jloads(json_string):
        return json.loads(json_string)

# ------------------------------------------------------------------------------
# XMLRPClib re-implementations

class ProtocolError(Exception):
    pass

class AppError(ProtocolError):
    def data(self):
        return self[0][2]

class TransportMixIn(object):
    """ Just extends the XMLRPC transport where necessary. """
    user_agent = config.user_agent
    # for Python 2.7 support
    _connection = None

    def send_content(self, connection, request_body):
        # Convert the body first
        request_body = utils.to_bytes(request_body)

        connection.putheader("Content-Type", "application/json-rpc")
        connection.putheader("Content-Length", str(len(request_body)))
        connection.endheaders()
        if request_body:
            connection.send(request_body)

    def getparser(self):
        target = JSONTarget()
        return JSONParser(target), target

class JSONParser(object):
    def __init__(self, target):
        self.target = target

    def feed(self, data):
        self.target.feed(data)

    def close(self):
        pass

class JSONTarget(object):
    def __init__(self):
        self.data = []

    def feed(self, data):
        # Store raw data: it might not contain whole wide-character
        self.data.append(data)

    def close(self):
        if not self.data:
            return ''

        else:
            data = type(self.data[0])().join(self.data)
            try:
                # Convert the whole final string
                data = utils.from_bytes(data)
            except:
                # Try a pass-through
                pass

            return data

class Transport(TransportMixIn, XMLTransport):
    pass

class SafeTransport(TransportMixIn, XMLSafeTransport):
    pass

# ------------------------------------------------------------------------------

class ServerProxy(XMLServerProxy):
    """
    Unfortunately, much more of this class has to be copied since
    so much of it does the serialization.
    """

    def __init__(self, uri, transport=None, encoding=None,
                 verbose=0, version=None, history=None):
        """
        Sets up the server proxy
        
        :param uri: Request URI
        :param transport: Custom transport handler
        :param encoding: Specified encoding
        :param verbose: Log verbosity level
        :param version: JSON-RPC specification version
        :param history: History object (for tests)
        """
        if not version:
            version = config.version
        self.__version = version

        schema, uri = splittype(uri)
        if schema not in ('http', 'https'):
            raise IOError('Unsupported JSON-RPC protocol.')

        self.__host, self.__handler = splithost(uri)
        if not self.__handler:
            # Not sure if this is in the JSON spec?
            self.__handler = '/'

        if transport is None:
            if schema == 'https':
                transport = SafeTransport()
            else:
                transport = Transport()
        self.__transport = transport

        self.__encoding = encoding
        self.__verbose = verbose
        self.__history = history

    def _request(self, methodname, params, rpcid=None):
        request = dumps(params, methodname, encoding=self.__encoding,
                        rpcid=rpcid, version=self.__version)
        response = self._run_request(request)
        check_for_errors(response)
        return response['result']

    def _request_notify(self, methodname, params, rpcid=None):
        request = dumps(params, methodname, encoding=self.__encoding,
                        rpcid=rpcid, version=self.__version, notify=True)
        response = self._run_request(request, notify=True)
        check_for_errors(response)
        return

    def _run_request(self, request, notify=None):
        if self.__history is not None:
            self.__history.add_request(request)

        response = self.__transport.request(
            self.__host,
            self.__handler,
            request,
            verbose=self.__verbose
        )

        # Here, the XMLRPC library translates a single list
        # response to the single value -- should we do the
        # same, and require a tuple / list to be passed to
        # the response object, or expect the Server to be
        # outputting the response appropriately?

        if self.__history is not None:
            self.__history.add_response(response)

        if not response:
            return None
        return_obj = loads(response)
        return return_obj

    def __getattr__(self, name):
        # Same as original, just with new _Method reference
        return _Method(self._request, name)

    @property
    def _notify(self):
        # Just like __getattr__, but with notify namespace.
        return _Notify(self._request_notify)

# ------------------------------------------------------------------------------

class _Method(XML_Method):

    def __call__(self, *args, **kwargs):
        if len(args) > 0 and len(kwargs) > 0:
            raise ProtocolError('Cannot use both positional ' +
                'and keyword arguments (according to JSON-RPC spec.)')
        if len(args) > 0:
            return self.__send(self.__name, args)
        else:
            return self.__send(self.__name, kwargs)

    def __getattr__(self, name):
        if name == "__name__":
            return self.__name

        self.__name = '%s.%s' % (self.__name, name)
        return self
        # The old method returned a new instance, but this seemed wasteful.
        # The only thing that changes is the name.
        # return _Method(self.__send, "%s.%s" % (self.__name, name))

class _Notify(object):
    def __init__(self, request):
        self._request = request

    def __getattr__(self, name):
        return _Method(self._request, name)

# ------------------------------------------------------------------------------
# Batch implementation

class MultiCallMethod(object):

    def __init__(self, method, notify=False):
        self.method = method
        self.params = []
        self.notify = notify

    def __call__(self, *args, **kwargs):
        if len(kwargs) > 0 and len(args) > 0:
            raise ProtocolError('JSON-RPC does not support both ' +
                                'positional and keyword arguments.')
        if len(kwargs) > 0:
            self.params = kwargs
        else:
            self.params = args

    def request(self, encoding=None, rpcid=None):
        return dumps(self.params, self.method, version=2.0,
                     encoding=encoding, rpcid=rpcid, notify=self.notify)

    def __repr__(self):
        return '%s' % self.request()

    def __getattr__(self, method):
        new_method = '%s.%s' % (self.method, method)
        self.method = new_method
        return self

class MultiCallNotify(object):

    def __init__(self, multicall):
        self.multicall = multicall

    def __getattr__(self, name):
        new_job = MultiCallMethod(name, notify=True)
        self.multicall._job_list.append(new_job)
        return new_job

class MultiCallIterator(object):

    def __init__(self, results):
        self.results = results

    def __iter__(self):
        for i in range(0, len(self.results)):
            yield self[i]
        raise StopIteration

    def __getitem__(self, i):
        item = self.results[i]
        check_for_errors(item)
        return item['result']

    def __len__(self):
        return len(self.results)

class MultiCall(object):

    def __init__(self, server):
        self._server = server
        self._job_list = []

    def _request(self):
        if len(self._job_list) < 1:
            # Should we alert? This /is/ pretty obvious.
            return
        request_body = '[ %s ]' % ','.join([job.request() for
                                          job in self._job_list])
        responses = self._server._run_request(request_body)
        del self._job_list[:]
        if not responses:
            responses = []
        return MultiCallIterator(responses)

    @property
    def _notify(self):
        return MultiCallNotify(self)

    def __getattr__(self, name):
        new_job = MultiCallMethod(name)
        self._job_list.append(new_job)
        return new_job

    __call__ = _request

# These lines conform to xmlrpclib's "compatibility" line.
# Not really sure if we should include these, but oh well.
Server = ServerProxy

# ------------------------------------------------------------------------------

class Fault(object):
    """
    JSON-RPC error class
    """
    def __init__(self, code=-32000, message='Server error', rpcid=None):
        """
        Sets up the error description
        
        :param code: Fault code
        :param message: Associated message
        :param rpcid: Request ID
        """
        self.faultCode = code
        self.faultString = message
        self.rpcid = rpcid

    def error(self):
        """
        Returns the error as a dictionary
        
        :returns: A {'code', 'message'} dictionary
        """
        return {'code':self.faultCode, 'message':self.faultString}

    def response(self, rpcid=None, version=None):
        """
        Returns the error as a JSON-RPC response string
        
        :param rpcid: Forced request ID
        :param version: JSON-RPC version
        :return: A JSON-RPC response string
        """
        if not version:
            version = config.version

        if rpcid:
            self.rpcid = rpcid

        return dumps(self, methodresponse=True, rpcid=self.rpcid,
                     version=version)

    def dump(self, rpcid=None, version=None):
        """
        Returns the error as a JSON-RPC response dictionary
        
        :param rpcid: Forced request ID
        :param version: JSON-RPC version
        :return: A JSON-RPC response dictionary
        """
        if not version:
            version = config.version

        if rpcid:
            self.rpcid = rpcid

        return dump(self, is_response=True, rpcid=self.rpcid,
                    version=version)

    def __repr__(self):
        """
        String representation
        """
        return '<Fault {0}: {1}>'.format(self.faultCode, self.faultString)


class Payload(object):
    """
    JSON-RPC content handler
    """
    def __init__(self, rpcid=None, version=None):
        """
        Sets up the JSON-RPC handler
        
        :param rpcid: Request ID
        :param version: JSON-RPC version
        """
        if not version:
            version = config.version

        self.id = rpcid
        self.version = float(version)


    def request(self, method, params=[]):
        """
        Prepares a method call request
        
        :param method: Method name
        :param params: Method parameters
        :return: A JSON-RPC request dictionary
        """
        if type(method) not in utils.StringTypes:
            raise ValueError('Method name must be a string.')

        if not self.id:
            # Generate a request ID
            self.id = str(uuid.uuid4())

        request = { 'id':self.id, 'method':method }
        if params or self.version < 1.1:
            request['params'] = params

        if self.version >= 2:
            request['jsonrpc'] = str(self.version)

        return request


    def notify(self, method, params=[]):
        """
        Prepares a notification request
        
        :param method: Notification name
        :param params: Notification parameters
        :return: A JSON-RPC notification dictionary
        """
        # Prepare the request dictionary
        request = self.request(method, params)

        # Remove the request ID, as it's a notification
        if self.version >= 2:
            del request['id']
        else:
            request['id'] = None

        return request


    def response(self, result=None):
        """
        Prepares a response dictionary
        
        :param result: The result of method call
        :return: A JSON-RPC response dictionary
        """
        response = {'result':result, 'id':self.id}

        if self.version >= 2:
            response['jsonrpc'] = str(self.version)
        else:
            response['error'] = None

        return response


    def error(self, code=-32000, message='Server error.'):
        """
        Prepares an error dictionary
        
        :param code: Error code
        :param message: Error message
        :return: A JSON-RPC error dictionary
        """
        error = self.response()
        if self.version >= 2:
            del error['result']
        else:
            error['result'] = None
        error['error'] = {'code':code, 'message':message}
        return error

# ------------------------------------------------------------------------------

def dump(params=[], methodname=None, rpcid=None, version=None,
         is_response=None, is_notify=None):
    """
    Prepares a JSON-RPC dictionary (request, notification, response or error)
    
    :param params: Method parameters (if a method name is given) or a Fault
    :param methodname: Method name
    :param rpcid: Request ID
    :param version: JSON-RPC version
    :param is_response: If True, this is a response dictionary
    :param is_notify: If True, this is a notification request
    :return: A JSON-RPC dictionary
    """
    # Default version
    if not version:
        version = config.version

    # Validate method name and parameters
    valid_params = (utils.TupleType, utils.ListType, utils.DictType, Fault)
    if methodname in utils.StringTypes and \
    not isinstance(params, valid_params):
        """
        If a method, and params are not in a listish or a Fault,
        error out.
        """
        raise TypeError('Params must be a dict, list, tuple or Fault instance.')

    # Prepares the JSON-RPC content
    payload = Payload(rpcid=rpcid, version=version)

    if type(params) is Fault:
        # Prepare an error dictionary
        return payload.error(params.faultCode, params.faultString)

    if type(methodname) not in utils.StringTypes and not is_response:
        # Neither a request nor a response
        raise ValueError('Method name must be a string, or is_response ' \
                         'must be set to True.')

    if config.use_jsonclass:
        # Use jsonclass to convert the parameters
        params = jsonclass.dump(params)

    if is_response:
        # Prepare a response dictionary
        if rpcid is None:
            # A response must have a request ID
            raise ValueError('A method response must have an rpcid.')
        return payload.response(params)

    if is_notify:
        # Prepare a notification dictionary
        return payload.notify(methodname, params)

    else:
        # Prepare a method call dictionary
        return payload.request(methodname, params)


def dumps(params=[], methodname=None, methodresponse=None,
          encoding=None, rpcid=None, version=None, notify=None):
    """
    Prepares a JSON-RPC request/response string
    
    :param params: Method parameters (if a method name is given) or a Fault
    :param methodname: Method name
    :param methodresponse: If True, this is a response dictionary
    :param encoding: Result string encoding
    :param rpcid: Request ID
    :param version: JSON-RPC version
    :param notify: If True, this is a notification request
    :return: A JSON-RPC dictionary
    """
    # Prepare the dictionary
    request = dump(params, methodname, rpcid, version, methodresponse, notify)

    # Set the default encoding
    if not encoding:
        encoding = "UTF-8"

    # Returns it as a JSON string
    return jdumps(request, encoding=encoding)


def load(data):
    """
    Loads a JSON-RPC request/response dictionary. Calls jsonclass to load beans
    
    :param data: A JSON-RPC dictionary
    :return: A parsed dictionary or None
    """
    if data is None:
        # Notification
        return None

    # if the above raises an error, the implementing server code
    # should return something like the following:
    # { 'jsonrpc':'2.0', 'error': fault.error(), id: None }
    if config.use_jsonclass:
        # Convert beans
        data = jsonclass.load(data)

    return data


def loads(data):
    """
    Loads a JSON-RPC request/response string. Calls jsonclass to load beans
    
    :param data: A JSON-RPC string
    :return: A parsed dictionary or None
    """
    if data == '':
        # Notification
        return None

    # Parse the JSON dictionary
    result = jloads(data)

    # Load the beans
    return load(result)

# ------------------------------------------------------------------------------

def check_for_errors(result):
    """
    Checks if a result dictionary signals an error
    
    :param result: A result dictionary
    :raise TypeError: Invalid parameter
    :raise NotImplementedError: Unknown JSON-RPC version
    :raise ValueError: Invalid dictionary content
    :raise ProtocolError: An error occurred on the server side
    :return: The result parameter
    """
    if not result:
        # Notification
        return result

    if type(result) is not utils.DictType:
        # Invalid argument
        raise TypeError('Response is not a dict.')

    if 'jsonrpc' in result and float(result['jsonrpc']) > 2.0:
        # Unknown JSON-RPC version
        raise NotImplementedError('JSON-RPC version not yet supported.')

    if 'result' not in result and 'error' not in result:
        # Invalid dictionary content
        raise ValueError('Response does not have a result or error key.')

    if 'error' in result and result['error']:
        # Server-side error
        if 'code' in result['error']:
            # Code + Message
            code = result['error']['code']
            try:
                # Get the message (jsonrpclib)
                message = result['error']['message']

            except KeyError:
                # Get the trace (jabsorb)
                message = result['error'].get('trace', '<no error message>')

            if -32700 <= code <= -32000:
                # Pre-defined errors
                # See http://www.jsonrpc.org/specification#error_object
                raise ProtocolError((code, message))

            else:
                # Application error
                data = result['error'].get('data', None)
                raise AppError((code, message, data))

            raise ProtocolError((code, message))

        elif isinstance(result['error'], dict) and len(result['error']) == 1:
            # Error with a single entry ('reason', ...): use its content
            error_key = result['error'].keys()[0]
            raise ProtocolError(result['error'][error_key])

        else:
            # Use the raw error content
            raise ProtocolError(result['error'])

    return result


def isbatch(result):
    if type(result) not in (utils.ListType, utils.TupleType):
        return False
    if len(result) < 1:
        return False
    if type(result[0]) is not utils.DictType:
        return False
    if 'jsonrpc' not in result[0].keys():
        return False
    try:
        version = float(result[0]['jsonrpc'])
    except ValueError:
        raise ProtocolError('"jsonrpc" key must be a float(able) value.')
    if version < 2:
        return False
    return True


def isnotification(request):
    """
    Tests if the given request is a notification
    
    :param request: A request dictionary
    :return: True if the request is a notification
    """
    if 'id' not in request:
        # 2.0 notification
        return True

    if request['id'] is None:
        # 1.0 notification
        return True

    return False
