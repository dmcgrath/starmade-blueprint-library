"""Handling Starmade Blueprints in App Engine & Datastore"""

from google.appengine.ext import blobstore, ndb

SCHEMA_VERSION_CURRENT = 25

class Blueprint(ndb.Model):
    """Datastore Entity for Blueprints"""
    attached_count = ndb.IntegerProperty(indexed=False)
    blob_key = ndb.StringProperty(indexed=False)
    class_rank = ndb.IntegerProperty(indexed=True)
    context = ndb.JsonProperty(indexed=False)
    date_created = ndb.DateTimeProperty(indexed=True, auto_now_add=True)
    element_count = ndb.IntegerProperty(indexed=True)
    elements = ndb.JsonProperty(indexed=False)
    header_hash = ndb.StringProperty(indexed=False)
    height = ndb.IntegerProperty(indexed=False)
    length = ndb.IntegerProperty(indexed=False)
    max_dimension = ndb.IntegerProperty(indexed=True)
    power_recharge = ndb.FloatProperty(indexed=False)
    power_capacity = ndb.FloatProperty(indexed=False)
    schema_version = ndb.IntegerProperty(indexed=True,
                                         default=SCHEMA_VERSION_CURRENT)
    systems = ndb.StringProperty(indexed=False, repeated=True)
    title = ndb.StringProperty(indexed=True) # Indexed for Projection only
    user = ndb.StringProperty(indexed=True)
    width = ndb.IntegerProperty(indexed=False)

class BlueprintAttachment(ndb.Model):
    """Datastore Entity for Attachments on Blueprints"""
    blob_key = ndb.StringProperty(indexed=False)
    class_rank = ndb.IntegerProperty(indexed=True)
    context = ndb.JsonProperty(indexed=False)
    depth = ndb.IntegerProperty(indexed=True)
    element_count = ndb.IntegerProperty(indexed=True)
    elements = ndb.JsonProperty(indexed=False)
    header_hash = ndb.StringProperty(indexed=True)
    height = ndb.IntegerProperty(indexed=True)
    length = ndb.IntegerProperty(indexed=True)
    max_dimension = ndb.IntegerProperty(indexed=True)
    path = ndb.StringProperty(indexed=True, repeated=True)
    power_recharge = ndb.FloatProperty(indexed=False)
    power_capacity = ndb.FloatProperty(indexed=False)
    schema_version = ndb.IntegerProperty(indexed=True,
                                         default=SCHEMA_VERSION_CURRENT)
    systems = ndb.StringProperty(indexed=False, repeated=True)
    title = ndb.StringProperty(indexed=True) # Indexed for Projection only
    width = ndb.IntegerProperty(indexed=True)
