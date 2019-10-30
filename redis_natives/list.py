from .errors import RedisValueError, RedisTypeError
from .datatypes import RedisSortable
from collections import Sequence


class List(RedisSortable, Sequence):

    __slots__ = ("_key", "_client", "_pipe")

    def __init__(self, client, key, type=str, iter=[]):
        super(List, self).__init__(client, key, type)
        if hasattr(iter, "__iter__") and len(iter):
            # TODO: What if the key already exists?
            for val in iter:
                self._pipe.rpush(self.key, val)
            self._pipe.execute()

    def __contains__(self, el):
        # As long as redis doesn't support lookups by value, we
        # have to use this inefficient workaround
        return str(self.type_prepare(el)) in \
            self._client.lrange(self.key, 0, -1)

    def __iter__(self):
        for el in map(self.type_convert, self._client.lrange(self.key, 0, -1)):
            yield self.type(el)

    def __len__(self):
        return self._client.llen(self.key)

    def __reversed__(self):
        return map(self.type_convert,
                   self._client.lrange(self.key, 0, -1)).reverse()

    def __getitem__(self, key):
        if isinstance(key, slice):
            stop = key.stop
            if stop is None:
                stop = -1
            else:
                stop -= 1
            start = key.start
            if start is None:
                start = 0
            return map(
                self.type_convert,
                self._client.lrange(self._key, start, stop)
            )
        else:
            return self.type_convert(self._client.lindex(self._key, key))

    def __setitem__(self, key, value):
        value = self.type_prepare(value)
        if isinstance(key, slice):
            if key.stop is None:
                stop = self.__len__() - 1
            else:
                stop = key.stop
            start = key.start
            if start is None:
                start = 0

            for i in range(start, stop + 1):
                self._client.lset(self._key, i, value)
        else:
            return self._client.lset(self._key, key, value)

    def __delitem__(self):
        raise NotImplementedError("Method '__delitem__' not implemented yet")

    def append(self, el):
        """Pushes element ``el`` at the end of this list.
        """
        self._client.rpush(self.key, self.type_prepare(el))

    def count(self, el):
        """Returns the number of occurences of value ``el`` within this list.
        """
        return self._client.lrange(self.key, 0, -1).count(el)

    def extend(self, iter):
        """Extends this list with the elements of ther iterable ``iter``
        """
        if hasattr(iter, "__iter__"):
            map(lambda el: self._pipe.rpush(el), iter)
            self._pipe.execute()
        else:
            raise RedisTypeError("Argument must be iterable")

    def insert(self, idx, el):
        """Insert element ``el`` at index ``idx``
        """
        count = self._client.llen(self.key)
        if count < idx:
            raise IndexError("Index out of range")
        else:
            el = self.type_prepare(el)
            if idx == 0:
                self._client.lpush(self.key, el)
            else:
                self._client.lset(self.key, idx, el)

    def index(self, el):
        """Return index of first occurence of value ``el`` within this list.
        """
        return self.type_convert(self._client.lindex(self.key, el))

    def pop(self, idx=None):
        """Remove and return element at index ``idx``.
        """
        if idx is None:
            return self.type_convert(self._client.rpop(self.key))
        elif isinstance(idx, int):
            if idx == 0:
                return self.type_convert(self._client.lpop(self.key))
            else:
                return self.__delitem__(idx)
        else:
            raise TypeError("Argument must be type of 'int' or 'NoneType'")

    def remove(self, val, n=1, all=False):
        """
        Removes ``n`` occurences of value ``el``. When ``n`` is ``0``
        all occurences will be removed. When ``n`` is negative the lookup
        start at the end, otherwise from the beginning.

        Returns number of removed values as ``int``.
        """
        val = self.type_prepare(val)
        if all:
            if self._client.lrem(self.key, val, 0):
                return None
        elif isinstance(n, int):
            if self._client.lrem(self.key, val, n):
                return None
        else:
            raise RedisTypeError("Argument 'count' must be type of 'int'")
        raise RedisValueError("Value '" + str(val) + "' not present")

    def bpop_head(self, keys=[], timeout=0):
        """
        ``pop_tail`` a value off of the first non-empty list named in the
        ``keys`` list and return it together with the ``key`` that unblocked
        it as a two-element tuple.

        If none of the lists in ``keys`` has a value to ``pop_tail``, then
        block for ``timeout`` seconds, or until a value gets pushed on to
        one of the lists.

        If ``timeout`` is 0, then block indefinitely.
        """
        return self._client.blpop(keys.insert(0, self.key), timeout)

    def bpop_tail(self, keys=[], timeout=0):
        """
        ``pop_tail`` a value off of the first non-empty list named in the
        ``keys`` list and return it together with the ``key`` that unblocked
        it as a two-element tuple.

        If none of the lists in ``keys`` has a value to ``pop_tail``, then
        block for ``timeout`` seconds, or until a value gets pushed on to
        one of the lists.

        If ``timeout`` is 0, then block indefinitely.
        """
        return self._client.brpop(keys.insert(0, self.key), timeout)

    def reverse(self):
        # Only there for the sake of completeness
        raise NotImplementedError("Method 'reverse' not yet implemented")
