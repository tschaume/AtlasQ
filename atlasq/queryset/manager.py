from typing import Union

from atlasq.queryset.index import AtlasIndex
from atlasq.queryset.queryset import AtlasQuerySet
from mongoengine import QuerySetManager


class AtlasManager(QuerySetManager):
    """
    Manager for the Atlas class.
    """

    @property
    def default(self):
        if self._index:
            return AtlasQuerySet
        res = super().default
        return res

    def __init__(
        self, atlas_index: Union[str, None], definition: Union[dict, None] = None
    ):
        super().__init__()
        self._index = AtlasIndex(atlas_index) if atlas_index else None
        self._definition = definition
        if definition and not self._index._indexed_fields:
            self._index._set_indexed_from_mappings(definition)

    def __get__(self, instance, owner):
        queryset = super().__get__(instance, owner)
        if isinstance(queryset, AtlasQuerySet):
            queryset.index = self._index
            queryset.definition = self._definition
        return queryset
