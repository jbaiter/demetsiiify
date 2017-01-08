import logging
from datetime import datetime
from urllib.parse import urlencode

import lxml.etree as ET
import requests


NS = {'oai': 'http://www.openarchives.org/OAI/2.0/',
      'mets': 'http://www.loc.gov/METS/'}


class OaiException(Exception):
    pass


class OaiRepository:
    def __init__(self, endpoint):
        self.endpoint = endpoint
        ident_resp = self._make_request('Identify')
        self.name = ident_resp.findtext('.//oai:repositoryName',
                                        namespaces=NS)
        granularity = ident_resp.findtext('.//oai:granularity',
                                          namespaces=NS).lower()
        if granularity == "yyyy-mm-ddthh:mm:ssz":
            self._time_format = '%Y-%m-%dT%H:%M:%SZ'
        elif granularity == "yyyy-mm-dd":
            self._time_format = '%Y-%m-%d'
        else:
            raise ValueError("Unknown granularity: {}".format(granularity))

    def _make_request(self, verb, **kwargs):
        params = {k: v for k, v in kwargs.items() if v}
        params['verb'] = verb
        resp = requests.get(self.endpoint, params=params)
        # TODO: Better error handling
        if resp:
            return ET.fromstring(resp.content)
        else:
            raise OaiException("Error retrieving data from server (code {})"
                               .format(resp.status))

    def _format_time(self, time):
        if isinstance(time, str):
            try:
                datetime.strptime(time, self._time_format)
            except ValueError:
                raise ValueError(
                    "Timestamp does not match required format :{}"
                    .format(self._time_format))
            return time
        elif isinstance(time, datetime):
            return time.strftime(self._time_format)
        else:
            raise ValueError("time must be a string or a datetime object.")

    @property
    def metadata_formats(self):
        if not hasattr(self, '_metadata_formats'):
            resp = self._make_request('ListMetadataFormats')
            self._metadata_formats = set(
                e.text for e in
                resp.findall('.//oai:metadataPrefix', namespaces=NS))
        return self._metadata_formats

    def get_record(self, identifier, metadata_format='mets'):
        if metadata_format not in self.metadata_formats:
            raise ValueError("Unsupported metadata format: {}"
                             .format(metadata_format))
        resp = self._make_request('GetRecord', metadataPrefix=metadata_format,
                                  identifier=identifier)
        if metadata_format == 'mets':
            return resp.find(
                "./oai:GetRecord/oai:record/oai:metadata/mets:mets",
                namespaces=NS)
        else:
            return resp.find("./oai:GetRecord/oai:record", namespaces=NS)

    def list_records(self, metadata_format='mets', set_id=None,
                     since=None):
        if metadata_format not in self.metadata_formats:
            raise ValueError("Unsupported metadata format: {}"
                             .format(metadata_format))
        resp = self._make_request(
            'ListRecords', metadataPrefix=metadata_format, set=set_id,
            **{'from': self._format_time(since) if since else None})
        while True:
            records = resp.findall("./oai:ListRecords/oai:record",
                                   namespaces=NS)
            for record in records:
                if metadata_format == 'mets':
                    yield record.find("./oai:metadata/mets:mets",
                                      namespaces=NS)
                else:
                    yield record
            resumption_token = resp.findtext(".//oai:resumptionToken",
                                             namespaces=NS)
            if not resumption_token:
                break
            else:
                resp = self._make_request(
                    'ListRecords', resumptionToken=resumption_token)

    def list_identifiers(self, metadata_format='mets', set_id=None,
                         since=None, include_sets=False):
        if metadata_format not in self.metadata_formats:
            raise ValueError("Unsupported metadata format: {}"
                             .format(metadata_format))
        resp = self._make_request(
            'ListIdentifiers', metadataPrefix=metadata_format, set=set_id,
            **{'from': self._format_time(since) if since else None})
        while True:
            headers = resp.findall("./oai:ListIdentifiers/oai:header",
                                   namespaces=NS)
            for e in headers:
                identifier = e.findtext('./oai:identifier', namespaces=NS)
                set_spec = e.findtext('./oai:setSpec', namespaces=NS)
                yield (identifier, set_spec) if include_sets else identifier
            resumption_token = resp.findtext(".//oai:resumptionToken",
                                             namespaces=NS)
            if not resumption_token:
                break
            else:
                resp = self._make_request(
                    'ListIdentifiers', resumptionToken=resumption_token)

    def list_record_urls(self, metadata_format='mets', set_id=None,
                         since=None, include_sets=False):
        id_iter = self.list_identifiers(metadata_format, set_id, since, True)
        for identifier, set_id in id_iter:
            params = urlencode({
                'verb': 'GetRecord',
                'identifier': identifier,
                'metadataFormat': metadata_format})
            url = "{}?{}".format(self.endpoint, params)
            yield (url, set_id) if include_sets else url

    def list_sets(self):
        resp = self._make_request('ListSets')
        for elem in resp.findall("./oai:ListSets/oai:set", namespaces=NS):
            yield (elem.findtext("./oai:setSpec", namespaces=NS),
                   elem.findtext("./oai:setName", namespaces=NS))
