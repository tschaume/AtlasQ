import copy
import logging
import time
from typing import Any, Dict, List, Tuple

from atlasq.queryset.exceptions import AtlasIndexError, AtlasQueryError
from atlasq.queryset.index import AtlasIndex
from atlasq.queryset.node import AtlasQ
from mongoengine import Q, QuerySet
from pymongo.command_cursor import CommandCursor


def clock(func):
    def clocked(self, *args, **kwargs):
        start_time = time.perf_counter()
        result = func(self, *args, **kwargs)
        elapsed = time.perf_counter() - start_time
        floor = f"{elapsed:0.3f}"
        self.logger.info(f"{floor} - {result}")
        return result

    return clocked


# pylint: disable=too-many-instance-attributes
class AtlasQuerySet(QuerySet):
    def _clone_into(self, new_qs):
        copy_props = (
            "index",
            "_aggrs_query",
            "_search_result",
            "_other_aggregations",
        )
        qs = super()._clone_into(new_qs)
        for prop in copy_props:
            val = getattr(self, prop)
            setattr(new_qs, prop, copy.copy(val))
        return qs

    def __init__(self, document, collection):
        super().__init__(document, collection)
        self._query_obj = AtlasQ()
        self.index: AtlasIndex = None

        self._aggrs_query: List[Dict[str, Any]] = None
        self._search_result: CommandCursor = None
        self._other_aggregations: List[Dict] = []
        self.logger = logging.getLogger(
            f"{__name__}.{self._document._get_collection_name()}"
        )

    # pylint: disable=too-many-arguments
    def upload_index(
        self,
        json_index: Dict,
        user: str,
        password: str,
        group_id: str,
        cluster_name: str,
    ):
        db_name = self._document._get_db().name  # pylint: disable=protected-access
        collection_name = (
            self._document._get_collection_name()
        )  # pylint: disable=protected-access
        if "collectionName" not in json_index:
            json_index["collectionName"] = collection_name
        if "database" not in json_index:
            json_index["database"] = db_name
        if "name" not in json_index:
            json_index["name"] = self.index._index  # pylint: disable=protected-access
        self.logger.info(f"Sending {json_index} to create new index")
        return self.index.upload_index(
            json_index, user, password, group_id, cluster_name
        )

    def ensure_index(self, user: str, password: str, group_id: str, cluster_name: str):
        db_name = self._document._get_db().name  # pylint: disable=protected-access
        collection_name = (
            self._document._get_collection_name()
        )  # pylint: disable=protected-access
        return self.index.ensure_index_exists(
            user, password, group_id, cluster_name, db_name, collection_name
        )

    def __iter__(self):
        return iter(self._cursor)

    def delete(self, write_concern=None, _from_doc_delete=False, cascade_refs=None):
        # we need to get the mongoengine query, the fastest way it to just call _cursor
        assert self._cursor is not None
        assert self._query is not None
        return super().delete(
            write_concern=write_concern,
            _from_doc_delete=_from_doc_delete,
            cascade_refs=cascade_refs,
        )

    @property
    @clock
    def _aggrs(self):
        # corresponding of _query for us
        if self._aggrs_query is None:
            self._aggrs_query = self._query_obj.to_query(self._document)
            if self._aggrs_query:
                if self._ordering:
                    self._aggrs_query[0]["$search"]["sort"].update(dict(self._ordering))
            else:
                if self._ordering:
                    raise AtlasQueryError(
                        "Atlas search does not support ordering without filtering."
                    )
            self._aggrs_query += self._get_projections()
            self._aggrs_query += self._other_aggregations
        return self._aggrs_query

    @property
    def _cursor(self):
        if not self._search_result:
            self._search_result = self.__collection_aggregate(self._aggrs)

        self._cursor_obj = [self._document(**d) for d in self._search_result]
        return super()._cursor

    def order_by(self, *keys):
        if not keys:
            return self
        qs: AtlasQuerySet = self.clone()
        order_by: List[Tuple[str, int]] = qs._get_order_by(keys)
        qs._ordering = order_by  # pylint: disable=protected-access
        return qs

    def __getitem__(self, key):
        if isinstance(key, int):
            from mongoengine.queryset.base import BaseQuerySet

            qs = self.clone()
            qs._limit = 1
            return BaseQuerySet.__getitem__(qs, key)
        return super().__getitem__(key)

    def __collection_aggregate(self, final_pipeline, **kwargs):
        collection = self._collection
        if self._read_preference is not None or self._read_concern is not None:
            collection = self._collection.with_options(
                read_preference=self._read_preference, read_concern=self._read_concern
            )
        self.logger.debug(final_pipeline)
        return collection.aggregate(final_pipeline, cursor={}, **kwargs)

    def __call__(self, q_obj=None, **query):
        if self.index is None:
            raise AtlasIndexError("Index is not set")

        q = AtlasQ(**query)
        if q_obj is not None:
            q &= q_obj
        self.logger.debug(q)
        qs = super().__call__(q)
        return qs

    def _get_projections(self) -> List[Dict[str, Any]]:
        loaded_fields = self._document.objects._loaded_fields.as_dict()
        loaded_fields["meta"] = "$$SEARCH_META"
        return [{"$project": loaded_fields}]

    def count(self, with_limit_and_skip=False):  # pylint: disable=unused-argument
        pipeline = self._aggrs + [{"$count": "count"}]
        cursor = self.__collection_aggregate(pipeline)
        try:
            count = next(cursor)
        except StopIteration:
            self._len = 0  # pylint: disable=attribute-defined-outside-init
        else:
            self._len = count["count"]
        return self._len

    def limit(self, n):
        qs = self.clone()
        qs._limit = n  # pylint: disable=protected-access
        qs._prepend({"$limit": n})
        return qs

    def skip(self, n):
        qs = self.clone()
        qs._skip = n  # pylint: disable=protected-access
        qs._prepend({"$skip": n})
        return qs

    def _prepend(self, stage, before="$project"):
        for idx, stg in enumerate(self._aggrs):
            if before in stg:
                self._aggrs.insert(idx, stage)
                break
        else:
            self._aggrs.append(stage)
