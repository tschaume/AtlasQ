from unittest import TestCase

import mongomock
from mongoengine import connect, disconnect
from mongomock import MongoClient


class TestBaseCase(TestCase):

    db_name = "mongoenginetest"

    @classmethod
    def setUpClass(cls) -> None:
        connect(db=cls.db_name, mongo_client_class=MongoClient)

    @classmethod
    def tearDownClass(cls) -> None:
        disconnect()
