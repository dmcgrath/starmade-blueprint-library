"""Handling Starmade Blueprint name searching in App Engine"""

from google.appengine.api import search
from datetime import datetime

_INDEX_NAME = "blueprints"

def create_document(title, blue_key):
    """Creates a search.Document from the blueprint name."""

    # Let the search service supply the document id.
    doc = search.Document(
        fields=[search.TextField(name='title', value=title),
                search.TextField(name='blue_key', value=blue_key),
                search.DateField(name='date', value=datetime.now().date())])

    search.Index(name=_INDEX_NAME).put(doc)

    return None
