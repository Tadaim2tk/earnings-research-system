"""Stable actor identifiers shared by validation and monitoring boundaries."""

import re

HUMAN_IDENTIFIER_PATTERN = re.compile(r"^human:[A-Za-z0-9][A-Za-z0-9._-]*$", re.ASCII)
SYSTEM_POLICY_IDENTIFIER_PATTERN = re.compile(
    r"^system_policy:[a-z0-9][a-z0-9._-]*$", re.ASCII
)


def is_human_identifier(value: str) -> bool:
    return bool(HUMAN_IDENTIFIER_PATTERN.fullmatch(value))


def is_activation_authorizer(value: str) -> bool:
    return is_human_identifier(value) or bool(SYSTEM_POLICY_IDENTIFIER_PATTERN.fullmatch(value))
