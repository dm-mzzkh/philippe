"""Errors raised while loading or validating a form."""


class FormError(Exception):
    """A ``form.yaml`` could not be read, parsed, or validated.

    The message carries enough context (file path, field key, field type) for
    the operator to fix the file without reading a traceback.
    """
