#!/usr/bin/env python

# Copyright (c) 2014 clowwindy
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from __future__ import absolute_import, division, print_function, \
    with_statement

import os
import logging
from ctypes import CDLL, c_char_p, c_int, c_ulonglong, byref, \
    create_string_buffer, c_void_p, c_ulong

logger = logging.getLogger('ctypes_libsodium')
logger.setLevel(logging.INFO)
hdr = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s %(name)s:%(levelname)s %(message)s',
                              datefmt='%H:%M:%S')
hdr.setFormatter(formatter)
logger.addHandler(hdr)

__all__ = ['ciphers']

libsodium = None
loaded = False

buf_size = 2048

# for salsa20 and chacha20
BLOCK_SIZE = 64


def load_libsodium():
    global loaded, libsodium, buf

    from ctypes.util import find_library

    if os.name == "nt" and os.path.isfile('./Python27/libsodium.dll'):
        libsodium_path = './Python27/libsodium.dll'
    else:
        for p in ('sodium', 'libsodium', ):
            libsodium_path = find_library(p)
            if libsodium_path:
                break
    if not libsodium_path:
        raise IOError(0, 'libsodium not found')
    logger.info('loading libsodium from %s' % libsodium_path)
    libsodium = CDLL(libsodium_path)
    libsodium.sodium_init.restype = c_int
    libsodium.crypto_stream_salsa20_xor_ic.restype = c_int
    libsodium.crypto_stream_salsa20_xor_ic.argtypes = (c_void_p, c_char_p,
                                                       c_ulonglong,
                                                       c_char_p, c_ulonglong,
                                                       c_char_p)
    libsodium.crypto_stream_chacha20_xor_ic.restype = c_int
    libsodium.crypto_stream_chacha20_xor_ic.argtypes = (c_void_p, c_char_p,
                                                        c_ulonglong,
                                                        c_char_p, c_ulonglong,
                                                        c_char_p)

    try:
        libsodium.crypto_stream_chacha20_ietf_xor_ic.restype = c_int
        libsodium.crypto_stream_chacha20_ietf_xor_ic.argtypes = (c_void_p, c_char_p,
                                                                 c_ulonglong,
                                                                 c_char_p, c_ulong,
                                                                 c_char_p)
    except:
        pass

    libsodium.sodium_init()

    buf = create_string_buffer(buf_size)
    loaded = True


class Salsa20Crypto(object):
    def __init__(self, cipher_name, key, iv, op):
        if not loaded:
            load_libsodium()
        self.key = key
        self.iv = iv
        self.key_ptr = c_char_p(key)
        self.iv_ptr = c_char_p(iv)
        if cipher_name == 'salsa20':
            self.cipher = libsodium.crypto_stream_salsa20_xor_ic
        elif cipher_name == 'chacha20':
            self.cipher = libsodium.crypto_stream_chacha20_xor_ic
        elif cipher_name == 'chacha20-ietf':
            self.cipher = libsodium.crypto_stream_chacha20_ietf_xor_ic
        else:
            raise Exception('Unknown cipher')
        # byte counter, not block counter
        self.counter = 0

    def update(self, data):
        global buf_size, buf
        l = len(data)

        # we can only prepend some padding to make the encryption align to
        # blocks
        padding = self.counter % BLOCK_SIZE
        if buf_size < padding + l:
            buf_size = (padding + l) * 2
            buf = create_string_buffer(buf_size)

        if padding:
            data = (b'\0' * padding) + data
        self.cipher(byref(buf), c_char_p(data), padding + l,
                    self.iv_ptr, self.counter // BLOCK_SIZE, self.key_ptr)
        self.counter += l
        # buf is copied to a str object when we access buf.raw
        # strip off the padding
        return buf.raw[padding:padding + l]


ciphers = {
    'salsa20': (32, 8, Salsa20Crypto),
    'chacha20': (32, 8, Salsa20Crypto),
}
