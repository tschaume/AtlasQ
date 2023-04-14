from unittest import TestCase

from mongoengine import connect, disconnect
from mongomock import MongoClient


class TestBaseCase(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.db_name = "mongoenginetest"
        connect(cls.db_name, mongo_client_class=MongoClient)

    @classmethod
    def tearDownClass(cls) -> None:
        disconnect()
