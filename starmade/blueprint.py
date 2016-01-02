"""Handling Starmade Blueprints in App Engine & Datastore"""

from google.appengine.ext import blobstore, ndb

SCHEMA_VERSION_CURRENT = 11

class Blueprint(ndb.Model):
    """Datastore Entity for Blueprints"""
    blob_key = ndb.StringProperty(indexed=False)
    schema_version = ndb.IntegerProperty(indexed=True,
                                         default=SCHEMA_VERSION_CURRENT)
    context = ndb.JsonProperty(indexed=False)
    elements = ndb.JsonProperty(indexed=False)
    element_count = ndb.IntegerProperty(indexed=True)
    length = ndb.IntegerProperty(indexed=True)
    width = ndb.IntegerProperty(indexed=True)
    height = ndb.IntegerProperty(indexed=True)
    max_dimension = ndb.IntegerProperty(indexed=True)
    class_rank = ndb.IntegerProperty(indexed=True)
    title = ndb.StringProperty(indexed=False)
