"""Handling Starmade Blueprints in App Engine & Datastore"""

from google.appengine.ext import blobstore, ndb

SCHEMA_VERSION_CURRENT = 19

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
    power_recharge = ndb.FloatProperty(indexed=False)
    power_capacity = ndb.FloatProperty(indexed=False)
    date_created = ndb.DateTimeProperty(indexed=True, auto_now_add=True)
    title = ndb.StringProperty(indexed=True) # Indexed for Projection only
