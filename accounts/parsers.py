from rest_framework.parsers import JSONParser
from rest_framework.exceptions import ParseError


class ObjectJSONParser(JSONParser):
    def parse(self, stream, media_type=None, parser_context=None):
        data = super().parse(stream, media_type, parser_context)
        if not isinstance(data, dict):
            raise ParseError('The request body must be a JSON object.')
        return data
