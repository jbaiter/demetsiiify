# [demetsiiify](https://demetsiiify.jbaiter.de)

*demetsiiify* is a **web service for creating IIIF manifests from METS/MODS documents.**
It does not store the document images itself, but merely keeps track of the available
dimensions, redirecting to the most suitable original resource when requested via the
IIIF Image API.

It sports the following features:
- Included Annotation Server: Users can create and share annotations using the Mirador
  viewer
- [RESTFul API](https://demetsiiify.jbaiter.de/apidocs) that can be used from scripts and
  other programs
- Every ID in the the generated manifests is fully dereferenceable (i.e. canvases,
  ranges, structures, etc)
- Exposes the complete set of imported documents as a
  [paginated IIIF collection](https://demetsiiify.jbaiter.de/iiif/collection/index/top)
- Rudimentary support for the IIIF Content Search API, allows searching through
  user-created annotations by target and date (no fulltext search, yet)

The service is **available at https://demetsiiify.jbaiter.de**

**To run it on your own machine**, make sure that you have an up-to-date version of both
`docker` and `docker-compose` on your machine. Then, follow these steps:

1. Run `docker-compose up` to start the individual services
2. Run `docker-compose run webapp python manage.py create` to initialise the database

You should then be able to reach the service at http://localhost:5000

## Caveats
Currently the service was only tested with METS/MODS documents that comply with the
[guidelines from the German Research Foundation (DFG)](http://dfg-viewer.de/profil-der-metadaten/),
including most of the ~1.6 million digitized volumes available at the
[Central Directory of Digitized Prints](http://zvdd.de).

If you would like to add support for your own flavor of METS/MODS, feel free to open
an issue with a few example documents and I will try to adapt the software accordingly.
