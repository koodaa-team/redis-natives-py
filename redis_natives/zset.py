from random import randint
from .errors import RedisKeyError
from .datatypes import RedisSortable, Comparable, SetOperatorMixin


class ZOrder(object):
    """
    Enum with supported sort orders of ZSet
    """
    def __new__(self):
        return ZOrder

    @property
    def ASC(self):
        return 0

    @property
    def DESC(self):
        return 1


class ZSet(RedisSortable, Comparable, SetOperatorMixin):
    """
    An Ordered-set datatype for Python. It's a mixture between Redis' ``ZSet``
    and a simple Set-type. Main difference is the concept of a score associated
    with every member of the set.
    """

    __slots__ = ("_key", "_client", "_pipe")

    def __init__(self, client, key, iter=[], type=str, withscores=True):
        super(ZSet, self).__init__(client, key, type=type)
        self._withscores = withscores

        if hasattr(iter, "__iter__") and len(iter):
            # TODO: What if the key already exists?
            for score, val in iter:
                self._pipe.zadd(val, score)
            self._pipe.execute()
        self.tuple2scalar = lambda a: a[0]
        self.tmp_keys = []
        self.aggregate = 'sum'

    def type_convert_tuple(self, value):
        if isinstance(value, tuple):
            return (self.type_convert(value[0]), value[1])
        else:
            return self.type_convert(value)

    @property
    def data(self):
        return map(
            self.type_convert_tuple,
            self._client.zrange(
                self.key,
                0,
                -1,
                withscores=True)
        )

    @property
    def values(self):
        return map(
            self.type_convert_tuple,
            self._client.zrange(self.key, 0, -1)
        )

    @property
    def items(self):
        return map(
            self.type_convert_tuple,
            self._client.zrange(self.key, 0, -1, withscores=True)
        )

    def __len__(self):
        return self._client.zcard(self.key)

    def __contains__(self, value):
        return self._client.zscore(self.key, value) is not None

    def __iter__(self):
        # TODO: Is there a better way than getting ALL at once?
        if self._withscores:
            data = self.items
        else:
            data = self.values
        for item in data:
            yield item

    def __repr__(self):
        return str(self.data)

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
                self.type_convert_tuple,
                self._client.zrange(
                    self._key,
                    start,
                    stop,
                    withscores=self._withscores)
            )
        else:
            return self.type_convert_tuple(
                self._client.zrange(
                    self._key,
                    key,
                    key,
                    withscores=self._withscores)[0]
            )

    def __setitem__(self, key, value):
        value = self.type_prepare(value)
        if isinstance(key, slice):
            raise TypeError('Setting slice ranges not supported for zsets.')
        else:
            item, rank = self._client.zrange(
                self._key,
                key,
                key,
                withscores=self._withscores
            )[0]
            return self._client.zadd(self._key, value, rank)

    def add(self, el, score):
        """
        Add element ``el`` with ``score`` to this ``ZSet``
        """
        try:
            return self._client.zadd(self.key, str(el), long(score))
        except ValueError:
            return False

    def discard(self, member):
        """
        Remove ``member`` form this set;
        Do nothing when element is not a member
        """
        self._client.zrem(self.key, member)

    def copy(self, key):
        """
        Return copy of this ``ZSet`` as new ``ZSet`` with key ``key``
        """
        self._client.zunionstore(key, [self.key])
        return ZSet(self._client, key)

    def union(self, *others):
        """
        Return the union of this set and others as new set
        """
        data = set(self.data)
        for other in others:
            for element in other:
                data.add(element)
        return data

    def update(self, *others, **kwargs):
        """
        Return the union of this set and others as new set
        """
        aggregate = self.aggregate
        if 'aggregate' in kwargs:
            aggregate = kwargs['aggregate']

        redis_keys = self.parse_args(others)
        if redis_keys:
            self._pipe.zunionstore(
                self.key,
                redis_keys,
                aggregate=aggregate
            )
            self._delete_temporary()
            self._pipe.execute()

    def intersection(self, *others, **kwargs):
        """
        Return the intersection of this set and others as new set
        """
        aggregate = self.aggregate
        if 'aggregate' in kwargs:
            aggregate = kwargs['aggregate']

        redis_keys = self.parse_args(others)
        temporary_key = '__tmp__intersection'
        self.tmp_keys.append(temporary_key)
        if redis_keys:
            self._pipe.zinterstore(
                temporary_key,
                redis_keys,
                aggregate=aggregate
            )
            self._pipe.zrange(temporary_key, 0, -1, withscores=True)
            i = self._delete_temporary()
            return set(
                map(self.type_convert_tuple, self._pipe.execute()[-i - 1])
            )

    def intersection_update(self, *others, **kwargs):
        """
        Update this set with the intersection of itself and others

        Accepts both native python sets and redis ZSet objects as arguments

        Uses single redis pipe for the whole procedure (= very fast)
        """
        aggregate = self.aggregate
        if 'aggregate' in kwargs:
            aggregate = kwargs['aggregate']

        redis_keys = self.parse_args(others)
        if redis_keys:
            self._pipe.zinterstore(
                self.key,
                redis_keys,
                aggregate=aggregate
            )
            self._delete_temporary()
            self._pipe.execute()

    def difference(self, *others):
        """
        Return the difference between this set and other as new set
        """
        data = set(self.data)
        for other in others:
            data -= other
        return data

    def difference_update(self, *others):
        """
        Remove all elements of other sets from this set
        """
        pipe = self._pipe
        pipe.delete(self.key)
        for element in self.difference(*others):
            pipe.zadd(self.key, element[0], element[1])
        pipe.execute()

    def symmetric_difference(self, *others):
        """
        Return the symmetric difference of this set and others as new set
        """
        data = set(self.data)
        for other in others:
            data = data.symmetric_difference(other)
        return data

    def symmetric_difference_update(self, *others):
        """
        Update this set with the symmetric difference of itself and others
        """
        key_union = self.generate_temporary_key()
        key_inter = self.generate_temporary_key()
        self.tmp_keys = [key_union, key_inter]

        redis_keys = self.parse_args(others)

        if redis_keys:
            self._pipe.zinterstore(key_inter, redis_keys) \
                .zunionstore(key_union, redis_keys)
            self._pipe.zrange(key_union, 0, -1, withscores=True)
            self._pipe.zrange(key_inter, 0, -1, withscores=True)
            i = self._delete_temporary()
            values = self._pipe.execute()
            diff = set(values[-2 - i]) - set(values[-1 - i])
            self._pipe.delete(self.key)
            for element, score in diff:
                self._pipe.zadd(self.key, element, score)
            self._pipe.execute()
        return set()

    def clear(self):
        """
        Purge/delete all elements from this set
        """
        return self._client.delete(self.key)

    def pop(self):
        """
        Remove and return a random element from the sorted set.
        Raises ``RedisKeyError`` if  set is empty.
        """
        length = self.__len__()
        if (length == 0):
            raise RedisKeyError("ZSet is empty")
        idx = randint(0, length - 1)
        value = self._pipe.zrange(
            self.key,
            idx,
            idx
        ).zremrangebyrank(self.key, idx, idx).execute()[0][0]

        return self.type(value)

    def incr_score(self, el, by=1):
        """
        Increment score of ``el`` by value ``by``
        """
        return self._client.zincrby(self.key, el, by)

    def rank_of(self, el, order=ZOrder.ASC):
        """
        Return the ordinal index of element ``el`` in the sorted set,
        whereas the sortation is based on scores and ordered according
        to the ``order`` enum.
        """
        if (order == ZOrder.ASC):
            return self._client.zrank(self.key, el)
        elif (order == ZOrder.DESC):
            return self._client.zrevrank(self.key, el)

    def score_of(self, el):
        """
        Return the associated score of element ``el`` in the sorted set.
        When ``el`` is not a member ``NoneType`` will be returned.
        """
        return self._client.zscore(self.key, el)

    def range_by_rank(self, min, max, order=ZOrder.ASC):
        """
        Return a range of elements from the sorted set by specifying ``min``
        and ``max`` ordinal indexes, whereas the sortation is based on
        scores and ordered according to the given ``order`` enum.
        """
        if (order == ZOrder.ASC):
            return self._client.zrange(self.key, min, max)
        elif (order == ZOrder.DESC):
            return self._client.zrevrange(self.key, min, max)

    def range_by_score(self, min, max):
        """
        Return a range of elements from the sorted set by specifying ``min``
        and ``max`` score values, whereas the sortation is based on scores
        with a descending order.
        """
        return self._client.zrangebyscore(self.key, min, max)

    def range_by_score_limit(self, limit=20, before=0, treshold=20):
        """
        Return a range of elements from the sorted set by specifying ``min``
        score value and the limit of items to be returned

        Note: only works for integer based scores
        """
        if not before:
            return self._client.zrevrange(
                self.redis_key,
                0,
                limit,
                withscores=True
            )
        else:
            items = []
            while len(items) < limit:
                items += self._client.zrevrangebyscore(
                    self.redis_key,
                    before - 1,
                    before - 1 - limit - treshold,
                    withscores=self._withscores)
                if before <= 0:
                    break
                before -= limit + self.treshold

        return map(self.type_convert_tuple, items[:limit])

    def grab(self):
        """
        Return a random element from the sorted set
        """
        length = self.__len__()
        if (length == 0):
            return None
        idx = randint(0, length - 1)
        return self._pipe.zrange(self.key, idx, idx)[0]

    def intersection_copy(self, dstKey, aggregate, *otherKeys):
        """
        Return the intersection of this set and others as new set
        """
        otherKeys.append(self.key)
        return self._client.zinterstore(dstKey, otherKeys, aggregate)

    def union_copy(self, dstKey, aggregate, *otherKeys):
        otherKeys.append(self.key)
        return self._client.zunionstore(dstKey, otherKeys, aggregate)

    def remove_range_by_rank(self, min, max):
        """
        Remove a range of elements from the sorted set by specifying the
        constraining ordinal indexes ``min`` and ``max``.
        """
        return self._client.zremrangebyrank(self.key, min, max)

    def remove_range_by_score(self, min, max):
        """
        Remove a range of elements from the sorted set by specifying the
        constraining score values ``min`` and ``max``.
        """
        return self._client.zremrangebyscore(self.key, min, max)
