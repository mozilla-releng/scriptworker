#!/usr/bin/env python
"""Chain of Trust artifact validation and creation.
"""

from scriptworker.client import validate_json_schema


def validate_cot_schema(cot, schema):
    """Simple wrapper function, probably overkill.
    """
    return validate_json_schema(cot, schema, name="chain of trust")
