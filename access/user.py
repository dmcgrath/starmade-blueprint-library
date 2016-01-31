from google.appengine.ext import blobstore, ndb

class User(ndb.Model):
    """Datastore Entity for Users"""
    display_name = ndb.StringProperty(indexed=False)
    profile_url = ndb.StringProperty(indexed=False)
    secret = ndb.StringProperty(indexed=False)
